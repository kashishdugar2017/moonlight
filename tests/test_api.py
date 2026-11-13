"""Ticket 5.1. The small API and Sidha's designed page, medicine first.

Each EXAMPLE in the ticket is a test here. Saved files only, no network:
fetch._post_json and explain._gemini_request are swapped for fakes, and any
real HTTP call is an error.
"""

import json
import pathlib
import re
from unittest.mock import patch

import pytest
import requests
from fastapi.testclient import TestClient

from moonlight import api, engine, explain, fetch
from moonlight.rank import RULE_TEXT
from moonlight.records import Disease

ROOT = pathlib.Path(__file__).resolve().parent.parent
GOLDEN = ROOT / "fixtures" / "MONDO_0015924"
PAH_ID = "MONDO_0015924"
PAH = Disease(id=PAH_ID, name="pulmonary arterial hypertension")

SAFETY_LINE = (
    "For learning and research exploration, not medical advice. "
    "Never start, stop or change any medicine without a doctor."
)
ENDING = (
    "But there is a catch. Nobody knows from our information if the "
    "disease needs this protein turned up or down. So this is a clue to "
    "read about. It is not a treatment. Do not try it."
)
ENDING_MANY = ENDING.replace("this protein", "these proteins")

FIVE = ("BMPR2", "KCNK3", "ACVRL1", "EDNRA", "PDE5A")
GUCY1 = ("GUCY1A1", "GUCY1B1", "GUCY1A2")
NEW_ORDER = [
    "Dibotermin Alfa", "Eptotermin Alfa", "Sevoflurane", "Desflurane",
    "Isoflurane", "Doxapram", "Enflurane", "Halothane", "Atrasentan",
    "Sparsentan", "Aprocitentan", "Clazosentan", "Pentoxifylline",
    "Dipyridamole", "Avanafil", "Ibudilast",
]
SAVED_IDS = {
    path.name.split(".")[0].split("_")[-1]
    for path in (GOLDEN / "target_drugs").glob("*.response.json")
}


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def fake_post_json(body):
    """Stands in for fetch._post_json: picks the saved response for a request."""
    assert set(body) == {"query", "variables"}
    query, variables = body["query"], body["variables"]
    if "text" in variables:
        saved = load(GOLDEN / "disease_search.request.json")["variables"]
        assert variables["text"] == saved["text"], "no saved search for this text"
        return load(GOLDEN / "disease_search.response.json")
    if "targetId" in variables:
        matches = list(
            (GOLDEN / "target_drugs").glob(f"*_{variables['targetId']}.response.json")
        )
        assert len(matches) == 1, f"no saved file for target {variables['targetId']}"
        return load(matches[0])
    if variables["diseaseId"] != PAH_ID:
        return {"data": {"disease": None}}  # a disease Open Targets does not know
    if "associatedTargets" in query:
        return load(GOLDEN / "associated_targets.response.json")
    return load(GOLDEN / "disease_description.response.json")


@pytest.fixture(autouse=True)
def offline():
    """Saved files instead of Open Targets. Real HTTP is an error."""
    explain.forget_everything()
    with patch("moonlight.fetch._post_json", side_effect=fake_post_json), \
            patch("requests.request", side_effect=AssertionError("network used")), \
            patch("requests.post", side_effect=AssertionError("network used")), \
            patch("requests.get", side_effect=AssertionError("network used")), \
            patch("requests.sessions.Session.request",
                  side_effect=AssertionError("network used")), \
            patch("moonlight.explain.time.sleep"):
        yield
    explain.forget_everything()


@pytest.fixture
def client():
    return TestClient(api.app)


def targets_named(*symbols):
    by_symbol = {t.symbol: t for t in fetch.fetch_targets(PAH)}
    return [by_symbol[symbol] for symbol in symbols]


def with_targets(*symbols):
    """The API looks at only these proteins, as in Kashish's answer key."""
    return patch("moonlight.api.fetch_targets", return_value=targets_named(*symbols))


def with_saved_targets():
    """The API looks at every protein that has a saved file."""
    saved = [t for t in fetch.fetch_targets(PAH) if t.id in SAVED_IDS]
    return patch("moonlight.api.fetch_targets", return_value=saved)


def gemini_unreachable(method, path, body=None, timeout=None):
    raise requests.ConnectionError("no network")


