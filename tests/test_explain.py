"""Ticket 3.2-3.4. Kashish's example and her nine MORE EXAMPLES, one test each.

Nothing here touches the network. Clues are built from the saved Open
Targets files in fixtures/ (fetch._post_json is swapped for one that reads
them). Gemini is never called: explain._gemini_request is swapped for a
fake, and real HTTP is made an error.
"""

import json
import pathlib
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from moonlight import explain, fetch
from moonlight.filter import BEING_STUDIED, NEW_CLUE, sort_paths
from moonlight.rank import Clue, rank_clues
from moonlight.records import Disease, Medicine, MedicineForm, Path, Target

FIXTURES = pathlib.Path(__file__).resolve().parent.parent / "fixtures"
GOLDEN = FIXTURES / "MONDO_0015924"
SAVED_GEMINI_ANSWER = FIXTURES / "gemini" / "sevoflurane_generate.response.json"

PAH = Disease(id="MONDO_0015924", name="pulmonary arterial hypertension")

# Kashish's own explanation, word for word from the ticket.
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

# The ENDING, word for word from the ticket.
ENDING = (
    "But there is a catch. Nobody knows from our information if the "
    "disease needs this protein turned up or down. So this is a clue to "
    "read about. It is not a treatment. Do not try it."
)
ENDING_MANY = ENDING.replace("this protein", "these proteins")


def load(file):
    return json.loads(file.read_text(encoding="utf-8"))


def fake_post_json(body):
    """Stands in for fetch._post_json: picks the saved response for a request."""
    variables = body["variables"]
    if "targetId" in variables:
        target_id = variables["targetId"]
        matches = list((GOLDEN / "target_drugs").glob(f"*_{target_id}.response.json"))
        assert len(matches) == 1, f"no saved file for target {target_id}"
        return load(matches[0])
    assert variables["diseaseId"] == PAH.id
    return load(GOLDEN / "associated_targets.response.json")


@pytest.fixture(autouse=True)
def no_network_and_fresh_memory():
    """Real HTTP is an error, waiting takes no time, nothing is remembered."""
    explain.forget_everything()
    with patch("requests.request", side_effect=AssertionError("network used")), \
            patch("requests.post", side_effect=AssertionError("network used")), \
            patch("requests.get", side_effect=AssertionError("network used")), \
            patch("requests.sessions.Session.request",
                  side_effect=AssertionError("network used")), \
            patch("moonlight.explain.time.sleep"):
        yield
    explain.forget_everything()


@pytest.fixture(scope="module")
def clues():
    """Every shown clue for PAH, by medicine name in capitals."""
    wanted = {"KCNK3", "PDE5A"}
    with patch("moonlight.fetch._post_json", side_effect=fake_post_json):
        targets = [t for t in fetch.fetch_targets(PAH) if t.symbol in wanted]
        paths = [p for t in targets for p in fetch.fetch_paths(PAH, t)]
    tray = sort_paths(paths)
    found = rank_clues(tray[NEW_CLUE]) + rank_clues(tray[BEING_STUDIED])
    return {clue.medicine.name.upper(): clue for clue in found}


@pytest.fixture
def disease():
    """PAH with the description from the saved disease record.

    records.Disease has no description, so this stands in for it.
    """
    record = load(GOLDEN / "disease.response.json")["data"]["disease"]
    return SimpleNamespace(
        id=record["id"], name=record["name"], description=record["description"]
    )


@pytest.fixture
def sevoflurane(clues):
    return clues["SEVOFLURANE"]


@pytest.fixture
def facts(sevoflurane, disease):
    return explain.facts_for(sevoflurane, disease)


def rules_broken(problems):
    """["Rule 4: ...", "Rule 1: ..."] -> {4, 1}"""
    assert all(p.startswith("Rule ") for p in problems), problems
    return {int(p.split(":")[0].replace("Rule ", "")) for p in problems}


# ---- a fake Gemini ----

