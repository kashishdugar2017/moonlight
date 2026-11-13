"""Translate: everyday words -> diseases Open Targets knows.

    did_you_mean(text)       -> list of Suggestion, most likely first
    suggest_names(text)      -> up to 3 disease names from Gemini (never shown)
    small_print(words, match) -> Open Targets' "also called" word, or None

Like asking a friend "what might they mean?" and then looking every answer
up on the map yourself. Gemini is the friend: it reads the words a person
typed ("flu", "Diabaties") and says up to three disease names. Open Targets
is the map: each name is searched there, and only what Open Targets sends
back, its own name and its own id, is ever handed on. A name the map does
not have is thrown away. Gemini's own text is never shown to anyone.

Kashish's decisions, 2026-11-13:
- Moonlight only offers "Did you mean". It never picks a disease.
- If the words (or Gemini's name) are letter for letter on Open Targets'
  own "also called" list for an entry, that word is shown beside the
  entry's name. The word shown is Open Targets' word.

Gemini gets GEMINI_SECONDS in total, the model list included. If it is
slow, busy, unreachable or says something that is not a list of names,
the answer is simply no suggestions. Nothing here raises for that.

Every Gemini call goes through _gemini_request. It hands the call to
explain.py's one Gemini function, so the rule about the key lives in a
single place and this module never touches it. The model name is picked
from the API's own model list. The fields of Gemini's answer were read
from the saved answers in fixtures/gemini/, not taken from memory.
"""

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import requests

from moonlight import explain, fetch
from moonlight.records import Disease

GEMINI_SECONDS = 3  # Gemini never gets longer than this, all its calls together
MAX_NAMES = 3  # the most disease names taken from Gemini
MAX_NAME_LETTERS = 80  # a longer "name" is not a disease name
REMEMBERED = 500  # how many different typed words are remembered

PROMPT = """A person typed these words into a disease search box:
{words}

Which disease names might they mean? Give at most 3, most likely first.
Use the plain medical name of each disease, with the spelling corrected.
If the words are not about a disease, give an empty list.
Answer with a JSON list of strings and nothing else.
"""


@dataclass(frozen=True)
class Suggestion:
    """One "Did you mean". Everything in it comes from Open Targets."""

    disease: Disease  # Open Targets' id and name
    also_called: Optional[str]  # Open Targets' own word for it, or None


class _NoAnswer(RuntimeError):
    """Gemini did not answer in time, or could not be asked."""


_models: List[str] = []  # the model list, asked for once
_names: Dict[str, List[str]] = {}  # typed words -> the names Gemini gave
_lock = threading.Lock()
# The names are looked up in Open Targets at the same time, one lane each.
_lanes = ThreadPoolExecutor(max_workers=2 * MAX_NAMES, thread_name_prefix="translate")


def forget_everything() -> None:
    """Forget the model list and the names Gemini gave."""
    with _lock:
        _models.clear()
        _names.clear()


def _gemini_request(method: str, path: str, body: Optional[dict],
                    timeout: float) -> Tuple[int, dict]:
    """The one place this module talks to Gemini. Tests replace this."""
    return explain._gemini_request(method, path, body, timeout)


def _plain(text: str) -> str:
    """Words in small letters with single spaces, for comparing."""
    return " ".join(text.split()).casefold()


def small_print(words: str, match: fetch.Match) -> Optional[str]:
    """Open Targets' "also called" word for this entry, if the words are it.

    The words must be on the entry's exact "also called" list, letter for
    letter (capitals and extra spaces do not count). What comes back is the
    word as Open Targets spells it. None if the words are not on the list,
    or are just the entry's own name.
    """
    wanted = _plain(words)
    if not wanted or wanted == _plain(match.disease.name):
        return None
    for term in match.also_called:
        if _plain(term) == wanted:
            return term
    return None


def _models_to_try(deadline: float) -> List[str]:
    """The models to ask, read from the API's own list. Asked for once."""
    with _lock:
        if _models:
            return list(_models)
    left = deadline - time.monotonic()
    if left <= 0:
        raise _NoAnswer("no time left to get the model list")
    status, listing = _gemini_request("GET", "models?pageSize=1000", None, left)
    if status != 200:
        raise _NoAnswer(f"the model list was refused ({status})")
    found = explain._model_order(listing)
    with _lock:
        if not _models:
            _models.extend(found)
    return found


def _ask_gemini(prompt: str, deadline: float) -> str:
    """Ask each model once, in order, until one answers or time is up."""
    body = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            # No silent "thinking" first. There are only three seconds.
            "thinkingConfig": {"thinkingBudget": 0},
            "responseMimeType": "application/json",
        },
    }
    for model in _models_to_try(deadline):
        left = deadline - time.monotonic()
        if left <= 0:
            break
        try:
            status, answer = _gemini_request(
                "POST", f"models/{model}:generateContent", body, left
            )
        except requests.RequestException:
            continue
        if status == 200:
            text = explain._text_of(answer)
            if text:
                return text
    raise _NoAnswer("no model answered in time")


def _names_in(text: str) -> Optional[List[str]]:
    """The disease names in Gemini's answer. None if it is not a list of names."""
    try:
        said = json.loads(text)
    except ValueError:
        return None
    if not isinstance(said, list) or not all(isinstance(item, str) for item in said):
        return None
    names: List[str] = []
    for item in said:
        name = " ".join(item.split())
        if not name or len(name) > MAX_NAME_LETTERS:
            continue
        if _plain(name) not in [_plain(other) for other in names]:
            names.append(name)
    return names[:MAX_NAMES]


def suggest_names(text: str) -> List[str]:
    """Up to MAX_NAMES disease names the words might mean, from Gemini.

    These are only search words for Open Targets. They are never shown.
    [] if Gemini cannot be asked or does not give a list of names.
    """
    key = _plain(text)
    if not key:
        return []
    with _lock:
        if key in _names:
            return list(_names[key])
    deadline = time.monotonic() + GEMINI_SECONDS
    try:
        # The words go in as quoted data, so they cannot pose as instructions.
        answer = _ask_gemini(PROMPT.format(words=json.dumps(text)), deadline)
    except (_NoAnswer, requests.RequestException):
        return []
    names = _names_in(answer)
    if names is None:
        return []
    with _lock:
        if len(_names) >= REMEMBERED:
            _names.clear()
        _names[key] = names
    return list(names)


def _confirm(name: str) -> Optional[Suggestion]:
    """Look one of Gemini's names up. -> Open Targets' best entry, or None."""
    try:
        matches = fetch.search_matches(name)
    except (fetch.FetchError, requests.RequestException):
        return None
    if not matches:
        return None  # Open Targets does not know it: thrown away
    best = matches[0]
    return Suggestion(disease=best.disease, also_called=small_print(name, best))


def did_you_mean(text: str) -> List[Suggestion]:
    """Diseases the words might mean, each one confirmed by Open Targets.

    One entry per name Gemini gave, in Gemini's order, each entry once.
    [] if Gemini gave nothing or Open Targets knows none of the names.
    """
    names = suggest_names(text)
    found: List[Suggestion] = []
    for suggestion in _lanes.map(_confirm, names):
        if suggestion and suggestion.disease.id not in [s.disease.id for s in found]:
            found.append(suggestion)
    return found