def gemini_says(text, model="gemini-3.5-flash"):
    """Stands in for explain._gemini_request with one good answer."""
    def fake(method, path, body=None, timeout=None):
        if method == "GET":
            return 200, {"models": [{
                "name": f"models/{model}",
                "supportedGenerationMethods": ["generateContent"],
            }]}
        return 200, {"candidates": [{"content": {"parts": [{"text": text}]}}]}
    return fake


def clues_json(client, *symbols):
    with with_targets(*symbols):
        response = client.get("/api/clues", params={"disease_id": PAH_ID})
    assert response.status_code == 200
    return response.json()


def clue_named(clues, name):
    found = [clue for clue in clues if clue["medicine"] == name]
    assert len(found) == 1, f"expected one {name}, found {len(found)}"
    return found[0]


# ---- Example 1 ----

def test_five_proteins_give_16_new_clues_in_kashishs_order(client):
    data = clues_json(client, *FIVE)
    assert [clue["medicine"] for clue in data["new_clues"]] == NEW_ORDER
    assert len(data["new_clues"]) == 16
    assert data["new_clues"][0]["medicine"] == "Dibotermin Alfa"


def test_five_proteins_give_2_being_studied_udenafil_then_vardenafil(client):
    data = clues_json(client, *FIVE)
    assert [clue["medicine"] for clue in data["being_studied"]] == ["Udenafil", "Vardenafil"]


def test_the_api_order_is_the_engines_order(client):
    ranked = engine.find_ranked_clues(PAH, targets_named(*FIVE))
    data = clues_json(client, *FIVE)
    for key, clues in (("new_clues", ranked.new_clues), ("being_studied", ranked.being_studied)):
        assert [c["medicine"].upper() for c in data[key]] == [
            clue.medicine.name.upper() for clue in clues
        ]
        assert [c["reports"] for c in data[key]] == [clue.reports for clue in clues]


def test_clues_carry_the_disease_and_the_rule_text_word_for_word(client):
    data = clues_json(client, *FIVE)
    assert data["disease"] == {"id": PAH_ID, "name": "pulmonary arterial hypertension"}
    assert data["rule_text"] == RULE_TEXT


def test_each_clue_has_its_facts_and_no_explanation(client):
    data = clues_json(client, *FIVE)
    ids = set()
    for clue in data["new_clues"] + data["being_studied"]:
        assert set(clue) == {
            "id", "medicine", "forms", "proteins", "reports", "source",
            "trial_phase", "ending",
        }
        assert clue["id"] and clue["forms"] and clue["proteins"]
        assert isinstance(clue["reports"], int)
        for protein in clue["proteins"]:
            assert set(protein) == {"symbol", "points", "direction", "machine", "piece_of_machine"}
            assert protein["direction"] in ("up", "down", "mixed", "unknown")
        ids.add(clue["id"])
    assert len(ids) == 18  # every clue has its own id


def test_forms_are_shown_inside_the_medicine(client):
    data = clues_json(client, *FIVE)
    assert clue_named(data["new_clues"], "Doxapram")["forms"] == [
        "Doxapram", "Doxapram Hydrochloride",
    ]


def test_one_source_link_or_none(client):
    data = clues_json(client, *FIVE)
    for clue in data["new_clues"] + data["being_studied"]:
        assert clue["source"] is None or clue["source"].startswith("https://")
    assert clue_named(data["new_clues"], "Sevoflurane")["source"].startswith("https://")


def test_trial_phase_is_only_for_being_studied(client):
    data = clues_json(client, *FIVE)
    assert all(clue["trial_phase"] is None for clue in data["new_clues"])
    assert clue_named(data["being_studied"], "Vardenafil")["trial_phase"] == "Phase 3"
    assert all(clue["trial_phase"].startswith("Phase ") or
               clue["trial_phase"].startswith("Early Phase ")
               for clue in data["being_studied"])


def test_one_protein_gets_the_ending_word_for_word(client):
    data = clues_json(client, *FIVE)
    assert clue_named(data["new_clues"], "Sevoflurane")["ending"] == ENDING


# ---- Example 2 ----

def all_api_text(client):
    """Everything the API can say about PAH, joined, in capitals."""
    said = [client.get("/").text]
    said.append(client.get("/api/search", params={"q": "pulmonary arterial hypertension"}).text)
    with with_saved_targets():
        clues = client.get("/api/clues", params={"disease_id": PAH_ID})
        said.append(clues.text)
        with patch("moonlight.explain._gemini_request", side_effect=gemini_unreachable):
            for clue in clues.json()["new_clues"] + clues.json()["being_studied"]:
                answer = client.get(
                    "/api/explain", params={"disease_id": PAH_ID, "clue_id": clue["id"]}
                )
                assert answer.status_code == 200
                said.append(answer.text)
    return "\n".join(said).upper()


