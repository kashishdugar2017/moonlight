"""Explain: turn one ranked Clue into a plain explanation.

    facts_for(clue, disease)                     -> the only facts Gemini is given
    check_explanation(text, facts, known_names)  -> list of problems; empty means it passes
    explain(clue, disease, known_names)          -> Explanation(text, source, model, tries)

explain asks Gemini, checks the answer against Kashish's rules, and tries
again up to three times. If nothing passes, Gemini cannot be reached, or 25
seconds have gone by, it builds the explanation from a template in code,
using the same facts.

known_names is every medicine name Moonlight met in this run. An explanation
may only name its own medicine, so any other name from that collection fails.

The ENDING is glued on by this code every time. Gemini never writes it.

Every Gemini call goes through _gemini_request, so tests can swap that one
function. Field names ("models", "name", "supportedGenerationMethods",
"candidates", "content", "parts", "text", "modelVersion", "generationConfig",
"thinkingConfig", "thinkingBudget") were checked against live responses and
fixtures/gemini/, not taken from memory.
"""

import json
import os
import re
import time
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

import requests

from moonlight.filter import BEING_STUDIED, NEW_CLUE, group_of
from moonlight.rank import Clue

BASE_URL = "https://generativelanguage.googleapis.com/v1beta/"
FIRST_MODEL = "gemini-3.5-flash"
MAX_TRIES = 3  # answers checked before the template is used
TOTAL_SECONDS = 25  # one explain() never waits longer than this, all Gemini calls together
REQUEST_SECONDS = 25  # one HTTP call never waits longer than this
WAIT_SECONDS = 1  # the brief wait before trying another model

# Word for word from the ticket. Changing these needs Kashish's approval.
ENDING = (
    "But there is a catch. Nobody knows from our information if the "
    "disease needs this protein turned up or down. So this is a clue to "
    "read about. It is not a treatment. Do not try it."
)
ENDING_MANY = ENDING.replace("this protein", "these proteins")

# Kashish's own explanation. Gemini is shown it as the pattern to copy.
KASHISH_EXAMPLE = (
    "Sevoflurane is a medicine. Doctors already use it for something else. "
    "It grabs a protein called KCNK3. A protein is a tiny machine in your "
    "body. Sevoflurane turns KCNK3 up, like a volume knob. KCNK3 is linked to "
    "pulmonary arterial hypertension. That is high blood pressure in the "
    "arteries of the lungs. An artery is like a pipe for blood. The link "
    "score is 0.79. That is like 79 points out of 100. Sevoflurane has no "
    "link to this disease in the database. The database is a huge web with "
    "lots of information."
)

MAX_WORDS = 20
JARGON = ("inhibitor", "antagonist", "agonist", "blocker", "opener", "modulator")
GETTING_WORDS = (
    "buy", "shop", "pharmacy", "chemist", "order", "online", "price", "dose",
    "prescription",
)
PROMISE_WORDS = (
    "cure", "heal", "treat", "will work", "works for", "should take", "safe",
    "best", "recommended", "more likely",
)

NO_LINK = "no link to this disease in the database"
IN_TRIALS = "in trials for this disease"

DIRECTION_FACT = {
    "up": "up",
    "down": "down",
    "mixed": "both up and down",
    "unknown": "not known",
}


@dataclass(frozen=True)
class Explanation:
    text: str  # the explanation, always finishing with the ENDING
    source: str  # "gemini" or "template"
    model: Optional[str]  # the Gemini model that answered; None for the template
    tries: int  # how many Gemini answers were checked
    problems: Tuple[str, ...] = ()  # rules the text still breaks; () is normal


class GeminiUnavailable(RuntimeError):
    """No Gemini model gave an answer in the time allowed."""


# ---------------------------------------------------------------- the facts

def _display(name: str) -> str:
    """"DOXAPRAM HYDROCHLORIDE" -> "Doxapram Hydrochloride". Same name, calmer."""
    if name != name.upper():
        return name
    return " ".join(w.capitalize() if w.isalpha() else w for w in name.split())


def _phase_words(stage: str) -> str:
    """"PHASE_2_3" -> "Phase 2/3", "EARLY_PHASE_1" -> "Early Phase 1"."""
    early = stage.startswith("EARLY_")
    numbers = stage.replace("EARLY_", "").replace("PHASE_", "").replace("_", "/")
    return ("Early " if early else "") + "Phase " + numbers