MODEL_LIST = {  # field names read from the live model list
    "models": [
        {"name": "models/gemini-2.5-flash",
         "supportedGenerationMethods": ["generateContent", "countTokens"]},
        {"name": "models/gemini-3.5-flash-tts",
         "supportedGenerationMethods": ["generateContent"]},
        {"name": "models/gemini-3.5-flash",
         "supportedGenerationMethods": ["generateContent", "countTokens"]},
        {"name": "models/gemini-embedding-2",
         "supportedGenerationMethods": ["embedContent"]},
        {"name": "models/gemini-3.8-flash",
         "supportedGenerationMethods": ["generateContent", "countTokens"]},
    ]
}


def answer(text):
    """A generateContent answer in the shape of the saved one."""
    return {"candidates": [{"content": {"parts": [{"text": text}], "role": "model"}}]}


class FakeGemini:
    """Stands in for explain._gemini_request. Remembers what it was asked."""

    def __init__(self, replies):
        # replies: one (status, data) per generate call; the last one repeats.
        self.replies = list(replies)
        self.asked = []  # model name for each generate call
        self.prompts = []
        self.list_calls = 0

    def __call__(self, method, path, body=None, timeout=None):
        if method == "GET":
            assert path.startswith("models")
            self.list_calls += 1
            return 200, MODEL_LIST
        assert method == "POST" and path.endswith(":generateContent")
        self.asked.append(path.split(":")[0].replace("models/", ""))
        self.prompts.append(json.dumps(body))
        reply = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        if isinstance(reply, Exception):
            raise reply
        return reply


def use(fake):
    return patch("moonlight.explain._gemini_request", side_effect=fake)


BUSY = (503, {"error": {"code": 503, "status": "UNAVAILABLE"}})


# ---- the facts ----

def test_facts_are_exactly_what_the_ticket_lists(facts, disease):
    assert facts == {
        "medicine": {
            "name": "Sevoflurane",
            "forms": ["Sevoflurane"],
            "approved_for_another_disease": "yes",
        },
        "proteins": [
            {
                "name": "KCNK3",
                "link_score": "0.79",
                "link_score_as_points": "79 points out of 100",
                "medicine_turns_it": "up",
            }
        ],
        "disease": {
            "name": "pulmonary arterial hypertension",
            "description": disease.description,
        },
        "link_to_disease": "no link to this disease in the database",
    }


def test_facts_never_hold_the_jargon_words(clues, disease):
    for clue in clues.values():
        made = dict(explain.facts_for(clue, disease), disease=None)
        text = json.dumps(made).lower()
        for word in ("inhibitor", "antagonist", "agonist", "blocker", "opener", "modulator"):
            assert word not in text


def test_facts_for_a_being_studied_clue_give_the_phase(clues, disease):
    facts = explain.facts_for(clues["VARDENAFIL"], disease)
    assert facts["link_to_disease"] == "in trials for this disease"
    assert facts["trial_phase"] == "Phase 3"
    assert facts["medicine"]["forms"] == ["Vardenafil", "Vardenafil Hydrochloride"]
    assert facts["proteins"][0]["medicine_turns_it"] == "down"
    assert explain.facts_for(clues["UDENAFIL"], disease)["trial_phase"] == "Phase 2/3"


def test_facts_work_when_the_disease_has_no_description(sevoflurane):
    facts = explain.facts_for(sevoflurane, PAH)
    assert facts["disease"] == {"name": "pulmonary arterial hypertension"}


def test_a_medicine_that_is_not_a_clue_is_refused(disease):
    form = MedicineForm(id="X1", name="NOTAPPROVEDINE", best_stage="PHASE_2")
    path = Path(
        medicine=Medicine(name="NOTAPPROVEDINE", forms=(form,)),
        target=Target(id="ENSG_KCNK3", symbol="KCNK3", name="KCNK3", score=0.79),
        disease=PAH, action_types=("OPENER",), score=0.79, sources=(),
    )
    with pytest.raises(ValueError):
        explain.facts_for(Clue(paths=(path,)), disease)


# ---- EXAMPLE: Kashish's own explanation passes every check ----

def test_kashishs_example_passes_every_check(facts):
    assert explain.check_explanation(KASHISH_EXAMPLE, facts) == []


def test_kashishs_example_is_the_pattern_shown_to_gemini(sevoflurane, disease):
    assert explain.KASHISH_EXAMPLE == KASHISH_EXAMPLE
    gemini = FakeGemini([(200, answer(KASHISH_EXAMPLE))])
    with use(gemini):
        explain.explain(sevoflurane, disease)
    assert json.dumps(KASHISH_EXAMPLE)[1:-1] in gemini.prompts[0]