def test_no_response_contains_sildenafil_or_tadalafil(client):
    text = all_api_text(client)
    assert "VARDENAFIL" in text  # it really answered
    assert "SILDENAFIL" not in text
    assert "TADALAFIL" not in text


def test_no_response_names_any_medicine_from_a_hidden_group(client):
    saved = [t for t in fetch.fetch_targets(PAH) if t.id in SAVED_IDS]
    tray = engine.find_clues(PAH, saved)
    hidden = set()
    for group in ("not_approved", "already_approved", "unclear_link"):
        for path in tray[group]:
            hidden.add(path.medicine.name.upper())
            hidden.update(form.name.upper() for form in path.medicine.forms)
    assert "SILDENAFIL" in hidden and len(hidden) > 10
    text = all_api_text(client)
    assert [name for name in sorted(hidden) if name in text] == []


def test_a_hidden_medicine_cannot_be_explained(client):
    (pde5a,) = targets_named("PDE5A")
    sildenafil = [
        p for p in fetch.fetch_paths(PAH, pde5a) if p.medicine.name.upper() == "SILDENAFIL"
    ][0]
    with with_targets(*FIVE), \
            patch("moonlight.explain._gemini_request", side_effect=gemini_unreachable):
        answer = client.get(
            "/api/explain",
            params={"disease_id": PAH_ID, "clue_id": sildenafil.medicine.forms[0].id},
        )
    assert answer.status_code == 404
    assert "SILDENAFIL" not in answer.text.upper()


def test_gemini_naming_a_hidden_medicine_is_thrown_away(client):
    data = clues_json(client, *FIVE)
    avanafil = clue_named(data["new_clues"], "Avanafil")
    sneaky = (
        "Avanafil is a medicine. Sildenafil is a medicine too. "
        "It grabs a protein called PDE5A. A protein is a tiny machine in your body."
    )
    with with_targets(*FIVE), \
            patch("moonlight.explain._gemini_request", side_effect=gemini_says(sneaky)):
        answer = client.get(
            "/api/explain", params={"disease_id": PAH_ID, "clue_id": avanafil["id"]}
        )
    assert answer.status_code == 200
    assert answer.json()["source"] == "template"
    assert "SILDENAFIL" not in answer.text.upper()


# ---- Example 3 ----

def test_left_out_is_three_numbers_12_6_0(client):
    data = clues_json(client, *FIVE)
    assert data["left_out"] == {"not_approved": 12, "already_approved": 6, "unclear_link": 0}
    assert list(data["left_out"].values()) == [12, 6, 0]


# ---- Example 4 ----

def test_sevoflurane_kcnk3_score_is_79(client):
    data = clues_json(client, *FIVE)
    sevoflurane = clue_named(data["new_clues"], "Sevoflurane")
    assert sevoflurane["proteins"] == [{
        "symbol": "KCNK3", "points": 79, "direction": "up",
        "machine": 1, "piece_of_machine": False,
    }]


def test_points_are_the_same_whole_numbers_the_explainer_uses(client):
    ranked = engine.find_ranked_clues(PAH, targets_named(*FIVE))
    data = clues_json(client, *FIVE)
    shown = data["new_clues"] + data["being_studied"]
    for clue, sent in zip(ranked.new_clues + ranked.being_studied, shown):
        facts = explain.facts_for(clue, PAH)
        assert [f"{p['points']} points out of 100" for p in sent["proteins"]] == [
            p["link_score_as_points"] for p in facts["proteins"]
        ]
        assert all(isinstance(p["points"], int) for p in sent["proteins"])


# ---- Example 5 ----

def test_isosorbide_mononitrate_is_one_clue_with_three_pieces_of_one_machine(client):
    data = clues_json(client, *GUCY1)
    isosorbide = clue_named(data["new_clues"], "Isosorbide Mononitrate")  # insists on one
    assert [p["symbol"] for p in isosorbide["proteins"]] == list(GUCY1)
    assert [p["points"] for p in isosorbide["proteins"]] == [60, 58, 58]
    assert [p["machine"] for p in isosorbide["proteins"]] == [1, 1, 1]
    assert all(p["piece_of_machine"] for p in isosorbide["proteins"])
    assert [p["direction"] for p in isosorbide["proteins"]] == ["up", "up", "up"]


