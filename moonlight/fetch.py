"""Fetch: ask Open Targets about a disease, its proteins, and their medicines.

Four questions, four functions:

    search_diseases(text)          -> list of Disease, best match first
    fetch_disease(disease_id)      -> one Disease with its description filled in
    fetch_targets(disease, limit)  -> list of Target, highest score first
    fetch_paths(disease, target)   -> list of Path, one per Medicine family

and one about the data itself:

    data_version()                 -> the Open Targets data release, like "26.09"

Nothing here sorts medicines into groups or ranks them.

Every question goes through _post_json. It looks in the saved results
(moonlight/cache.py) first and only asks Open Targets when the answer is
not there. Tests that swap _post_json swap the saved results out with it.
Every real HTTP call goes through _send, on one shared connection.

Field names were read from the saved responses in fixtures/ and from
docs/schema-notes.md, not from memory. "meta", "dataVersion", "year",
"month" and "iteration" were read from the live API on 2026-11-12.
"""

import threading
import time
from typing import Dict, List, Optional

import requests

from moonlight import cache
from moonlight.records import (
    Disease,
    Medicine,
    MedicineForm,
    Path,
    Target,
    stronger_stage,
)

URL = "https://api.platform.opentargets.org/api/v4/graphql"
TIMEOUT_SECONDS = 30
SEARCH_SIZE = 10
VERSION_CHECK_SECONDS = 3600  # a long-running program reads the version again after this
# Kashish's decision, 2026-11-12. Open Targets sometimes gives a short
# answer to "which medicines act on this protein?", with reports missing.
# So that question is asked twice, and a third time only if the first two
# answers differ. The answer with the most clinical reports is kept, and
# only then is it saved. The medicines must be the same in every answer.
# If they are not, Moonlight stops and saves nothing.
ASKS_AT_FIRST = 2
ASKS_AT_MOST = 3

VERSION_QUERY = """
query DataVersion {
  meta { dataVersion { year month iteration } }
}
"""

SEARCH_QUERY = """
query DiseaseSearch($text: String!, $size: Int!) {
  search(queryString: $text, entityNames: ["disease"], page: {index: 0, size: $size}) {
    total
    hits { id entity name }
  }
}
"""

DISEASE_QUERY = """
query DiseaseRecord($diseaseId: String!) {
  disease(efoId: $diseaseId) { id name description }
}
"""

TARGETS_QUERY = """
query AssociatedTargets($diseaseId: String!, $size: Int!) {
  disease(efoId: $diseaseId) {
    id
    associatedTargets(page: {index: 0, size: $size}) {
      count
      rows {
        score
        target { id approvedSymbol approvedName }
      }
    }
  }
}
"""

TARGET_DRUGS_QUERY = """
query TargetDrugs($targetId: String!) {
  target(ensemblId: $targetId) {
    id
    drugAndClinicalCandidates {
      count
      rows {
        drug {
          id
          name
          maximumClinicalStage
          parentMolecule { id name }
          mechanismsOfAction {
            rows {
              actionType
              targets { id }
            }
          }
          indications {
            rows { maxClinicalStage disease { id } }
          }
        }
        clinicalReports { url }
      }
    }
  }
}
"""


class FetchError(RuntimeError):
    """Open Targets answered, but with an error instead of data."""


class AnswersDisagree(FetchError):
    """Asked the same question again, Open Targets named different medicines."""


# One connection to Open Targets, opened once and used for every call.
_session = requests.Session()

_version: Optional[str] = None
_version_read_at = 0.0
_version_lock = threading.Lock()
_turn = threading.local()  # see started()


