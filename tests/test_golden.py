"""Ticket 4.1. The golden test, from Kashish's paper graph.

Examples 3, 4 and 5 of the answer key (docs/paper-graph-answer-key.jpg).
Sildenafil is already a medicine for PAH, so Moonlight must FIND it on the
way (that proves the path works) and must NOT show it as a clue.
Saved files only. No network.
"""

from moonlight import engine, fetch
from moonlight.filter import group_of

from test_fetch import PAH, fake_post_json, offline  # noqa: F401

FIVE = ("BMPR2", "KCNK3", "ACVRL1", "EDNRA", "PDE5A")


def targets_named(*symbols):
    by_symbol = {t.symbol: t for t in fetch.fetch_targets(PAH)}
    return [by_symbol[symbol] for symbol in symbols]


def tray():
    return engine.find_clues(PAH, targets_named(*FIVE))


def all_names(paths):
    """Every medicine name and every form name in these paths, in capitals."""
    names = set()
    for path in paths:
        names.add(path.medicine.name.upper())
        names.update(form.name.upper() for form in path.medicine.forms)
    return names


def find(paths, name):
    found = [p for p in paths if p.medicine.name.upper() == name.upper()]
    assert len(found) == 1, f"expected one {name}, found {len(found)}"
    return found[0]


# Example 3
def test_golden_path_sildenafil_is_found_under_pde5a_with_two_forms():
    (pde5a,) = targets_named("PDE5A")
    sildenafil = find(fetch.fetch_paths(PAH, pde5a), "Sildenafil")
    assert sildenafil.target.symbol == "PDE5A"
    assert [f.name for f in sildenafil.medicine.forms] == [
        "SILDENAFIL",
        "SILDENAFIL CITRATE",
    ]
    assert group_of(sildenafil.medicine) == "already_approved"


def test_golden_path_sildenafil_is_not_shown():
    groups = tray()
    assert find(groups["already_approved"], "Sildenafil")
    shown = all_names(groups["new_clue"]) | all_names(groups["being_studied"])
    assert not any("SILDENAFIL" in name for name in shown)


def test_the_same_for_tadalafil():
    groups = tray()
    tadalafil = find(groups["already_approved"], "Tadalafil")
    assert tadalafil.target.symbol == "PDE5A"
    shown = all_names(groups["new_clue"]) | all_names(groups["being_studied"])
    assert not any("TADALAFIL" in name for name in shown)


# Example 4
def test_vardenafil_is_being_studied_and_its_tablet_form_is_not_a_new_clue():
    groups = tray()
    vardenafil = find(groups["being_studied"], "Vardenafil")
    assert "VARDENAFIL HYDROCHLORIDE" in all_names([vardenafil])
    assert not any("VARDENAFIL" in name for name in all_names(groups["new_clue"]))


# Example 5
def test_being_studied_holds_exactly_udenafil_and_vardenafil():
    names = sorted(p.medicine.name.upper() for p in tray()["being_studied"])
    assert names == ["UDENAFIL", "VARDENAFIL"]