def test_more_than_one_protein_gets_the_these_proteins_ending(client):
    data = clues_json(client, *GUCY1)
    assert clue_named(data["new_clues"], "Isosorbide Mononitrate")["ending"] == ENDING_MANY


# ---- Example 6 ----

GOOD_ANSWER = load(ROOT / "fixtures" / "gemini" / "sevoflurane_generate.response.json")[
    "candidates"][0]["content"]["parts"][0]["text"]


def explain_sevoflurane(client, gemini):
    data = clues_json(client, *FIVE)
    sevoflurane = clue_named(data["new_clues"], "Sevoflurane")
    with with_targets(*FIVE), patch("moonlight.explain._gemini_request", side_effect=gemini):
        answer = client.get(
            "/api/explain", params={"disease_id": PAH_ID, "clue_id": sevoflurane["id"]}
        )
    assert answer.status_code == 200
    return sevoflurane, answer.json()


def test_explain_gives_gemini_text_ending_with_the_ending(client):
    sevoflurane, answer = explain_sevoflurane(client, gemini_says(GOOD_ANSWER))
    assert set(answer) == {"clue_id", "text", "source", "model"}
    assert answer["clue_id"] == sevoflurane["id"]
    assert answer["text"] == GOOD_ANSWER + " " + ENDING
    assert answer["text"].endswith(ENDING)
    assert answer["source"] == "gemini"
    assert answer["model"] == "gemini-3.5-flash"


def test_explain_gives_the_template_when_gemini_cannot_be_reached(client):
    _, answer = explain_sevoflurane(client, gemini_unreachable)
    assert answer["source"] == "template"
    assert answer["model"] is None
    assert answer["text"].startswith("Sevoflurane is a medicine.")
    assert answer["text"].endswith(ENDING)


def test_explain_for_a_clue_that_is_not_there_is_404(client):
    with with_targets(*FIVE), \
            patch("moonlight.explain._gemini_request", side_effect=gemini_unreachable):
        answer = client.get(
            "/api/explain", params={"disease_id": PAH_ID, "clue_id": "CHEMBL0"}
        )
    assert answer.status_code == 404


# ---- Example 7 ----

def test_the_page_has_the_safety_line_word_for_word(client):
    response = client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert SAFETY_LINE in response.text
    assert SAFETY_LINE in (ROOT / "CLAUDE.md").read_text(encoding="utf-8").replace(
        "\n  ", " "
    )


def test_the_safety_line_is_in_the_html_before_any_script(client):
    page = client.get("/").text
    assert page.index(SAFETY_LINE) < page.index("<script")
    assert 'data-slot="safety-line"' in page[: page.index(SAFETY_LINE)]


def test_the_page_has_the_rule_text_slot_and_sidhas_other_slots(client):
    page = client.get("/").text
    for slot in (
        "rule-text", "safety-line", "search", "matches", "chips", "new-clues",
        "studied", "left-out", "card", "medicine-name", "forms", "reports",
        "path", "protein", "score", "direction", "explanation", "ending",
        "source", "phase", "loading", "empty",
    ):
        assert f'data-slot="{slot}"' in page, slot


def test_the_page_has_no_outside_link(client):
    page = client.get("/").text
    assert "http" not in page.lower()  # no font, script, stylesheet or any other outside address
    assert "//" not in re.sub(r"(?s)<script>.*?</script>", "", page)  # no "//host" address either
    assert "@import" not in page
    assert "<link" not in page.lower()
    assert not re.search(r"<script[^>]+src", page, flags=re.IGNORECASE)
    assert "target=" not in page  # nothing opens in a new tab
    assert "window.open" not in page


def test_the_page_wording(client):
    page = client.get("/").text
    assert 'placeholder="Type a disease name"' in page
    assert "Search by disease name<" in page
    assert (
        "An explorer that shows which existing medicines act on the proteins "
        "linked to a disease, using open research data."
    ) in page
    assert "Please wait, fetching data" in page
    assert "Already being studied for this disease" in page
    assert "The data does not say which direction this disease needs." in page
    assert "Read explanation" in page


def test_the_only_quick_start_chip_is_pah_by_its_id(client):
    page = client.get("/").text
    chips = re.findall(r'<button class="chip"[^>]*>(.*?)</button>', page)
    assert chips == ["Pulmonary arterial hypertension"]
    assert 'data-disease-id="MONDO_0015924"' in page


def test_the_page_names_no_medicine_before_a_search(client):
    page = client.get("/").text.upper()
    for name in NEW_ORDER + ["Udenafil", "Vardenafil", "Sildenafil", "Tadalafil"]:
        assert name.upper() not in page