# ---- MORE EXAMPLES 1 to 6: the checks ----

def test_1_dolo_fails_grounding(facts):
    text = "Sevoflurane is a medicine just like Dolo or paracetamol."
    problems = explain.check_explanation(text, facts)
    assert rules_broken(problems) == {4}
    assert "Dolo" in problems[0]


def test_2_a_sentence_of_25_words_fails(facts):
    sentence = " ".join(["the"] * 24) + " end."
    assert len(sentence.split()) == 25
    assert rules_broken(explain.check_explanation(sentence, facts)) == {1}


def test_2_a_sentence_of_20_words_is_allowed(facts):
    sentence = " ".join(["the"] * 19) + " end."
    assert explain.check_explanation(sentence, facts) == []


def test_3_protein_without_tiny_machine_fails(facts):
    problems = explain.check_explanation("It grabs a protein called KCNK3.", facts)
    assert rules_broken(problems) == {2}


@pytest.mark.parametrize(
    "word", ["inhibitor", "antagonist", "agonist", "blocker", "opener", "modulator"]
)
def test_jargon_fails(facts, word):
    problems = explain.check_explanation(f"This medicine is a strong {word}.", facts)
    assert rules_broken(problems) == {3}


def test_4_buy_it_at_a_pharmacy_fails(facts):
    problems = explain.check_explanation("You can buy it at a pharmacy.", facts)
    assert rules_broken(problems) == {5}
    assert "buy" in problems[0] and "pharmacy" in problems[0]


@pytest.mark.parametrize(
    "word",
    ["buy", "shop", "pharmacy", "chemist", "order", "online", "price", "dose",
     "prescription"],
)
def test_every_getting_word_fails(facts, word):
    problems = explain.check_explanation(f"There is a {word} for it.", facts)
    assert rules_broken(problems) == {5}


def test_5_this_will_work_fails(facts):
    problems = explain.check_explanation("This will work for the disease.", facts)
    assert rules_broken(problems) == {6}


@pytest.mark.parametrize(
    "sentence",
    [
        "It can cure the disease.",
        "It helps the lungs heal.",
        "It could treat the disease.",
        "It will work.",
        "It works for this disease.",
        "You should take it.",
        "It is safe.",
        "It is the best one.",
        "It is recommended.",
        "It is more likely to help.",
        "It is a treatment.",
    ],
)
def test_every_promise_fails(facts, sentence):
    assert rules_broken(explain.check_explanation(sentence, facts)) == {6}


def test_6_wrong_score_fails(facts):
    problems = explain.check_explanation("The link score is 0.95.", facts)
    assert rules_broken(problems) == {4}
    assert "0.95" in problems[0]
    assert explain.check_explanation("The link score is 0.79.", facts) == []


def test_capital_word_from_the_facts_is_allowed_inside_a_sentence(facts):
    assert explain.check_explanation("Then Sevoflurane turns KCNK3 up.", facts) == []


def test_the_ending_is_not_checked_against_rule_6(facts):
    # "treatment" is only allowed inside the ENDING itself.
    text = "A protein is a tiny machine. " + ENDING
    assert explain.check_explanation(text, facts) == []
    sneaky = "A protein is a tiny machine. It is a treatment. " + ENDING
    assert rules_broken(explain.check_explanation(sneaky, facts)) == {6}


# ---- MORE EXAMPLE 7: the ENDING ----

def test_7_the_ending_is_word_for_word():
    assert explain.ENDING == ENDING
    assert explain.ENDING_MANY == ENDING_MANY


def test_7_every_result_ends_with_the_ending(clues, disease):
    good = FakeGemini([(200, answer(KASHISH_EXAMPLE))])
    with use(good):
        from_gemini = explain.explain(clues["SEVOFLURANE"], disease)
    assert from_gemini.source == "gemini"
    assert from_gemini.text == KASHISH_EXAMPLE + " " + ENDING

    explain.forget_everything()
    with use(FakeGemini([BUSY])):
        for clue in clues.values():
            result = explain.explain(clue, disease)
            assert result.source == "template"
            assert result.text.endswith(" " + ENDING)


