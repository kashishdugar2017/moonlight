"""Ticket 2.6. The terminal runner, cli.py.

Saved files exist for 11 targets only, so these tests hand cli those targets.
No network.
"""

import pathlib
from unittest.mock import patch

import pytest

import cli
from moonlight import engine, fetch
from moonlight.filter import SHOWN_GROUPS

from test_fetch import GOLDEN, PAH, fake_post_json, offline  # noqa: F401

SAFETY = (
    "For learning and research exploration, not medical advice. "
    "Never start, stop or change any medicine without a doctor."
)
NO_DIRECTION = "The data does not say which direction this disease needs."
FIVE = ("BMPR2", "KCNK3", "ACVRL1", "EDNRA", "PDE5A")
SAVED_IDS = {
    path.name.split(".")[0].split("_")[-1]
    for path in (GOLDEN / "target_drugs").glob("*.response.json")
}


def targets_named(*symbols):
    by_symbol = {t.symbol: t for t in fetch.fetch_targets(PAH)}
    return [by_symbol[symbol] for symbol in symbols]


def saved_targets(disease, limit=25):
    """Stands in for fetch.fetch_targets: only the targets with saved files.

    The only saved target list is PAH's, so it is used whatever disease is asked.
    """
    return [t for t in fetch.fetch_targets(PAH, limit) if t.id in SAVED_IDS]


def run(*argv):
    """Run the command the way the terminal would. Gives (exit code, lines)."""
    printed = []
    with patch("cli.fetch_targets", side_effect=saved_targets) as spy, \
            patch("builtins.print", side_effect=lambda *a, **k: printed.append(
                " ".join(str(x) for x in a))):
        code = cli.main(list(argv))
    run.fetch_targets = spy
    return code, "\n".join(printed).split("\n")


def section(lines, heading):
    """The lines under a heading, up to the next blank line."""
    start = lines.index(heading) + 1
    end = lines.index("", start) if "" in lines[start:] else len(lines)
    return lines[start:end]


def line_for(lines, medicine):
    found = [l for l in lines if l.lstrip("- ").upper().startswith(medicine.upper())]
    assert len(found) == 1, f"expected one line for {medicine}, found {len(found)}"
    return found[0]


def test_safety_line_is_in_claude_md_word_for_word():
    claude_md = pathlib.Path(cli.__file__).with_name("CLAUDE.md").read_text("utf-8")
    assert SAFETY in " ".join(claude_md.split())
    assert cli.SAFETY_LINE == SAFETY


def test_the_safety_line_is_printed_first():
    code, lines = run("pulmonary arterial hypertension")
    assert code == 0
    assert lines[0] == SAFETY


def test_the_safety_line_is_first_even_when_nothing_is_typed():
    printed = []
    with patch("builtins.print", side_effect=lambda *a, **k: printed.append(a)), \
            pytest.raises(SystemExit):
        cli.main([])
    assert printed[0] == (SAFETY,)


def test_it_prints_the_top_matches_and_uses_the_first():
    code, lines = run("pulmonary arterial hypertension")
    text = "\n".join(lines)
    assert "1. pulmonary arterial hypertension (MONDO_0015924)" in text
    assert "2. heritable pulmonary arterial hypertension (MONDO_0017148)" in text
    assert "Using: pulmonary arterial hypertension (MONDO_0015924)" in lines


def test_pick_chooses_another_match():
    with patch("cli.find_ranked_clues", wraps=engine.find_ranked_clues) as spy:
        code, lines = run("pulmonary arterial hypertension", "--pick", "2")
    assert "Using: heritable pulmonary arterial hypertension (MONDO_0017148)" in lines
    assert spy.call_args.args[0].id == "MONDO_0017148"


def test_a_pick_that_is_not_on_the_list_stops_politely():
    code, lines = run("pulmonary arterial hypertension", "--pick", "99")
    assert code != 0
    assert lines[0] == SAFETY
    assert "New clues" not in lines


def test_it_asks_for_the_top_25_targets():
    run("pulmonary arterial hypertension")
    assert run.fetch_targets.call_args.args == (PAH, 25)