def facts_for(clue: Clue, disease) -> dict:
    """The only facts Gemini is given, and the only facts the template uses.

    disease is anything with a .name and, if it has one, a .description.
    No IDs, no long protein names, no source links and no action words
    (the action words are the jargon Kashish banned; only up/down is kept).
    """
    medicine = clue.medicine
    group = group_of(medicine)
    if group not in (NEW_CLUE, BEING_STUDIED):
        raise ValueError(
            f"{medicine.name} is in group {group!r}. Only new clues and "
            "medicines being studied are explained."
        )

    proteins = []
    for path in clue.paths:
        score = f"{path.score:.2f}"
        points = round(float(score) * 100)
        proteins.append(
            {
                "name": path.target.symbol,
                "link_score": score,
                "link_score_as_points": f"{points} points out of 100",
                "medicine_turns_it": DIRECTION_FACT[path.direction],
            }
        )

    disease_facts = {"name": disease.name}
    # An empty description is left out, so nobody is asked to describe
    # the disease from nothing.
    description = (getattr(disease, "description", None) or "").strip()
    if description:
        disease_facts["description"] = description

    facts = {
        "medicine": {
            "name": _display(medicine.name),
            "forms": [_display(form.name) for form in medicine.forms],
            # group_of already made sure of this.
            "approved_for_another_disease": "yes",
        },
        "proteins": proteins,
        "disease": disease_facts,
        "link_to_disease": NO_LINK if group == NEW_CLUE else IN_TRIALS,
    }
    if group == BEING_STUDIED:
        facts["trial_phase"] = _phase_words(medicine.disease_stage)
    return facts


def ending_for(facts: dict) -> str:
    return ENDING_MANY if len(facts["proteins"]) > 1 else ENDING


# --------------------------------------------------------------- the checks

_TOKEN = re.compile(r"\d+(?:\.\d+)?|[^\W\d_][^\W_]*")
_SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+|\n+")


def _sentences(text: str) -> List[str]:
    return [s.strip() for s in _SENTENCE_BREAK.split(text.strip()) if s.strip()]


def _fact_values(thing) -> List[str]:
    """Every value in the facts, as text. Labels (the keys) do not count."""
    if isinstance(thing, dict):
        return [v for value in thing.values() for v in _fact_values(value)]
    if isinstance(thing, (list, tuple)):
        return [v for value in thing for v in _fact_values(value)]
    return [] if thing is None else [str(thing)]


def _banned_found(text: str, banned) -> List[str]:
    """Words in the text that START with a banned word ("treatment" for
    "treat", "doses" for "dose"), in the order they appear."""
    found = []
    for phrase in banned:
        pattern = r"\b" + r"\s+".join(re.escape(w) for w in phrase.split()) + r"\w*"
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            found.append((match.start(), " ".join(match.group().split())))
    return [word for _, word in sorted(found)]


def _own_names(facts: dict) -> List[str]:
    """Every name this clue's own medicine goes by."""
    return [facts["medicine"]["name"]] + list(facts["medicine"]["forms"])


def _name_pattern(name: str) -> str:
    """The whole name, in any letter case, not as part of a longer word."""
    return r"(?<!\w)" + r"\s+".join(re.escape(w) for w in name.split()) + r"(?!\w)"


def _other_medicines_found(text: str, facts: dict, known_names: Iterable[str]) -> List[str]:
    """Known medicine names in the text that are not this clue's own,
    as the text wrote them, in the order they appear."""
    own = {" ".join(name.lower().split()) for name in _own_names(facts)}
    # The clue's own names are covered up first, longest first, so a
    # stranger can never be found inside one of them.
    for name in sorted(own, key=len, reverse=True):
        if name:
            text = re.sub(
                _name_pattern(name), lambda m: " " * len(m.group()), text, flags=re.IGNORECASE
            )
    others = {" ".join(name.lower().split()) for name in known_names if name} - own - {""}
    found = []
    for name in others:
        for match in re.finditer(_name_pattern(name), text, flags=re.IGNORECASE):
            found.append((match.start(), " ".join(match.group().split())))
    names = []
    for _, name in sorted(found):
        if name not in names:
            names.append(name)
    return names


