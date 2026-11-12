"""Ticket 2.1-2.3. Each EXAMPLE from Kashish's paper graph is one test here.

These tests never touch the network. fetch.py makes every HTTP call through
one small function, fetch._post_json. Here it is swapped (unittest.mock.patch)
for fake_post_json, which hands back the saved files in fixtures/.
"""

import json
import pathlib
from unittest.mock import patch

import pytest

from moonlight import fetch
from moonlight.records import Disease, Path, Target

FIXTURES = pathlib.Path(__file__).resolve().parent.parent / "fixtures"
GOLDEN = FIXTURES / "MONDO_0015924"
PAH = Disease(id="MONDO_0015924", name="pulmonary arterial hypertension")


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def target_drugs_file(target_id):
    matches = list((GOLDEN / "target_drugs").glob(f"*_{target_id}.response.json"))
    assert len(matches) == 1, f"no saved file for target {target_id}"
    return matches[0]


def fake_post_json(body):
    """Stands in for fetch._post_json: picks the saved response for a request."""
    assert set(body) == {"query", "variables"}
    variables = body["variables"]
    if "text" in variables:
        saved = load(GOLDEN / "disease_search.request.json")["variables"]
        assert variables["text"] == saved["text"], "no saved search for this text"
        return load(GOLDEN / "disease_search.response.json")
    if "targetId" in variables:
        return load(target_drugs_file(variables["targetId"]))
    if "diseaseId" in variables:
        assert variables["diseaseId"] == PAH.id
        return load(GOLDEN / "associated_targets.response.json")
    raise AssertionError(f"unexpected request variables: {variables}")


@pytest.fixture(autouse=True)
def offline():
    """Swap the one HTTP function for the fake, and make real HTTP an error."""
    with patch("moonlight.fetch._post_json", side_effect=fake_post_json) as fake, \
            patch("requests.post", side_effect=AssertionError("network used")), \
            patch("requests.sessions.Session.request",
                  side_effect=AssertionError("network used")):
        yield fake


def targets_by_symbol():
    return {t.symbol: t for t in fetch.fetch_targets(PAH)}


def paths_for(symbol):
    return fetch.fetch_paths(PAH, targets_by_symbol()[symbol])


def family(paths, name):
    found = [p for p in paths if p.medicine.name.upper() == name.upper()]
    assert len(found) == 1, f"expected one {name} family, found {len(found)}"
    return found[0]


def count_forms(paths):
    return sum(len(p.medicine.forms) for p in paths)


# Example 1
def test_search_gives_the_golden_disease_first():
    diseases = fetch.search_diseases("pulmonary arterial hypertension")
    assert all(isinstance(d, Disease) for d in diseases)
    assert diseases[0] == PAH


# Example 2
def test_targets_are_25_with_bmpr2_first_and_pde5a_15th():
    targets = fetch.fetch_targets(PAH)
    assert len(targets) == 25
    assert all(isinstance(t, Target) for t in targets)

    assert targets[0].symbol == "BMPR2"
    assert round(targets[0].score, 2) == 0.85

    assert targets[14].symbol == "PDE5A"
    assert targets[14].id == "ENSG00000138735"
    assert round(targets[14].score, 2) == 0.61

    scores = [t.score for t in targets]
    assert scores == sorted(scores, reverse=True)


def test_targets_asks_for_the_limit(offline):
    fetch.fetch_targets(PAH, limit=7)
    variables = offline.call_args.args[0]["variables"]
    assert variables == {"diseaseId": PAH.id, "size": 7}


# Example 3
def test_pde5a_gives_11_paths_from_13_forms():
    paths = paths_for("PDE5A")
    assert all(isinstance(p, Path) for p in paths)
    assert len(paths) == 11
    assert count_forms(paths) == 13

    sildenafil = family(paths, "Sildenafil")
    assert len(sildenafil.medicine.forms) == 2
    assert sildenafil.medicine.disease_stage == "APPROVAL"

    vardenafil = family(paths, "Vardenafil")
    assert len(vardenafil.medicine.forms) == 2
    assert vardenafil.medicine.disease_stage == "PHASE_3"

    assert family(paths, "Tadalafil").medicine.disease_stage == "APPROVAL"
    assert family(paths, "Udenafil").medicine.disease_stage == "PHASE_2_3"
    assert family(paths, "Avanafil").medicine.disease_stage is None

    assert [p.direction for p in paths] == ["down"] * 11