# ---- /api/search ----

def test_search_gives_matches_best_first(client):
    response = client.get("/api/search", params={"q": "pulmonary arterial hypertension"})
    assert response.status_code == 200
    matches = response.json()["matches"]
    assert matches[0] == {"id": PAH_ID, "name": "pulmonary arterial hypertension"}
    assert all(set(match) == {"id", "name"} for match in matches)
    assert [m["id"] for m in matches] == [
        d.id for d in fetch.search_diseases("pulmonary arterial hypertension")
    ]


def test_search_with_nothing_typed_asks_nothing_and_matches_nothing(client):
    with patch("moonlight.api.search_diseases") as spy:
        response = client.get("/api/search", params={"q": "   "})
    assert response.json() == {"matches": []}
    spy.assert_not_called()


# ---- when things go wrong ----

def test_a_disease_open_targets_does_not_know_is_404(client):
    response = client.get("/api/clues", params={"disease_id": "MONDO_0000000"})
    assert response.status_code == 404


def test_a_disease_with_no_clues_gives_empty_lists_and_zero_counts(client):
    with patch("moonlight.api.fetch_targets", return_value=[]):
        data = client.get("/api/clues", params={"disease_id": PAH_ID}).json()
    assert data["new_clues"] == [] and data["being_studied"] == []
    assert data["left_out"] == {"not_approved": 0, "already_approved": 0, "unclear_link": 0}


def test_open_targets_being_down_is_a_502_not_a_crash(client):
    with patch("moonlight.fetch._post_json", side_effect=requests.ConnectionError("down")):
        response = client.get("/api/clues", params={"disease_id": PAH_ID})
    assert response.status_code == 502
    assert "detail" in response.json()


def test_the_api_asks_for_the_top_25_proteins(client):
    with patch("moonlight.api.fetch_targets", return_value=[]) as spy:
        client.get("/api/clues", params={"disease_id": PAH_ID})
    assert spy.call_args.args[1:] == (25,) or spy.call_args.kwargs.get("limit") == 25


# =====================================================================
# Ticket 6.3: the API gives explain() the data version, so a finished
# explanation is saved
# =====================================================================

from moonlight import cache  # noqa: E402

NEW_ENDING = "This is only a clue to read about. Do not try it."


def fake_send(body):
    """Stands in for fetch._send. Only the data version is ever asked for
    here, because fetch._post_json is already swapped for saved files.
    The shape was copied from the live API on 2026-11-12."""
    assert "dataVersion" in body["query"], "only the data version may be asked"
    return {"data": {"meta": {"dataVersion": {"year": "26", "month": "09",
                                              "iteration": None}}}}


@pytest.fixture(autouse=True)
def pretend_data_version_and_throwaway_folder(tmp_path, monkeypatch):
    """Every test in this file gets data version 26.09 and a throwaway
    folder for the saved results.

    Kashish's decision, 2026-11-13 (asked under STOP AND ASK). The API now
    reads the data version for /api/explain. The ticket 5.1 tests above
    block the network and had no pretend version, so five of them failed.
    This is new set-up. No line of those tests was changed.
    """
    monkeypatch.setenv("MOONLIGHT_CACHE_DIR", str(tmp_path / "saved"))
    cache.forget_memory()
    fetch.forget_version()
    with patch("moonlight.fetch._send", side_effect=fake_send):
        yield tmp_path / "saved"
    cache.forget_memory()
    fetch.forget_version()


@pytest.fixture
def saved_results(pretend_data_version_and_throwaway_folder):
    """The throwaway folder the saved results go in."""
    return pretend_data_version_and_throwaway_folder


def new_program():
    """What a restarted server starts with: nothing in memory."""
    explain.forget_everything()
    cache.forget_memory()
    fetch.forget_version()


class CountingGemini:
    """Stands in for explain._gemini_request. Counts the generate calls."""

    def __init__(self, text=GOOD_ANSWER):
        self.text = text
        self.calls = 0  # every call, the model list too
        self.generate_calls = 0

    def __call__(self, method, path, body=None, timeout=None):
        self.calls += 1
        if method == "GET":
            return 200, {"models": [{
                "name": "models/gemini-3.5-flash",
                "supportedGenerationMethods": ["generateContent"],
            }]}
        self.generate_calls += 1
        return 200, {"candidates": [{"content": {"parts": [{"text": self.text}]}}]}