def check_explanation(text: str, facts: dict,
                      known_names: Optional[Iterable[str]] = None) -> List[str]:
    """Kashish's rules. Returns the problems; an empty list means pass.

    known_names: every medicine name Moonlight knows from this run. Rule 7
    fails the text if it holds any of them, in any letter case, that is not
    one of this clue's own forms. With no known_names, Rule 7 has nothing
    to look for.
    """
    problems = []
    sentences = _sentences(text)

    # Rule 1: no sentence longer than 20 words.
    for sentence in sentences:
        count = len(sentence.split())
        if count > MAX_WORDS:
            problems.append(
                f"Rule 1: a sentence has {count} words. The most allowed is "
                f'{MAX_WORDS}: "{sentence}"'
            )

    # Rule 2: "protein" must come with "tiny machine".
    lowered = text.lower()
    if "protein" in lowered and "tiny machine" not in lowered:
        problems.append('Rule 2: it says "protein" but never says "tiny machine".')

    # Rule 3: no jargon.
    jargon = _banned_found(text, JARGON)
    if jargon:
        problems.append("Rule 3: jargon is not allowed: " + ", ".join(jargon) + ".")

    # Rule 4: grounding. Numbers, and capital words inside a sentence, must
    # be in the facts.
    fact_tokens = {t.lower() for value in _fact_values(facts) for t in _TOKEN.findall(value)}
    strangers = []
    for sentence in sentences:
        for position, token in enumerate(_TOKEN.findall(sentence)):
            is_number = token[0].isdigit()
            starts_sentence = position == 0
            if is_number or (token[0].isupper() and not starts_sentence):
                if token.lower() not in fact_tokens and token not in strangers:
                    strangers.append(token)
    if strangers:
        problems.append("Rule 4: not in the facts: " + ", ".join(strangers) + ".")

    # Rule 5: nothing about getting medicines.
    getting = _banned_found(text, GETTING_WORDS)
    if getting:
        problems.append(
            "Rule 5: it must not talk about getting medicines: " + ", ".join(getting) + "."
        )

    # Rule 6: no promises. The ENDING is the code's own words and says
    # "treatment", so it is taken off before this rule looks.
    body = text.rstrip()
    for ending in (ENDING, ENDING_MANY):
        if body.endswith(ending):
            body = body[: -len(ending)]
            break
    promises = _banned_found(body, PROMISE_WORDS)
    if promises:
        problems.append(
            "Rule 6: it must not promise or hint it will help: " + ", ".join(promises) + "."
        )

    # Rule 7: no other medicine Moonlight knows may be named.
    if known_names:
        others = _other_medicines_found(text, facts, known_names)
        if others:
            problems.append(
                "Rule 7: it must not name any other medicine: " + ", ".join(others) + "."
            )

    return problems


def _missing_for_being_studied(text: str, facts: dict) -> List[str]:
    """A being studied clue must say it is being tested, and the phase."""
    phase = facts.get("trial_phase")
    if not phase:
        return []
    lowered = text.lower()
    if "testing" in lowered and phase.lower() in lowered:
        return []
    return [
        "Being studied: it must say doctors are already testing it for this "
        f"disease, and give the phase, {phase}."
    ]


# ------------------------------------------------------------- the template

def _name_sentences(first: str, later: str, names: List[str]) -> List[str]:
    """List names in sentences that each stay inside the word limit."""
    groups, group, used = [], [], 0
    for name in names:
        words = len(name.split())
        if group and used + words > 12:
            groups.append(group)
            group, used = [], 0
        group.append(name)
        used += words
    groups.append(group)

    sentences = []
    for number, group in enumerate(groups):
        listed = group[0] if len(group) == 1 else ", ".join(group[:-1]) + " and " + group[-1]
        sentences.append(f"{later if number else first} {listed}.")
    return sentences