def test_each_form_keeps_its_own_stage_for_the_disease():
    sildenafil = family(paths_for("PDE5A"), "Sildenafil")
    forms = {f.id: f for f in sildenafil.medicine.forms}
    assert forms["CHEMBL192"].name == "SILDENAFIL"
    assert forms["CHEMBL192"].disease_stage == "PHASE_3"
    assert forms["CHEMBL192"].parent_id is None
    assert forms["CHEMBL1737"].name == "SILDENAFIL CITRATE"
    assert forms["CHEMBL1737"].disease_stage == "APPROVAL"
    assert forms["CHEMBL1737"].parent_id == "CHEMBL192"

    vardenafil = family(paths_for("PDE5A"), "Vardenafil")
    forms = {f.id: f for f in vardenafil.medicine.forms}
    assert forms["CHEMBL1520"].disease_stage == "PHASE_3"
    assert forms["CHEMBL1339"].disease_stage is None


def test_path_carries_target_disease_score_and_action_types():
    pde5a = targets_by_symbol()["PDE5A"]
    for path in fetch.fetch_paths(PAH, pde5a):
        assert path.target == pde5a
        assert path.disease == PAH
        assert path.score == pde5a.score
        assert path.action_types == ("INHIBITOR",)


def test_action_types_are_only_those_for_this_target():
    # Schema notes: pentoxifylline is ANTAGONIST and INHIBITOR overall,
    # but on PDE5A it is only INHIBITOR.
    pentoxifylline = family(paths_for("PDE5A"), "Pentoxifylline")
    assert pentoxifylline.action_types == ("INHIBITOR",)


def test_sources_are_the_urls_from_the_saved_evidence():
    saved = load(target_drugs_file("ENSG00000138735"))
    rows = saved["data"]["target"]["drugAndClinicalCandidates"]["rows"]
    urls = {
        row["drug"]["id"]: [report["url"] for report in row["clinicalReports"]]
        for row in rows
    }
    paths = paths_for("PDE5A")

    sildenafil = family(paths, "Sildenafil")
    expected = set(urls["CHEMBL192"]) | set(urls["CHEMBL1737"])
    assert len(expected) == 12
    assert set(sildenafil.sources) == expected
    assert len(sildenafil.sources) == len(expected)  # no url twice

    assert set(family(paths, "Tadalafil").sources) == set(urls["CHEMBL779"])
    for path in paths:
        assert all(url.startswith("http") for url in path.sources)


# Example 4
def test_ednra_gives_15_paths_from_16_forms():
    paths = paths_for("EDNRA")
    assert len(paths) == 15
    assert count_forms(paths) == 16

    sitaxentan = family(paths, "Sitaxentan")
    assert len(sitaxentan.medicine.forms) == 2
    assert sitaxentan.medicine.disease_stage == "APPROVAL"


# Example 5
def test_kcnk3_gives_6_paths_from_7_forms():
    paths = paths_for("KCNK3")
    assert len(paths) == 6
    assert count_forms(paths) == 7

    doxapram = family(paths, "Doxapram")
    assert len(doxapram.medicine.forms) == 2
    assert doxapram.direction == "down"

    assert family(paths, "Halothane").direction == "up"


# Example 6
def test_bmpr2_gives_2_paths_both_up():
    paths = paths_for("BMPR2")
    assert len(paths) == 2
    assert [p.direction for p in paths] == ["up", "up"]


def test_acvrl1_gives_2_paths_with_best_stages_phase_2_and_phase_1():
    paths = paths_for("ACVRL1")
    assert len(paths) == 2
    assert [p.medicine.best_stage for p in paths] == ["PHASE_2", "PHASE_1"]


def test_a_target_with_no_medicines_gives_no_paths():
    # Schema notes, surprise 7: EIF2AK4 came back with zero drugs.
    assert paths_for("EIF2AK4") == []


def test_an_error_from_open_targets_is_raised_not_hidden(offline):
    offline.side_effect = lambda body: {"errors": [{"message": "boom"}]}
    with pytest.raises(fetch.FetchError):
        fetch.fetch_targets(PAH)


# ---- Ticket 2.8. fetch says which proteins are pieces of one machine ----

GUCY1A1 = "ENSG00000164116"
GUCY1B1 = "ENSG00000061918"
GUCY1A2 = "ENSG00000152402"


