"""Ticket 2.5. Each EXAMPLE from Kashish's notebook is one test here.

Examples 1 to 3 build records by hand. Example 4 runs fetch and filter on
the saved files in fixtures/. Nothing here touches the network:
fetch._post_json is swapped (unittest.mock.patch) for one that reads the
saved files, and real HTTP is made an error.
"""

import json
import pathlib
from unittest.mock import patch

import pytest

from moonlight import fetch
from moonlight.filter import BEING_STUDIED, NEW_CLUE, sort_paths
from moonlight.rank import RULE_TEXT, Clue, rank_clues
from moonlight.records import Disease, Medicine, MedicineForm, Path, Target

FIXTURES = pathlib.Path(__file__).resolve().parent.parent / "fixtures"
GOLDEN = FIXTURES / "MONDO_0015924"
PAH = Disease(id="MONDO_0015924", name="pulmonary arterial hypertension")


@pytest.fixture(autouse=True)
def no_network():
    with patch("requests.post", side_effect=AssertionError("network used")), \
            patch("requests.sessions.Session.request",
                  side_effect=AssertionError("network used")):
        yield


# ---- helpers for the hand-built examples ----

def protein(symbol, score):
    return Target(id="ENSG_" + symbol, symbol=symbol, name=symbol, score=score)


def medicine(name):
    form = MedicineForm(
        id="ID_" + name.upper().replace(" ", "_"), name=name, best_stage="APPROVAL"
    )
    return Medicine(name=name, forms=(form,))


def path(name, symbol, score, reports):
    """One medicine -> protein path with this many reports (sources)."""
    return Path(
        medicine=medicine(name),
        target=protein(symbol, score),
        disease=PAH,
        action_types=(),
        score=score,
        sources=tuple(f"https://example.org/{name}/{symbol}/{n}" for n in range(reports)),
    )


def names(clues):
    return [clue.medicine.name for clue in clues]


SEVOFLURANE = ("Sevoflurane", "KCNK3", 0.79, 274)
HALOTHANE = ("Halothane", "KCNK3", 0.79, 2)
ENFLURANE = ("Enflurane", "KCNK3", 0.79, 2)
DIBOTERMIN = ("Dibotermin Alfa", "BMPR2", 0.85, 14)
EPTOTERMIN = ("Eptotermin Alfa", "BMPR2", 0.85, 7)
SPARSENTAN = ("Sparsentan", "EDNRA", 0.62, 14)
AVANAFIL = ("Avanafil", "PDE5A", 0.61, 0)
IBUDILAST = ("Ibudilast", "PDE5A", 0.61, 0)

HER_SIX = [SEVOFLURANE, HALOTHANE, DIBOTERMIN, EPTOTERMIN, SPARSENTAN, AVANAFIL]
HER_SIX_IN_ORDER = [
    "Dibotermin Alfa",
    "Eptotermin Alfa",
    "Sevoflurane",
    "Halothane",
    "Sparsentan",
    "Avanafil",
]


# ---- Example 1 ----

def test_example_1_her_six_come_out_in_her_order():
    clues = rank_clues([path(*row) for row in HER_SIX])
    assert names(clues) == HER_SIX_IN_ORDER


def test_example_1_same_input_shuffled_gives_the_same_order():
    backwards = rank_clues([path(*row) for row in reversed(HER_SIX)])
    assert names(backwards) == HER_SIX_IN_ORDER
    again = rank_clues([path(*row) for row in reversed(HER_SIX)])
    assert names(again) == names(backwards)


def test_example_1_each_clue_carries_its_score_and_reports():
    clues = {c.medicine.name: c for c in rank_clues([path(*row) for row in HER_SIX])}
    assert all(isinstance(clue, Clue) for clue in clues.values())
    assert clues["Sevoflurane"].total_score == 0.79
    assert clues["Sevoflurane"].reports == 274
    assert clues["Avanafil"].total_score == 0.61
    assert clues["Avanafil"].reports == 0


# ---- Example 2 ----

