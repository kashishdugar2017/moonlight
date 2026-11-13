"""The small API behind Sidha's page. Medicine first.

    GET /                                   the page (web/index.html)
    GET /api/search?q=                      matching diseases, best first, and "did you mean"
    GET /api/clues?disease_id=              Kashish's ranked clues, no explanations
    GET /api/explain?disease_id=&clue_id=   one clue's explanation

Run it with:  uvicorn moonlight.api:app

Nothing here fetches, filters, ranks or explains by itself. It asks
fetch.py, engine.py, rank.py and explain.py, and turns their answers into
JSON. Only new clues and medicines being studied are ever named. Medicines
that are left out are sent as three counts and nothing else.

Nothing is remembered between requests, so /api/explain looks the disease
up again to find its clue. (Remembering is a later ticket.)
"""

import pathlib
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional, Tuple

import requests
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

from moonlight import explain, translate
from moonlight.engine import find_clues
from moonlight.fetch import (
    FetchError,
    fetch_disease,
    fetch_targets,
    search_diseases,
    search_matches,
)
from moonlight.filter import (
    ALREADY_APPROVED,
    BEING_STUDIED,
    GROUPS,
    NEW_CLUE,
    NOT_APPROVED,
    SHOWN_GROUPS,
    UNCLEAR_LINK,
)
from moonlight.rank import RULE_TEXT, Clue, rank_clues
from moonlight.records import Disease, Path

PAGE = pathlib.Path(__file__).resolve().parent.parent / "web" / "index.html"
TOP_TARGETS = 25  # the same number of proteins the terminal runner looks at

# The left-out groups, in the order they are sent. Counts only.
LEFT_OUT_GROUPS = (NOT_APPROVED, ALREADY_APPROVED, UNCLEAR_LINK)

# "Did you mean" is given up on after this long, counted from the start of
# the search: Gemini's 3 seconds, and 2 more to look its names up in Open
# Targets. The normal matches never wait longer than this for it.
DID_YOU_MEAN_SECONDS = translate.GEMINI_SECONDS + 2
# Where "did you mean" runs while the normal search runs.
_side_lane = ThreadPoolExecutor(max_workers=8, thread_name_prefix="did-you-mean")

app = FastAPI(title="Moonlight", docs_url=None, redoc_url=None, openapi_url=None)


class _Found:
    """Everything worked out for one disease in one request."""

    def __init__(self, disease: Disease, tray: Dict[str, List[Path]]):
        self.disease = disease
        # The same steps as engine.find_ranked_clues. They are done here so
        # the names from every group can also go to the explainer's check.
        self.new_clues = rank_clues(tray[NEW_CLUE])
        self.being_studied = rank_clues(tray[BEING_STUDIED])
        self.left_out = {
            # A medicine that acts on two proteins is still one medicine.
            group: len({path.medicine.name for path in tray[group]})
            for group in GROUPS
            if group not in SHOWN_GROUPS
        }
        # Every medicine name Moonlight met, shown or not. Only the
        # explainer's check sees these. They are never sent to anyone.
        names = set()
        for paths in tray.values():
            for path in paths:
                names.add(path.medicine.name)
                names.update(form.name for form in path.medicine.forms)
        self.known_names = names


def _find(disease_id: str) -> _Found:
    """Disease -> its top proteins -> the sorted, ranked clues."""
    try:
        disease = fetch_disease(disease_id)
        if disease is None:
            raise HTTPException(status_code=404, detail="Open Targets does not know this disease.")
        targets = fetch_targets(disease, TOP_TARGETS)
        return _Found(disease, find_clues(disease, targets))
    except (FetchError, requests.RequestException):
        raise HTTPException(
            status_code=502, detail="Could not get the data from Open Targets."
        ) from None


def _clue_id(clue: Clue) -> str:
    """The id shared by a medicine and its tablet forms (as in rank.py)."""
    first = clue.medicine.forms[0]
    return first.parent_id or first.id


def _one_source(clue: Clue) -> Optional[str]:
    """One link, from the strongest protein that has one. None if there is none."""
    for path in clue.paths:
        for source in path.sources:
            if source.startswith("https://"):
                return source
    return None