def test_the_saved_mechanism_row_lists_all_three_gucy1_proteins():
    # The contract's check, against the saved live response.
    saved = load(target_drugs_file(GUCY1A1))
    rows = saved["data"]["target"]["drugAndClinicalCandidates"]["rows"]
    (drug,) = [r["drug"] for r in rows if r["drug"]["name"] == "ISOSORBIDE MONONITRATE"]
    (mechanism,) = drug["mechanismsOfAction"]["rows"]
    assert {t["id"] for t in mechanism["targets"]} == {GUCY1A1, GUCY1B1, GUCY1A2}


@pytest.mark.parametrize("symbol, own, others", [
    ("GUCY1A1", GUCY1A1, {GUCY1B1, GUCY1A2}),
    ("GUCY1B1", GUCY1B1, {GUCY1A1, GUCY1A2}),
    ("GUCY1A2", GUCY1A2, {GUCY1A1, GUCY1B1}),
])
def test_isosorbide_mononitrate_path_names_the_other_two_pieces(symbol, own, others):
    path = family(paths_for(symbol), "Isosorbide Mononitrate")
    assert set(path.same_machine_ids) == others
    assert len(path.same_machine_ids) == 2  # no id twice
    assert own not in path.same_machine_ids


def test_a_medicine_on_a_one_piece_machine_has_no_partners():
    for path in paths_for("KCNK3") + paths_for("BMPR2"):
        assert path.same_machine_ids == ()
    assert family(paths_for("PDE5A"), "Avanafil").same_machine_ids == ()


def test_only_the_rows_that_list_our_target_give_partners():
    # Pentoxifylline has one row that lists PDE5A with 22 other proteins,
    # and other rows about other targets. Only the first kind counts.
    saved = load(target_drugs_file("ENSG00000138735"))
    rows = saved["data"]["target"]["drugAndClinicalCandidates"]["rows"]
    (drug,) = [r["drug"] for r in rows if r["drug"]["name"] == "PENTOXIFYLLINE"]
    with_pde5a, without = set(), set()
    for mechanism in drug["mechanismsOfAction"]["rows"]:
        ids = {t["id"] for t in mechanism["targets"]}
        if "ENSG00000138735" in ids:
            with_pde5a |= ids
        else:
            without |= ids
    assert len(with_pde5a) == 23 and without and not (with_pde5a & without)

    partners = family(paths_for("PDE5A"), "Pentoxifylline").same_machine_ids
    assert set(partners) == with_pde5a - {"ENSG00000138735"}
    assert len(partners) == 22
    assert not set(partners) & without


# ---- Ticket 3.5: the disease description ----

def saved_disease_record(body):
    assert set(body) == {"query", "variables"}
    assert body["variables"] == {"diseaseId": PAH.id}
    return load(GOLDEN / "disease_description.response.json")


def test_fetch_disease_fills_the_description(offline):
    offline.side_effect = saved_disease_record
    saved = load(GOLDEN / "disease_description.response.json")["data"]["disease"]

    disease = fetch.fetch_disease(PAH.id)

    assert isinstance(disease, Disease)
    assert disease.id == PAH.id
    assert disease.name == "pulmonary arterial hypertension"
    assert disease.description == saved["description"]
    assert disease.description.startswith("Pulmonary arterial hypertension (PAH) is")


def test_fetch_disease_asks_for_the_field_called_description(offline):
    offline.side_effect = saved_disease_record
    fetch.fetch_disease(PAH.id)
    assert "description" in offline.call_args.args[0]["query"]


def test_a_disease_with_no_description_gets_an_empty_one(offline):
    # Open Targets may send null here (the schema says the field can be empty).
    offline.side_effect = lambda body: {
        "data": {"disease": {"id": "D1", "name": "d", "description": None}}
    }
    assert fetch.fetch_disease("D1") == Disease(id="D1", name="d", description="")


def test_a_disease_open_targets_does_not_know_gives_none(offline):
    offline.side_effect = lambda body: {"data": {"disease": None}}
    assert fetch.fetch_disease("NOT_A_REAL_ID") is None


# ---- Ticket 3.5 add-on: ACTIVATOR turns the protein up ----

def test_isosorbide_mononitrate_on_gucy1a1_has_direction_up():
    path = family(paths_for("GUCY1A1"), "Isosorbide Mononitrate")
    assert path.action_types == ("ACTIVATOR",)
    assert path.direction == "up"