@pytest.mark.parametrize("first, second", [(ENFLURANE, HALOTHANE), (AVANAFIL, IBUDILAST)])
def test_example_2_full_ties_go_alphabetical(first, second):
    expected = [first[0], second[0]]
    assert names(rank_clues([path(*first), path(*second)])) == expected
    assert names(rank_clues([path(*second), path(*first)])) == expected


def test_example_2_alphabetical_ignores_case():
    lower_a = ("avanafil", "PDE5A", 0.61, 0)
    clues = rank_clues([path(*IBUDILAST), path(*lower_a)])
    assert names(clues) == ["avanafil", "Ibudilast"]


# ---- Example 3 ----

def test_example_3_two_proteins_make_one_clue_with_scores_added():
    made_up = [
        path("Madeupamine", "KCNK3", 0.5, 1),
        path("Madeupamine", "EDNRA", 0.5, 2),
    ]
    clues = rank_clues([path(*DIBOTERMIN)] + made_up)

    assert names(clues) == ["Madeupamine", "Dibotermin Alfa"]
    clue = clues[0]
    assert clue.total_score == 1.0
    assert clue.reports == 3
    assert len(clue.paths) == 2
    assert {p.target.symbol for p in clue.paths} == {"KCNK3", "EDNRA"}


def test_example_3_strongest_protein_is_named_first():
    clue = rank_clues([
        path("Madeupamine", "EDNRA", 0.3, 0),
        path("Madeupamine", "BMPR2", 0.6, 0),
    ])[0]
    assert [p.target.symbol for p in clue.paths] == ["BMPR2", "EDNRA"]


# ---- Example 4 ----

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
    if "diseaseId" in variables:
        assert variables["diseaseId"] == PAH.id
        return load(GOLDEN / "associated_targets.response.json")
    raise AssertionError(f"unexpected request variables: {variables}")


@pytest.fixture
def tray():
    """fetch then filter, for the five proteins, from the saved files."""
    wanted = {"BMPR2", "KCNK3", "ACVRL1", "EDNRA", "PDE5A"}
    with patch("moonlight.fetch._post_json", side_effect=fake_post_json):
        targets = [t for t in fetch.fetch_targets(PAH) if t.symbol in wanted]
        assert {t.symbol for t in targets} == wanted
        paths = [p for t in targets for p in fetch.fetch_paths(PAH, t)]
    return sort_paths(paths)


def test_example_4_the_16_new_clues_in_order(tray):
    expected = [
        "Dibotermin Alfa", "Eptotermin Alfa", "Sevoflurane", "Desflurane",
        "Isoflurane", "Doxapram", "Enflurane", "Halothane", "Atrasentan",
        "Sparsentan", "Aprocitentan", "Clazosentan", "Pentoxifylline",
        "Dipyridamole", "Avanafil", "Ibudilast",
    ]
    clues = rank_clues(tray[NEW_CLUE])
    assert [n.upper() for n in names(clues)] == [n.upper() for n in expected]


def test_example_4_the_two_being_studied_in_order(tray):
    clues = rank_clues(tray[BEING_STUDIED])
    assert [n.upper() for n in names(clues)] == ["UDENAFIL", "VARDENAFIL"]


# ---- Contract ----

def test_rule_text_is_exactly_kashishs_words():
    assert RULE_TEXT == (
        "Ordered by how strongly the proteins are linked to the disease. "
        "Pieces of the same machine count once. "
        "If a medicine acts on different machines, the scores are added. "
        "Ties: more reports first, then alphabetical. "
        "Being first on the list does not mean best."
    )


def test_no_paths_gives_no_clues():
    assert rank_clues([]) == []


# ---- Ticket 2.8. Pieces of the same machine count once ----

def piece(name, symbol, score, reports, machine=()):
    """A path whose protein is one piece of a machine. `machine` holds the
    symbols of the other pieces."""
    plain = path(name, symbol, score, reports)
    return Path(
        medicine=plain.medicine,
        target=plain.target,
        disease=plain.disease,
        action_types=plain.action_types,
        score=plain.score,
        sources=plain.sources,
        same_machine_ids=tuple("ENSG_" + other for other in machine),
    )