def template_text(facts: dict) -> str:
    """The explanation built by plain code from the facts. No ENDING yet."""
    name = facts["medicine"]["name"]
    disease = facts["disease"]["name"]
    proteins = facts["proteins"]
    out = [f"{name} is a medicine.", "Doctors already use it for something else."]

    forms = facts["medicine"]["forms"]
    if forms != [name]:
        out.append("It comes in more than one form.")
        out += _name_sentences("The forms are called", "More forms are called", forms)

    if len(proteins) == 1:
        out.append(f"It grabs a protein called {proteins[0]['name']}.")
    else:
        out.append(f"{name} grabs more than one protein.")
    out.append("A protein is a tiny machine in your body.")

    for number, protein in enumerate(proteins):
        symbol = protein["name"]
        if len(proteins) > 1:
            out.append(f"{'Another' if number else 'One'} protein is called {symbol}.")
        turns = protein["medicine_turns_it"]
        if turns in ("up", "down"):
            out.append(f"{name} turns {symbol} {turns}, like a volume knob.")
        elif turns == DIRECTION_FACT["mixed"]:
            out.append(f"Our information says {name} can turn {symbol} both up and down.")
        else:
            out.append(f"Our information does not say if {name} turns {symbol} up or down.")
        out.append(f"{symbol} is linked to {disease}.")
        out.append(f"The link score is {protein['link_score']}.")
        out.append(f"That is like {protein['link_score_as_points']}.")

    if facts["link_to_disease"] == IN_TRIALS:
        out.append(f"Doctors are already testing {name} for this disease.")
        out.append(f"The testing is at {facts['trial_phase']}.")
        out.append("A phase is one step of testing.")
        out.append("Nobody knows yet what the testing will show.")
    else:
        out.append(f"{name} has no link to this disease in the database.")
    out.append("The database is a huge web with lots of information.")
    return " ".join(out)


# ------------------------------------------------------------------- Gemini

def _headers() -> Dict[str, str]:
    """The key header, only if GEMINI_API_KEY is set. Never printed or logged."""
    key = os.environ.get("GEMINI_API_KEY")
    return {"x-goog-api-key": key} if key else {}


def _gemini_request(method: str, path: str, body: Optional[dict] = None,
                    timeout: float = REQUEST_SECONDS) -> Tuple[int, dict]:
    """The one place Moonlight talks to Gemini. Tests replace this.

    Returns the HTTP status and the JSON answer ({} if it was not JSON).
    """
    response = requests.request(
        method, BASE_URL + path, headers=_headers(), json=body, timeout=timeout
    )
    try:
        data = response.json()
    except ValueError:
        data = {}
    return response.status_code, data if isinstance(data, dict) else {}


_MODEL_NAME = re.compile(r"^gemini-(\d+(?:\.\d+)?)-flash(-lite)?$")
_models: List[str] = []  # the model list, asked for once
_made: Dict[str, Explanation] = {}  # explanations already made


def forget_everything() -> None:
    """Forget the model list and the explanations already made."""
    _models.clear()
    _made.clear()


def _model_order(listing: dict) -> List[str]:
    """Which models to try, in order, picked from the API's own list.

    Only plain text "flash" models that can generateContent. FIRST_MODEL
    goes first if it is on the list, then the newest, with "lite" ones last.
    """
    found = []
    for model in listing.get("models", []):
        name = model.get("name", "").replace("models/", "", 1)
        match = _MODEL_NAME.match(name)
        if match and "generateContent" in model.get("supportedGenerationMethods", []):
            found.append((name != FIRST_MODEL, bool(match.group(2)), -float(match.group(1)), name))
    return [name for *_, name in sorted(found)]


def _models_to_try(deadline: float) -> List[str]:
    if not _models:
        left = deadline - time.monotonic()
        if left <= 0:
            raise GeminiUnavailable("no time left to get the model list")
        try:
            status, listing = _gemini_request(
                "GET", "models?pageSize=1000", timeout=min(REQUEST_SECONDS, left)
            )
        except requests.RequestException as error:
            raise GeminiUnavailable("could not get the model list") from error
        if status != 200:
            raise GeminiUnavailable(f"the model list was refused ({status})")
        _models.extend(_model_order(listing))
    return list(_models)


