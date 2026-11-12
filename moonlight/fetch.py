"""Fetch: ask Open Targets about a disease, its proteins, and their medicines.

Four questions, four functions:

    search_diseases(text)          -> list of Disease, best match first
    fetch_disease(disease_id)      -> one Disease with its description filled in
    fetch_targets(disease, limit)  -> list of Target, highest score first
    fetch_paths(disease, target)   -> list of Path, one per Medicine family

Nothing here sorts medicines into groups or ranks them. Every HTTP call
goes through _post_json, so tests can swap that one function for saved files.

Field names were read from the saved responses in fixtures/ and from
docs/schema-notes.md, not from memory.
"""

from typing import Dict, List, Optional

import requests

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


def _post_json(body: dict) -> dict:
    """The one place Moonlight talks to Open Targets. Tests replace this."""
    response = requests.post(URL, json=body, timeout=TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.json()


def _ask(query: str, variables: dict) -> dict:
    """Send one question and hand back the "data" part of the answer."""
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
            family_id, {"name": None, "forms": [], "actions": [], "sources": []}
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
        )
        for family in families.values()
    ]