def _clue_json(clue: Clue, disease: Disease) -> dict:
    """One clue's facts. No explanation, so this is quick."""
    # The names, the points and the ending come from explain.py, so a card
    # and its explanation always say the same thing.
    facts = explain.facts_for(clue, disease)
    machine_of: Dict[str, Tuple[int, bool]] = {}
    for number, machine in enumerate(clue.machines, start=1):
        for path in machine:
            machine_of[path.target.id] = (number, len(machine) > 1)

    proteins = []
    for path in clue.paths:  # a Clue keeps its paths strongest first
        number, shared = machine_of[path.target.id]
        proteins.append(
            {
                "symbol": path.target.symbol,
                # Whole points out of 100, rounded the way explain.py does.
                "points": round(float(f"{path.score:.2f}") * 100),
                "direction": path.direction,
                "machine": number,  # proteins with the same number are one machine
                "piece_of_machine": shared,
            }
        )
    return {
        "id": _clue_id(clue),
        "medicine": facts["medicine"]["name"],
        "forms": facts["medicine"]["forms"],
        "proteins": proteins,
        "reports": clue.reports,
        "source": _one_source(clue),
        "trial_phase": facts.get("trial_phase"),  # only for being studied
        "ending": explain.ending_for(facts),
    }


@app.get("/", response_class=HTMLResponse)
def page() -> str:
    return PAGE.read_text(encoding="utf-8")


@app.get("/api/search")
def search(q: str = "") -> dict:
    """The matches, as before, plus "did_you_mean" and "also_called".

    Two swimmers, two lanes. Gemini's guesses set off in the side lane
    while the normal Open Targets search swims here. If the side lane is
    slow or goes wrong, the matches still come back, with no suggestions
    and no error. Moonlight never picks a disease: it only offers them.
    """
    text = q.strip()
    if not text:
        return {"matches": []}
    give_up_at = time.monotonic() + DID_YOU_MEAN_SECONDS
    guessing = _side_lane.submit(translate.did_you_mean, text)
    try:
        matches = search_diseases(text)
        # The same question once more, answered from the saved results:
        # is what the person typed one of an entry's "also called" names?
        also_called = {
            match.disease.id: translate.small_print(text, match)
            for match in search_matches(text)
        }
    except (FetchError, requests.RequestException):
        raise HTTPException(
            status_code=502, detail="Could not get the data from Open Targets."
        ) from None
    try:
        guesses = guessing.result(timeout=max(0.0, give_up_at - time.monotonic()))
    except Exception:  # slow, busy, unreachable or broken: no suggestions, no error
        guesses = []

    did_you_mean = []
    for guess in guesses:
        if matches and guess.disease.id == matches[0].id:
            continue  # already the first match: not repeated
        did_you_mean.append({"id": guess.disease.id, "name": guess.disease.name})
        also_called.setdefault(guess.disease.id, guess.also_called)
    return {
        "matches": [{"id": disease.id, "name": disease.name} for disease in matches],
        "did_you_mean": did_you_mean,
        # id -> Open Targets' own "also called" word, only where there is one.
        "also_called": {key: word for key, word in also_called.items() if word},
    }


@app.get("/api/clues")
def clues(disease_id: str) -> dict:
    found = _find(disease_id)
    disease = found.disease
    return {
        "disease": {"id": disease.id, "name": disease.name},
        "rule_text": RULE_TEXT,
        "new_clues": [_clue_json(clue, disease) for clue in found.new_clues],
        "being_studied": [_clue_json(clue, disease) for clue in found.being_studied],
        "left_out": {group: found.left_out[group] for group in LEFT_OUT_GROUPS},
    }


@app.get("/api/explain")
def explain_clue(disease_id: str, clue_id: str) -> dict:
    found = _find(disease_id)
    # Only a shown clue can be explained. Anything else is "not found".
    for clue in found.new_clues + found.being_studied:
        if _clue_id(clue) == clue_id:
            break
    else:
        raise HTTPException(status_code=404, detail="No clue with this id for this disease.")
    answer = explain.explain(clue, found.disease, found.known_names)
    return {
        "clue_id": clue_id,
        "text": answer.text,
        "source": answer.source,  # "gemini" or "template"
        "model": answer.model,  # None for the template
    }