def isosorbide():
    return [
        piece("Isosorbide Mononitrate", "GUCY1A1", 0.60, 1, ("GUCY1B1", "GUCY1A2")),
        piece("Isosorbide Mononitrate", "GUCY1B1", 0.58, 1, ("GUCY1A1", "GUCY1A2")),
        piece("Isosorbide Mononitrate", "GUCY1A2", 0.58, 1, ("GUCY1A1", "GUCY1B1")),
    ]


# Example 1
def test_2_8_example_1_three_pieces_of_one_machine_count_once():
    (clue,) = rank_clues(isosorbide())
    assert clue.total_score == 0.60
    assert [p.target.symbol for p in clue.paths] == ["GUCY1A1", "GUCY1A2", "GUCY1B1"]
    assert len(clue.machines) == 1
    assert [p.target.symbol for p in clue.machines[0]] == ["GUCY1A1", "GUCY1A2", "GUCY1B1"]


def test_2_8_example_1_from_the_saved_files():
    wanted = {"GUCY1A1", "GUCY1B1", "GUCY1A2"}
    with patch("moonlight.fetch._post_json", side_effect=fake_post_json):
        targets = [t for t in fetch.fetch_targets(PAH) if t.symbol in wanted]
        paths = [p for t in targets for p in fetch.fetch_paths(PAH, t)]
    clues = {c.medicine.name: c for c in rank_clues(sort_paths(paths)[NEW_CLUE])}
    clue = clues["ISOSORBIDE MONONITRATE"]
    assert {p.target.symbol for p in clue.paths} == wanted
    assert len(clue.machines) == 1
    assert round(clue.total_score, 2) == 0.60
    assert clue.total_score == max(p.score for p in clue.paths)


def test_2_8_one_machine_no_longer_jumps_ahead_of_a_stronger_protein():
    clues = rank_clues(isosorbide() + [path(*DIBOTERMIN)])
    assert names(clues) == ["Dibotermin Alfa", "Isosorbide Mononitrate"]


def test_2_8_a_machine_is_found_even_if_only_one_piece_names_the_other():
    clue = Clue(paths=(
        piece("Madeupamine", "AAA", 0.7, 0, ("BBB",)),
        piece("Madeupamine", "BBB", 0.6, 0),
    ))
    assert clue.total_score == 0.7
    assert len(clue.machines) == 1


def test_2_8_a_partner_the_medicine_has_no_path_to_changes_nothing():
    # The machine has a piece outside the proteins we looked at.
    clue = Clue(paths=(piece("Madeupamine", "AAA", 0.7, 0, ("ZZZ",)),))
    assert clue.total_score == 0.7
    assert len(clue.machines) == 1


# Example 2
def test_2_8_example_2_two_different_machines_add():
    clue = Clue(paths=(
        piece("Madeupamine", "KCNK3", 0.5, 1),
        piece("Madeupamine", "EDNRA", 0.5, 2),
    ))
    assert clue.total_score == 1.0
    assert len(clue.machines) == 2


# Example 3
def test_2_8_example_3_a_two_piece_machine_and_a_separate_machine():
    clue = Clue(paths=(
        piece("Madeupamine", "AAA", 0.7, 0, ("BBB",)),
        piece("Madeupamine", "BBB", 0.6, 0, ("AAA",)),
        piece("Madeupamine", "CCC", 0.4, 0),
    ))
    assert clue.total_score == pytest.approx(1.1)
    assert round(clue.total_score, 2) == 1.1
    assert [[p.target.symbol for p in m] for m in clue.machines] == [["AAA", "BBB"], ["CCC"]]


# Example 4 is test_example_4_the_16_new_clues_in_order above. It is not changed.


def test_2_8_rule_text_is_exactly_kashishs_new_words():
    assert RULE_TEXT == (
        "Ordered by how strongly the proteins are linked to the disease. "
        "Pieces of the same machine count once. "
        "If a medicine acts on different machines, the scores are added. "
        "Ties: more reports first, then alphabetical. "
        "Being first on the list does not mean best."
    )