def _text_of(answer: dict) -> str:
    """The words in a generateContent answer. "" if there are none."""
    candidates = answer.get("candidates") or [{}]
    parts = (candidates[0].get("content") or {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
    return " ".join(text.split())


def _ask_gemini(prompt: str, deadline: float) -> Tuple[str, str]:
    """Ask each model once, in order, until one answers. -> (text, model)"""
    body = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        # No silent "thinking" first: it made answers take about 25 seconds,
        # and the checks below do the checking anyway. A model that refuses
        # this setting is skipped like any other refused model.
        "generationConfig": {"thinkingConfig": {"thinkingBudget": 0}},
    }
    for number, model in enumerate(_models_to_try(deadline)):
        if number:
            # Refused or busy: wait briefly, try another. The wait is never
            # longer than the time that is left.
            left = deadline - time.monotonic()
            if left <= 0:
                break
            time.sleep(min(WAIT_SECONDS, left))
        left = deadline - time.monotonic()
        if left <= 0:
            break
        try:
            status, answer = _gemini_request(
                "POST", f"models/{model}:generateContent", body,
                timeout=min(REQUEST_SECONDS, left),
            )
        except requests.RequestException:
            continue
        if status == 200:
            text = _text_of(answer)
            if text:
                # The answer names the model that really wrote it, which can
                # be a newer one than the one that was asked.
                return text, answer.get("modelVersion") or model
    raise GeminiUnavailable("no model answered in time")


def _prompt(facts: dict, problems: List[str]) -> str:
    lines = [
        "You explain one drug-repurposing clue for a learning website.",
        "Write for a five-year-old who can read.",
        "",
        "RULES",
        "- Use ONLY the facts in FACTS. Add nothing else: no other medicine, "
        "disease, body part name, number or name.",
        "- Every number you write must be written in FACTS exactly that way.",
        "- A word with a capital letter may only be the first word of a "
        "sentence or a name copied from FACTS.",
        f"- No sentence longer than {MAX_WORDS} words. Shorter is better.",
        "- Explain every big word in a short sentence of its own.",
        '- If you write "protein", also say a protein is a "tiny machine".',
        "- Say up or down like a volume knob. Never use these words: "
        + ", ".join(JARGON) + ".",
        "- Never say where or how to get a medicine. Never use these words, "
        "or words that start with them: " + ", ".join(GETTING_WORDS) + ".",
        "- Never say or hint that the medicine will help. Never use these "
        "words, or words that start with them: " + ", ".join(PROMISE_WORDS) + ".",
        "- Do not write a warning or an ending. The website adds its own.",
        "- Plain sentences in one paragraph. No lists, no headings, no stars.",
    ]
    if "description" in facts["disease"]:
        lines.append(
            "- Say what the disease is in one or two short sentences, using "
            "only the description in FACTS. Use small everyday words. Do not "
            "copy its long or hard words, and do not say anything scary."
        )
    else:
        lines.append("- FACTS has no description of the disease, so do not describe it.")
    if facts["link_to_disease"] == IN_TRIALS:
        lines.append(
            "- This medicine is being studied. Say that doctors are already "
            f"testing it for this disease, and that the testing is at "
            f"{facts['trial_phase']}. Never say this makes it more likely to help."
        )
    lines += [
        "",
        "PATTERN (written by a child for a different clue; copy its style, "
        "not its facts)",
        KASHISH_EXAMPLE,
        "",
        "FACTS",
        json.dumps(facts, indent=2),
    ]
    if problems:
        lines += ["", "Your last answer broke these rules. Write it again and fix them:"]
        lines += ["- " + problem for problem in problems]
    return "\n".join(lines)


# ------------------------------------------------------------------ explain

def explain(clue: Clue, disease,
            known_names: Optional[Iterable[str]] = None) -> Explanation:
    """One clue -> a checked explanation, from Gemini or from the template.

    known_names: every medicine name Moonlight knows from this run. They are
    only used by the check. They are never shown to Gemini.
    """
    facts = facts_for(clue, disease)
    known = sorted({name.lower() for name in known_names or () if name})
    key = json.dumps([facts, known], sort_keys=True)
    if key in _made:
        return _made[key]  # the same clue is not asked twice

    ending = ending_for(facts)
    deadline = time.monotonic() + TOTAL_SECONDS
    tries = 0
    problems: List[str] = []
    try:
        while tries < MAX_TRIES:
            answer, model = _ask_gemini(_prompt(facts, problems), deadline)
            tries += 1
            text = answer + " " + ending
            problems = check_explanation(text, facts, known) + _missing_for_being_studied(text, facts)
            if not problems:
                _made[key] = Explanation(text=text, source="gemini", model=model, tries=tries)
                return _made[key]
    except GeminiUnavailable:
        pass

    # Template answers are not remembered, so Gemini gets another go later.
    text = template_text(facts) + " " + ending
    return Explanation(
        text=text, source="template", model=None, tries=tries,
        problems=tuple(check_explanation(text, facts, known)),
    )