def test_7_more_than_one_protein_says_these_proteins(clues, disease):
    one = clues["SEVOFLURANE"].paths[0]
    other = Path(
        medicine=one.medicine,
        target=Target(id="ENSG_EDNRA", symbol="EDNRA", name="EDNRA", score=0.62),
        disease=PAH, action_types=("ANTAGONIST",), score=0.62, sources=(),
    )
    clue = Clue(paths=(one, other))
    with use(FakeGemini([BUSY])):
        result = explain.explain(clue, disease)
    assert result.text.endswith(" " + ENDING_MANY)
    assert "KCNK3" in result.text and "EDNRA" in result.text
    assert "0.79" in result.text and "0.62" in result.text
    assert result.problems == ()


# ---- MORE EXAMPLE 8: Gemini busy every time ----

def test_8_gemini_busy_every_time_gives_the_template(sevoflurane, disease, facts):
    gemini = FakeGemini([BUSY])
    with use(gemini):
        result = explain.explain(sevoflurane, disease)
    assert result.source == "template"
    assert result.model is None
    assert result.text.endswith(ENDING)
    assert explain.check_explanation(result.text, facts) == []
    # It tried gemini-3.5-flash first, then others from the list, each once.
    assert gemini.asked == ["gemini-3.5-flash", "gemini-3.8-flash", "gemini-2.5-flash"]


def test_8_the_template_says_the_same_facts(sevoflurane, disease):
    with use(FakeGemini([BUSY])):
        text = explain.explain(sevoflurane, disease).text
    for piece in (
        "Sevoflurane is a medicine.",
        "Doctors already use it for something else.",
        "A protein is a tiny machine in your body.",
        "Sevoflurane turns KCNK3 up, like a volume knob.",
        "KCNK3 is linked to pulmonary arterial hypertension.",
        "The link score is 0.79.",
        "That is like 79 points out of 100.",
        "Sevoflurane has no link to this disease in the database.",
    ):
        assert piece in text


def test_8_every_clue_gets_a_template_that_passes_every_check(clues, disease):
    with use(FakeGemini([BUSY])):
        for clue in clues.values():
            result = explain.explain(clue, disease)
            facts = explain.facts_for(clue, disease)
            assert explain.check_explanation(result.text, facts) == [], clue.medicine.name
            assert result.problems == ()


def test_8_gemini_cannot_be_reached_gives_the_template(sevoflurane, disease):
    import requests

    def unreachable(method, path, body=None, timeout=None):
        raise requests.ConnectionError("no network")

    with patch("moonlight.explain._gemini_request", side_effect=unreachable):
        result = explain.explain(sevoflurane, disease)
    assert result.source == "template"


def test_8_gives_up_after_a_short_total_time(sevoflurane, disease):
    gemini = FakeGemini([BUSY])
    clock = iter(range(0, 100000, 25))  # every look at the clock is 25 s later
    with use(gemini), patch("moonlight.explain.time.monotonic", side_effect=lambda: next(clock)):
        result = explain.explain(sevoflurane, disease)
    assert result.source == "template"
    assert len(gemini.asked) < 3


# ---- MORE EXAMPLE 9: being studied ----

def test_9_being_studied_template_gives_the_phase(clues, disease):
    with use(FakeGemini([BUSY])):
        result = explain.explain(clues["VARDENAFIL"], disease)
    text = result.text
    assert "Doctors are already testing Vardenafil for this disease." in text
    assert "Phase 3" in text
    assert "more likely" not in text.lower()
    assert "has no link to this disease" not in text
    facts = explain.facts_for(clues["VARDENAFIL"], disease)
    assert explain.check_explanation(text, facts) == []


def test_9_being_studied_gemini_answer_must_give_the_phase(clues, disease):
    without_phase = (
        "Vardenafil is a medicine. It grabs a protein called PDE5A. "
        "A protein is a tiny machine in your body."
    )
    with_phase = without_phase + (
        " Doctors are already testing Vardenafil for this disease."
        " The testing is at Phase 3."
    )
    gemini = FakeGemini([(200, answer(without_phase)), (200, answer(with_phase))])
    with use(gemini):
        result = explain.explain(clues["VARDENAFIL"], disease)
    assert result.source == "gemini"
    assert result.tries == 2
    assert "Phase 3" in result.text


