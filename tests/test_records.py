"""Ticket 1.3. Each EXAMPLE from Kashish's paper graph is one test here.

These tests build records by hand. They read no files and use no network.
"""

import pytest

from moonlight.records import (
    STAGE_ORDER,
    Disease,
    Medicine,
    MedicineForm,
    Path,
    Target,
    direction_from_action_types,
    stronger_stage,
)


def form(id, name, best_stage, disease_stage=None, parent_id=None):
    return MedicineForm(
        id=id,
        name=name,
        best_stage=best_stage,
        disease_stage=disease_stage,
        parent_id=parent_id,
    )


# Example 1
def test_sildenafil_and_its_citrate_are_one_medicine():
    sildenafil = form("CHEMBL192", "SILDENAFIL", "APPROVAL", "PHASE_3")
    citrate = form(
        "CHEMBL1737", "SILDENAFIL CITRATE", "APPROVAL", "APPROVAL", "CHEMBL192"
    )

    medicine = Medicine(name="SILDENAFIL", forms=[sildenafil, citrate])

    assert len(medicine.forms) == 2
    assert medicine.best_stage == "APPROVAL"
    assert medicine.disease_stage == "APPROVAL"


# Example 2
def test_vardenafil_family_keeps_the_link_only_one_form_has():
    vardenafil = form("V1", "VARDENAFIL", "APPROVAL", "PHASE_3")
    hydrochloride = form("V2", "VARDENAFIL HYDROCHLORIDE", "APPROVAL", None, "V1")

    medicine = Medicine(name="VARDENAFIL", forms=[vardenafil, hydrochloride])

    assert len(medicine.forms) == 2
    assert medicine.disease_stage == "PHASE_3"


# Example 2 again, with the forms the other way round: order must not matter.
def test_form_order_does_not_change_the_disease_stage():
    vardenafil = form("V1", "VARDENAFIL", "APPROVAL", "PHASE_3")
    hydrochloride = form("V2", "VARDENAFIL HYDROCHLORIDE", "APPROVAL", None, "V1")

    medicine = Medicine(name="VARDENAFIL", forms=[hydrochloride, vardenafil])

    assert medicine.disease_stage == "PHASE_3"


# Example 3
def test_doxapram_family_with_no_link_has_disease_stage_none():
    doxapram = form("D1", "DOXAPRAM", "APPROVAL")
    hydrochloride = form("D2", "DOXAPRAM HYDROCHLORIDE", "APPROVAL", None, "D1")

    medicine = Medicine(name="DOXAPRAM", forms=[doxapram, hydrochloride])

    assert len(medicine.forms) == 2
    assert medicine.best_stage == "APPROVAL"
    assert medicine.disease_stage is None


# Example 4
def test_tadalafil_alone_is_a_medicine_with_one_form():
    tadalafil = form("T1", "TADALAFIL", "APPROVAL")

    medicine = Medicine(name="TADALAFIL", forms=[tadalafil])

    assert len(medicine.forms) == 1
    assert medicine.forms[0] == tadalafil
    assert medicine.best_stage == "APPROVAL"


def test_best_stage_is_the_strongest_of_the_forms():
    medicine = Medicine(
        name="X", forms=[form("X1", "X", "PHASE_2"), form("X2", "X SALT", "PHASE_3")]
    )

    assert medicine.best_stage == "PHASE_3"


def test_a_medicine_needs_at_least_one_form():
    with pytest.raises(ValueError):
        Medicine(name="NOTHING", forms=[])


# Example 5
def test_phase_2_3_sits_between_phase_2_and_phase_3():
    assert stronger_stage("PHASE_2_3", "PHASE_2") == "PHASE_2_3"
    assert stronger_stage("PHASE_2", "PHASE_2_3") == "PHASE_2_3"
    assert stronger_stage("PHASE_2_3", "PHASE_3") == "PHASE_3"
    assert stronger_stage("PHASE_3", "PHASE_2_3") == "PHASE_3"


def test_stage_order_is_the_one_in_the_ticket():
    assert STAGE_ORDER == (
        "APPROVAL",
        "PHASE_4",
        "PHASE_3",
        "PHASE_2_3",
        "PHASE_2",
        "PHASE_1_2",
        "PHASE_1",
        "EARLY_PHASE_1",
        "WITHDRAWAL",
        "UNKNOWN",
    )
    for stronger, weaker in zip(STAGE_ORDER, STAGE_ORDER[1:]):
        assert stronger_stage(stronger, weaker) == stronger
        assert stronger_stage(weaker, stronger) == stronger


def test_any_stage_is_stronger_than_no_stage():
    assert stronger_stage("UNKNOWN", None) == "UNKNOWN"
    assert stronger_stage(None, "PHASE_1") == "PHASE_1"
    assert stronger_stage(None, None) is None


def test_a_stage_word_we_do_not_know_is_an_error():
    with pytest.raises(ValueError):
        stronger_stage("PHASE_9", "APPROVAL")
    with pytest.raises(ValueError):
        form("Z1", "Z", "approved-ish")


# Example 6
def test_direction_examples():
    assert direction_from_action_types(["INHIBITOR"]) == "down"
    assert direction_from_action_types(["OPENER"]) == "up"
    assert direction_from_action_types([]) == "unknown"


@pytest.mark.parametrize("action", ["INHIBITOR", "ANTAGONIST", "BLOCKER"])
def test_down_action_types(action):
    assert direction_from_action_types([action]) == "down"


@pytest.mark.parametrize(
    "action",
    ["AGONIST", "OPENER", "POSITIVE MODULATOR", "POSITIVE ALLOSTERIC MODULATOR"],
)
def test_up_action_types(action):
    assert direction_from_action_types([action]) == "up"


def test_up_and_down_together_is_mixed():
    assert direction_from_action_types(["INHIBITOR", "AGONIST"]) == "mixed"


def test_an_action_type_not_on_either_list_is_unknown():
    assert direction_from_action_types(["MODULATOR"]) == "unknown"


def test_path_holds_the_whole_chain_and_its_direction():
    disease = Disease(id="MONDO_0015924", name="pulmonary arterial hypertension")
    target = Target(
        id="ENSG00000138735",
        symbol="PDE5A",
        name="phosphodiesterase 5A",
        score=0.61,
    )
    medicine = Medicine(name="TADALAFIL", forms=[form("T1", "TADALAFIL", "APPROVAL")])

    path = Path(
        medicine=medicine,
        target=target,
        disease=disease,
        action_types=["INHIBITOR"],
        score=0.61,
        sources=["https://example.org/label"],
    )

    assert path.medicine is medicine
    assert path.target.symbol == "PDE5A"
    assert path.disease.name == "pulmonary arterial hypertension"
    assert path.action_types == ("INHIBITOR",)
    assert path.direction == "down"
    assert path.score == 0.61
    assert path.sources == ("https://example.org/label",)


def test_path_with_no_action_types_says_unknown():
    path = Path(
        medicine=Medicine(name="T", forms=[form("T1", "T", "APPROVAL")]),
        target=Target(id="E1", symbol="S", name="n", score=0.5),
        disease=Disease(id="D1", name="d"),
        action_types=[],
        score=0.5,
        sources=[],
    )

    assert path.direction == "unknown"