def sevoflurane_id(client):
    return clue_named(clues_json(client, *FIVE)["new_clues"], "Sevoflurane")["id"]


def ask_explain(client, clue_id):
    with with_targets(*FIVE):
        return client.get("/api/explain", params={"disease_id": PAH_ID, "clue_id": clue_id})


# Example 3
def test_63_example_3_two_explain_requests_for_the_same_clue_make_one_gemini_call(
        client, saved_results):
    clue_id = sevoflurane_id(client)
    gemini = CountingGemini()
    with patch("moonlight.explain._gemini_request", side_effect=gemini):
        first = ask_explain(client, clue_id)
        second = ask_explain(client, clue_id)
    assert first.status_code == second.status_code == 200
    assert gemini.generate_calls == 1
    assert second.json() == first.json()
    assert first.json()["source"] == "gemini"


def test_63_example_3_still_one_gemini_call_after_the_server_restarts(client, saved_results):
    clue_id = sevoflurane_id(client)
    gemini = CountingGemini()
    with patch("moonlight.explain._gemini_request", side_effect=gemini):
        first = ask_explain(client, clue_id)
        calls = gemini.calls
        new_program()  # only the disk holds the explanation now
        second = ask_explain(client, clue_id)
    assert gemini.calls == calls  # no Gemini call at all, not even the model list
    assert gemini.generate_calls == 1
    assert second.json() == first.json()
    assert second.json()["source"] == "gemini"


def test_63_the_api_gives_explain_the_data_version(client, saved_results):
    clue_id = sevoflurane_id(client)
    with patch("moonlight.api.explain.explain", wraps=explain.explain) as spy, \
            patch("moonlight.explain._gemini_request", side_effect=CountingGemini()):
        ask_explain(client, clue_id)
    arguments = spy.call_args
    given = arguments.kwargs.get("data_version") or arguments.args[3]
    assert given == "26.09"
    # The explanation is filed under that data version on disk.
    saved = [json.loads(file.read_text(encoding="utf-8"))
             for file in saved_results.rglob("*.json")]
    assert [(entry["kind"], entry["version"]) for entry in saved] == [("explanation", "26.09")]


# Example 4
def test_63_example_4_changing_the_ending_means_a_saved_explanation_is_not_reused(
        client, saved_results):
    clue_id = sevoflurane_id(client)
    gemini = CountingGemini()
    with patch("moonlight.explain._gemini_request", side_effect=gemini):
        old = ask_explain(client, clue_id).json()
        assert gemini.generate_calls == 1

        new_program()  # only the disk holds the old text now
        with patch("moonlight.explain.ENDING", NEW_ENDING):
            new = ask_explain(client, clue_id).json()
    assert gemini.generate_calls == 2  # asked afresh, the saved one was not reused
    assert old["text"].endswith(ENDING)
    assert new["text"].endswith(NEW_ENDING)
    assert ENDING not in new["text"]


def test_63_example_4_changing_the_ending_without_a_restart_is_not_reused_either(
        client, saved_results):
    clue_id = sevoflurane_id(client)
    gemini = CountingGemini()
    with patch("moonlight.explain._gemini_request", side_effect=gemini):
        ask_explain(client, clue_id)
        with patch("moonlight.explain.ENDING", NEW_ENDING):
            new = ask_explain(client, clue_id).json()
    assert gemini.generate_calls == 2
    assert new["text"].endswith(NEW_ENDING)
    assert ENDING not in new["text"]


def test_63_a_template_explanation_is_not_saved_so_gemini_gets_another_go(client, saved_results):
    clue_id = sevoflurane_id(client)
    with patch("moonlight.explain._gemini_request", side_effect=gemini_unreachable):
        first = ask_explain(client, clue_id).json()
    assert first["source"] == "template"
    assert not list(saved_results.rglob("*.json"))
    gemini = CountingGemini()
    with patch("moonlight.explain._gemini_request", side_effect=gemini):
        second = ask_explain(client, clue_id).json()
    assert second["source"] == "gemini"
    assert gemini.generate_calls == 1


def test_63_if_the_data_version_cannot_be_read_it_is_a_502_not_a_crash(client, saved_results):
    clue_id = sevoflurane_id(client)
    gemini = CountingGemini()
    with patch("moonlight.fetch._send", side_effect=requests.ConnectionError("down")), \
            patch("moonlight.explain._gemini_request", side_effect=gemini):
        response = ask_explain(client, clue_id)
    assert response.status_code == 502
    assert "detail" in response.json()
    assert gemini.calls == 0