def test_9_more_likely_is_never_let_through(clues, disease):
    hinting = (
        "Vardenafil is a medicine. A protein is a tiny machine. Doctors are "
        "already testing it for this disease at Phase 3. So it is more likely "
        "to help."
    )
    with use(FakeGemini([(200, answer(hinting))])):
        result = explain.explain(clues["VARDENAFIL"], disease)
    assert result.source == "template"
    assert "more likely" not in result.text.lower()


# ---- explain: asking, checking, trying again, remembering ----

def test_explain_with_the_saved_gemini_answer(sevoflurane, disease, facts):
    saved = load(SAVED_GEMINI_ANSWER)
    gemini = FakeGemini([(200, saved)])
    with use(gemini):
        result = explain.explain(sevoflurane, disease)
    assert result.source == "gemini"
    # gemini-3.5-flash was asked. The saved answer says which model really
    # wrote it ("modelVersion"), and that is the one reported.
    assert saved["modelVersion"] == "gemini-3.6-flash"
    assert result.model == "gemini-3.6-flash"
    assert result.tries == 1
    assert result.text.endswith(" " + ENDING)
    assert explain.check_explanation(result.text, facts) == []
    assert gemini.asked == ["gemini-3.5-flash"]


def test_gemini_is_given_the_facts_and_nothing_else_about_the_clue(sevoflurane, disease, facts):
    gemini = FakeGemini([(200, answer(KASHISH_EXAMPLE))])
    with use(gemini):
        explain.explain(sevoflurane, disease)
    prompt = gemini.prompts[0]
    assert json.dumps(json.dumps(facts, indent=2))[1:-1] in prompt
    path = sevoflurane.paths[0]
    assert path.target.id not in prompt  # no IDs
    assert path.target.name not in prompt  # no long protein name
    for source in path.sources[:5]:
        assert source not in prompt


def test_a_bad_answer_is_asked_again_up_to_three_times(sevoflurane, disease):
    bad = "You can buy it at a pharmacy."
    gemini = FakeGemini([(200, answer(bad)), (200, answer(bad)), (200, answer(KASHISH_EXAMPLE))])
    with use(gemini):
        result = explain.explain(sevoflurane, disease)
    assert result.source == "gemini"
    assert result.tries == 3
    assert len(gemini.asked) == 3
    assert "Rule 5" in gemini.prompts[1]  # it is told what was wrong


def test_three_bad_answers_give_the_template(sevoflurane, disease, facts):
    gemini = FakeGemini([(200, answer("This will work for the disease."))])
    with use(gemini):
        result = explain.explain(sevoflurane, disease)
    assert len(gemini.asked) == 3
    assert result.source == "template"
    assert result.model is None
    assert result.tries == 3
    assert "will work" not in result.text
    assert explain.check_explanation(result.text, facts) == []


def test_a_refused_model_is_skipped_for_the_next_one(sevoflurane, disease):
    refused = (404, {"error": {"code": 404, "status": "NOT_FOUND"}})
    gemini = FakeGemini([refused, (200, answer(KASHISH_EXAMPLE))])
    with use(gemini), patch("moonlight.explain.time.sleep") as sleep:
        result = explain.explain(sevoflurane, disease)
    assert gemini.asked == ["gemini-3.5-flash", "gemini-3.8-flash"]
    assert result.source == "gemini"
    assert result.model == "gemini-3.8-flash"
    assert sleep.call_count == 1  # it waited briefly before the next model


def test_the_same_clue_is_not_asked_twice(sevoflurane, disease):
    gemini = FakeGemini([(200, answer(KASHISH_EXAMPLE))])
    with use(gemini):
        first = explain.explain(sevoflurane, disease)
        second = explain.explain(sevoflurane, disease)
    assert first == second
    assert len(gemini.asked) == 1
    assert gemini.list_calls == 1


def test_no_key_variable_means_no_key_header(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert explain._headers() == {}
    monkeypatch.setenv("GEMINI_API_KEY", "made-up-for-this-test")
    assert explain._headers() == {"x-goog-api-key": "made-up-for-this-test"}
