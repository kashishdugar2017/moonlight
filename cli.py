"""Terminal runner: print the repurposing clues for a disease.

    python cli.py "pulmonary arterial hypertension"
    python cli.py "pulmonary arterial hypertension" --pick 2

It prints the safety line first, then the diseases that matched, then two
sections ("New clues" and "Already being studied for this disease"), then
how many medicines were left out, as counts only. A medicine from a group
that is not shown is never named.

Both sections are in Kashish's ranked order (moonlight/rank.py), and each
medicine is printed once, on one line that names every protein it acts on
and says which of them are pieces of one machine. Those count once.
"""

import argparse
import sys
from typing import List, Optional

import requests

from moonlight.engine import find_ranked_clues
from moonlight.fetch import FetchError, fetch_targets, search_diseases
from moonlight.filter import ALREADY_APPROVED, NOT_APPROVED, UNCLEAR_LINK
from moonlight.rank import RULE_TEXT, Clue
from moonlight.records import Disease, Target

# Word for word from CLAUDE.md. Changing it needs Kashish's approval.
SAFETY_LINE = (
    "For learning and research exploration, not medical advice. "
    "Never start, stop or change any medicine without a doctor."
)
NO_DIRECTION_LINE = "The data does not say which direction this disease needs."

NEW_HEADING = "New clues"
STUDIED_HEADING = "Already being studied for this disease"
LEFT_OUT_HEADING = "Medicines left out (counts only)"

TOP_TARGETS = 25
MATCHES_SHOWN = 5

DIRECTION_WORDS = {
    "up": "turns the protein up",
    "down": "turns the protein down",
    "mixed": "turns the protein both up and down",
    "unknown": "the data does not say if it turns the protein up or down",
}

# In the order they are printed.
LEFT_OUT_LABELS = (
    (NOT_APPROVED, "not approved anywhere"),
    (ALREADY_APPROVED, "already approved for this disease"),
    (UNCLEAR_LINK, "unclear link"),
)


def _phase_words(stage: str) -> str:
    """"PHASE_2_3" -> "Phase 2/3", "EARLY_PHASE_1" -> "Early Phase 1"."""
    early = stage.startswith("EARLY_")
    numbers = stage.replace("EARLY_", "").replace("PHASE_", "").replace("_", "/")
    return ("Early " if early else "") + "Phase " + numbers


def _machine_note(symbols: List[str]) -> str:
    """["A", "B", "C"] -> "A, B and C are pieces of one machine, counted once"."""
    listed = ", ".join(symbols[:-1]) + " and " + symbols[-1]
    return f"{listed} are pieces of one machine, counted once"


def _clue_line(clue: Clue, with_phase: bool) -> str:
    """One medicine: its forms, every protein it acts on (strongest first,
    each with its score and direction), which proteins are pieces of one
    machine, the score if there is more than one protein, the number of
    reports, and one source."""
    medicine = clue.medicine
    forms = ", ".join(form.name for form in medicine.forms)
    parts = [f"- {medicine.name} (forms: {forms})"]
    for path in clue.paths:  # a Clue keeps its paths strongest first
        parts.append(
            f"protein {path.target.symbol}, link score {path.score:.2f}, "
            f"{DIRECTION_WORDS[path.direction]}"
        )
    for machine in clue.machines:
        if len(machine) > 1:
            parts.append(_machine_note([path.target.symbol for path in machine]))
    if len(clue.paths) > 1:
        parts.append(f"total score {clue.total_score:.2f}")
    parts.append(f"reports: {clue.reports}")
    if with_phase:
        parts.append(f"trial phase: {_phase_words(medicine.disease_stage)}")
    sources = [source for path in clue.paths for source in path.sources]
    if sources:
        parts.append(f"source: {sources[0]}")  # from the strongest protein that has one
    else:
        parts.append("no source link in the data")
    return " | ".join(parts)


def _section(heading: str, clues: List[Clue], with_phase: bool) -> List[str]:
    lines = [_clue_line(clue, with_phase) for clue in clues]
    lines.append(NO_DIRECTION_LINE)
    return [heading] + lines


def clue_lines(disease: Disease, targets: List[Target]) -> List[str]:
    """The two shown sections, then the left-out counts, as lines of text."""
    ranked = find_ranked_clues(disease, targets)

    new = _section(NEW_HEADING, ranked.new_clues, with_phase=False)
    lines = [new[0], RULE_TEXT] + new[1:]  # the rule sits directly under the heading
    lines.append("")
    lines.extend(_section(STUDIED_HEADING, ranked.being_studied, with_phase=True))
    lines.append("")
    lines.append(LEFT_OUT_HEADING)
    for group, label in LEFT_OUT_LABELS:
        lines.append(f"- {label}: {ranked.left_out[group]}")
    return lines


def main(argv: Optional[List[str]] = None) -> int:
    print(SAFETY_LINE)  # always first, whatever happens next

    parser = argparse.ArgumentParser(
        description="Print drug-repurposing clues for a disease."
    )
    parser.add_argument("disease", help="the disease to look up, in quotes")
    parser.add_argument(
        "--pick", type=int, default=1, metavar="N",
        help="use match number N instead of the first one",
    )
    args = parser.parse_args(argv)

    try:
        matches = search_diseases(args.disease)
        if not matches:
            print(f'No disease matched "{args.disease}".')
            return 1

        print()
        print(f'Top matches for "{args.disease}":')
        for number, match in enumerate(matches[:MATCHES_SHOWN], start=1):
            print(f"{number}. {match.name} ({match.id})")
        if not 1 <= args.pick <= len(matches):
            print(f"--pick must be a number from 1 to {len(matches)}.")
            return 2
        disease = matches[args.pick - 1]
        print(f"Using: {disease.name} ({disease.id})")

        targets = fetch_targets(disease, TOP_TARGETS)
        print(f"Looked at the top {len(targets)} proteins linked to this disease.")
        print()
        for line in clue_lines(disease, targets):
            print(line)
    except (FetchError, requests.RequestException) as problem:
        print(f"Could not get the data from Open Targets: {problem}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