def test_the_two_sections_come_in_order_with_the_direction_note_under_each():
    lines = cli.clue_lines(PAH, targets_named(*FIVE))
    new = lines.index("New clues")
    studied = lines.index("Already being studied for this disease")
    assert new < studied
    assert section(lines, "New clues")[-1] == NO_DIRECTION
    assert section(lines, "Already being studied for this disease")[-1] == NO_DIRECTION
    assert lines.count(NO_DIRECTION) == 2


def test_new_clues_has_16_lines_and_being_studied_has_2():
    lines = cli.clue_lines(PAH, targets_named(*FIVE))
    # + the rule text (ticket 2.7) and the direction note
    assert len(section(lines, "New clues")) == 16 + 2
    assert len(section(lines, "Already being studied for this disease")) == 2 + 1


def test_a_new_clue_line_shows_forms_protein_score_direction_and_one_source():
    lines = section(cli.clue_lines(PAH, targets_named(*FIVE)), "New clues")
    doxapram = line_for(lines, "Doxapram")
    assert "DOXAPRAM, DOXAPRAM HYDROCHLORIDE" in doxapram
    assert "KCNK3" in doxapram
    assert "0.79" in doxapram
    assert "turns the protein down" in doxapram
    assert doxapram.count("http") == 1
    tray = engine.find_clues(PAH, targets_named("KCNK3"))
    (path,) = [p for p in tray["new_clue"] if p.medicine.name == "DOXAPRAM"]
    assert path.sources[0] in doxapram
    assert "phase" not in doxapram.lower()

    halothane = line_for(lines, "Halothane")
    assert "turns the protein up" in halothane


def test_a_line_with_no_source_in_the_data_says_so():
    lines = section(cli.clue_lines(PAH, targets_named("PDE5A")), "New clues")
    avanafil = line_for(lines, "Avanafil")
    assert "http" not in avanafil
    assert "no source link in the data" in avanafil


def test_being_studied_lines_show_the_trial_phase():
    lines = section(
        cli.clue_lines(PAH, targets_named(*FIVE)),
        "Already being studied for this disease",
    )
    vardenafil = line_for(lines, "Vardenafil")
    assert "VARDENAFIL, VARDENAFIL HYDROCHLORIDE" in vardenafil
    assert "PDE5A" in vardenafil and "0.61" in vardenafil
    assert "turns the protein down" in vardenafil
    assert "trial phase: Phase 3" in vardenafil
    assert "trial phase: Phase 2/3" in line_for(lines, "Udenafil")


def test_left_out_medicines_are_printed_as_counts_only():
    lines = cli.clue_lines(PAH, targets_named(*FIVE))
    left_out = section(lines, "Medicines left out (counts only)")
    assert left_out == [
        "- not approved anywhere: 12",
        "- already approved for this disease: 6",
        "- unclear link: 0",
    ]


def test_no_name_from_a_hidden_group_is_ever_printed():
    code, lines = run("pulmonary arterial hypertension")
    text = "\n".join(lines).upper()
    tray = engine.find_clues(PAH, saved_targets(PAH))
    hidden = set()
    for group, paths in tray.items():
        if group in SHOWN_GROUPS:
            continue
        for path in paths:
            hidden.add(path.medicine.name.upper())
            hidden.update(form.name.upper() for form in path.medicine.forms)
    assert len(hidden) == 20  # 18 medicines, two of them with a tablet form
    for name in sorted(hidden):
        assert name not in text, name
    for name in ("SILDENAFIL", "TADALAFIL", "BOSENTAN", "GISADENAFIL"):
        assert name not in text


def test_when_no_disease_matches_it_says_so_and_stops():
    with patch("cli.search_diseases", return_value=[]):
        code, lines = run("pulmonary arterial hypertension")
    assert code != 0
    assert lines[0] == SAFETY
    assert "New clues" not in lines


# ---- Ticket 2.7. The runner prints the clues in Kashish's ranked order ----

from moonlight.rank import RULE_TEXT  # noqa: E402
from moonlight.records import Medicine, MedicineForm, Path, Target  # noqa: E402

RULE = (
    "Ordered by how strongly the proteins are linked to the disease. "
    "If a medicine acts on more than one protein, the scores are added. "
    "Ties: more reports first, then alphabetical. "
    "Being first on the list does not mean best."
)
NEW_ORDER = [
    "Dibotermin Alfa", "Eptotermin Alfa", "Sevoflurane", "Desflurane",
    "Isoflurane", "Doxapram", "Enflurane", "Halothane", "Atrasentan",
    "Sparsentan", "Aprocitentan", "Clazosentan", "Pentoxifylline",
    "Dipyridamole", "Avanafil", "Ibudilast",
]