def _send(body: dict) -> dict:
    """The one place Moonlight talks to Open Targets. Tests replace this."""
    response = _session.post(URL, json=body, timeout=TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.json()


def data_version() -> str:
    """The Open Targets data release, read from the API. Like "26.09".

    It is read once and remembered, because every saved result is filed
    under it. A program that runs for a long time reads it again every hour.
    """
    global _version, _version_read_at
    with _version_lock:
        now = time.monotonic()
        if _version is None or now - _version_read_at > VERSION_CHECK_SECONDS:
            answer = _send({"query": VERSION_QUERY, "variables": {}})
            if answer.get("errors") or not answer.get("data"):
                raise FetchError(f"Open Targets did not give its data version: {answer}")
            version = answer["data"]["meta"]["dataVersion"]
            parts = [version["year"], version["month"], version["iteration"]]
            _version = ".".join(str(part) for part in parts if part)
            _version_read_at = now
        return _version


def forget_version() -> None:
    """Forget the data version, so the next question reads it again."""
    global _version
    with _version_lock:
        _version = None


def _is_good(answer: dict) -> bool:
    return not answer.get("errors") and answer.get("data") is not None


def _rows(answer: dict) -> List[dict]:
    target = answer["data"].get("target") or {}
    return (target.get("drugAndClinicalCandidates") or {}).get("rows") or []


def _report_count(answer: dict) -> int:
    """How many clinical reports a medicines-for-a-protein answer holds."""
    return sum(len(row.get("clinicalReports") or []) for row in _rows(answer))


def _medicine_ids(answer: dict) -> List[str]:
    """The id of every medicine form in the answer, sorted."""
    return sorted((row.get("drug") or {}).get("id") or "" for row in _rows(answer))


def _send_keeping_the_fullest(body: dict) -> dict:
    """Ask twice. Ask a third time only if the first two answers differ.
    Keep the answer with the most clinical reports in total.

    If two answers are equally full, the earlier one is kept. An answer
    that is an error is handed straight back. If the answers do not hold
    the same medicines, AnswersDisagree is raised and nothing is saved.
    """
    answers: List[dict] = []
    while len(answers) < ASKS_AT_MOST:
        answer = _send(body)
        if not _is_good(answer):
            return answer
        answers.append(answer)
        if _medicine_ids(answer) != _medicine_ids(answers[0]):
            raise AnswersDisagree(
                "Open Targets gave different medicines for the same question "
                f"({body['variables']}). Nothing was saved. Please tell Kashish."
            )
        if len(answers) == ASKS_AT_FIRST and answers[0] == answers[1]:
            break
    return max(answers, key=_report_count)  # max keeps the earliest of equals


def _post_json(body: dict) -> dict:
    """One question for Open Targets: from the saved results if it is there,
    from the network if not. Only good answers are saved. Tests replace this.
    """
    version = data_version()
    saved = cache.load("open-targets", version, body)
    if saved is not None:
        return saved
    if body["query"] == TARGET_DRUGS_QUERY:
        answer = _send_keeping_the_fullest(body)
    else:
        answer = _send(body)
    if _is_good(answer):
        cache.save("open-targets", version, body, answer)
    return answer


def started(tell) -> None:
    """Ask to be told when this thread next begins a question.

    tell is called once, with nothing, at that moment. The engine uses it to
    start several proteins in order: the next one sets off as soon as this
    one has begun.
    """
    _turn.tell = tell


def _ask(query: str, variables: dict) -> dict:
    """Send one question and hand back the "data" part of the answer."""
    tell = getattr(_turn, "tell", None)
    if tell is not None:
        _turn.tell = None
        tell()
    answer = _post_json({"query": query, "variables": variables})
    if answer.get("errors"):
        raise FetchError(f"Open Targets returned errors: {answer['errors']}")
    data = answer.get("data")
    if data is None:
        raise FetchError("Open Targets returned no data.")
    return data


def search_diseases(text: str) -> List[Disease]:
    """Diseases matching the words, in the order Open Targets ranks them."""
    data = _ask(SEARCH_QUERY, {"text": text, "size": SEARCH_SIZE})
    return [
        Disease(id=hit["id"], name=hit["name"])
        for hit in data["search"]["hits"]
        if hit["entity"] == "disease"
    ]


def fetch_disease(disease_id: str) -> Optional[Disease]:
    """The disease with its description filled in. None if the id is not known.

    Open Targets may send no description at all. Then it stays "", and
    nothing is made up to fill the gap.
    """
    data = _ask(DISEASE_QUERY, {"diseaseId": disease_id})
    record = data["disease"]
    if record is None:
        return None
    return Disease(
        id=record["id"],
        name=record["name"],
        description=(record["description"] or "").strip(),
    )


def fetch_targets(disease: Disease, limit: int = 25) -> List[Target]:
    """The proteins most strongly linked to the disease, highest score first."""
    data = _ask(TARGETS_QUERY, {"diseaseId": disease.id, "size": limit})
    if data["disease"] is None:
        return []
    targets = [
        Target(
            id=row["target"]["id"],
            symbol=row["target"]["approvedSymbol"],
            name=row["target"]["approvedName"],
            score=row["score"],
        )
        for row in data["disease"]["associatedTargets"]["rows"]
    ]
    # Rows arrive highest first already. Sorting keeps the promise even if
    # that ever changes; equal scores keep the order they arrived in.
    targets.sort(key=lambda target: target.score, reverse=True)
    return targets


def _disease_stage(drug: dict, disease_id: str) -> Optional[str]:
    """How far this one form got for our disease. None if it has no link."""
    stage = None
    for indication in drug["indications"]["rows"]:
        linked = indication["disease"]
        if linked and linked["id"] == disease_id:
            stage = stronger_stage(stage, indication["maxClinicalStage"])
    return stage


def _action_types_on(drug: dict, target_id: str) -> List[str]:
    """What this form does to OUR target, ignoring its other targets."""
    found = []
    for mechanism in drug["mechanismsOfAction"]["rows"]:
        if any(hit["id"] == target_id for hit in mechanism["targets"]):
            action = mechanism["actionType"]
            if action and action not in found:
                found.append(action)
    return found


def _same_machine_ids(drug: dict, target_id: str) -> List[str]:
    """The other proteins that are pieces of the same machine as OUR target.

    One mechanism row is one machine. If a row lists our target, every other
    target in that row is a piece of the same machine.
    """
    found = []
    for mechanism in drug["mechanismsOfAction"]["rows"]:
        ids = [hit["id"] for hit in mechanism["targets"]]
        if target_id in ids:
            for other in ids:
                if other != target_id and other not in found:
                    found.append(other)
    return found


def fetch_paths(disease: Disease, target: Target) -> List[Path]:
    """One Path per medicine family acting on the target.

    A form with a parent joins its parent's family, and the family is named
    after the parent. Families come out in the order Open Targets first
    mentions them.
    """
    data = _ask(TARGET_DRUGS_QUERY, {"targetId": target.id})
    if data["target"] is None:
        return []

    families: Dict[str, dict] = {}  # family id -> what we have gathered so far
    for row in data["target"]["drugAndClinicalCandidates"]["rows"]:
        drug = row["drug"]
        if drug is None:
            continue
        parent = drug["parentMolecule"]
        family_id = parent["id"] if parent else drug["id"]
        family = families.setdefault(
            family_id, {"name": None, "forms": [], "actions": [], "sources": [], "machine": []}
        )
        if parent:
            # Named after the parent, even if the parent has no row of its own.
            family["name"] = family["name"] or parent["name"]
        else:
            family["name"] = drug["name"]

        form = MedicineForm(
            id=drug["id"],
            name=drug["name"],
            best_stage=drug["maximumClinicalStage"],
            disease_stage=_disease_stage(drug, disease.id),
            parent_id=parent["id"] if parent else None,
        )
        if parent:
            family["forms"].append(form)
        else:
            family["forms"].insert(0, form)  # the parent itself goes first

        for action in _action_types_on(drug, target.id):
            if action not in family["actions"]:
                family["actions"].append(action)
        for other in _same_machine_ids(drug, target.id):
            if other not in family["machine"]:
                family["machine"].append(other)
        for report in row["clinicalReports"]:
            url = report["url"]
            if url and url not in family["sources"]:
                family["sources"].append(url)

    return [
        Path(
            medicine=Medicine(name=family["name"], forms=family["forms"]),
            target=target,
            disease=disease,
            action_types=family["actions"],
            score=target.score,
            sources=family["sources"],
            same_machine_ids=sorted(family["machine"]),
        )
        for family in families.values()
    ]