def medicines_printed(lines):
    """The medicine name at the start of each "- NAME (forms: ...)" line."""
    return [l[2:].split(" (forms:")[0] for l in lines if l.startswith("- ")]


# Example 1
def test_new_clues_print_in_kashishs_order():
    lines = section(cli.clue_lines(PAH, targets_named(*FIVE)), "New clues")
    assert medicines_printed(lines) == [name.upper() for name in NEW_ORDER]


# Example 2
def test_being_studied_prints_udenafil_then_vardenafil():
    lines = section(
        cli.clue_lines(PAH, targets_named(*FIVE)),
        "Already being studied for this disease",
    )
    assert medicines_printed(lines) == ["UDENAFIL", "VARDENAFIL"]


# Example 3
def test_the_rule_text_is_directly_under_new_clues_word_for_word():
    lines = cli.clue_lines(PAH, targets_named(*FIVE))
    assert RULE_TEXT == RULE
    assert lines[lines.index("New clues") + 1] == RULE
    assert lines.count(RULE) == 1


def made_up_paths(disease, target):
    """Stands in for fetch_paths: MADEUPINE acts on every protein it is asked
    about, with 2 reports each. ONLYONE acts on BBB alone."""
    def one(name, reports):
        form = MedicineForm(id="ID_" + name, name=name, best_stage="APPROVAL")
        return Path(
            medicine=Medicine(name=name, forms=(form,)),
            target=target,
            disease=disease,
            action_types=("INHIBITOR",) if target.symbol == "BBB" else ("AGONIST",),
            score=target.score,
            sources=tuple(
                f"https://example.org/{name}/{target.symbol}/{n}"
                for n in range(reports)
            ),
        )
    paths = [one("MADEUPINE", 2)]
    if target.symbol == "BBB":
        paths.append(one("ONLYONE", 1))
    return paths


def made_up_lines():
    weak = Target(id="ENSG_AAA", symbol="AAA", name="AAA", score=0.5)
    strong = Target(id="ENSG_BBB", symbol="BBB", name="BBB", score=0.9)
    with patch("moonlight.engine.fetch_paths", side_effect=made_up_paths):
        return cli.clue_lines(PAH, [weak, strong])  # weakest handed in first


# Example 4
def test_a_medicine_on_two_proteins_is_one_line_with_the_added_score():
    lines = made_up_lines()
    madeupine = line_for(lines, "MADEUPINE")  # line_for insists on one line
    assert "\n".join(lines).count("MADEUPINE (forms:") == 1
    # Both proteins, strongest first, each with its score and its direction.
    bbb = madeupine.index("protein BBB, link score 0.90, turns the protein down")
    aaa = madeupine.index("protein AAA, link score 0.50, turns the protein up")
    assert bbb < aaa
    assert "total score 1.40" in madeupine
    assert madeupine.index("total score 1.40") > aaa
    assert "reports: 4" in madeupine
    assert madeupine.count("http") == 1
    # Added score 1.40 beats 0.90, so it is printed first.
    assert medicines_printed(section(lines, "New clues")) == ["MADEUPINE", "ONLYONE"]


def test_a_medicine_on_one_protein_shows_no_total_score():
    onlyone = line_for(made_up_lines(), "ONLYONE")
    assert "total score" not in onlyone
    assert "reports: 1" in onlyone
    lines = section(cli.clue_lines(PAH, targets_named(*FIVE)), "New clues")
    assert not any("total score" in line for line in lines)


def test_each_line_shows_the_number_of_reports():
    lines = cli.clue_lines(PAH, targets_named(*FIVE))
    assert "reports: 8" in line_for(lines, "Doxapram")
    assert "reports: 274" in line_for(lines, "Sevoflurane")
    assert "reports: 0" in line_for(lines, "Avanafil")
    assert "reports: 0" in line_for(lines, "Vardenafil")


def test_each_medicine_is_printed_once():
    code, lines = run("pulmonary arterial hypertension")
    printed = medicines_printed(lines)
    assert len(printed) == len(set(printed))
