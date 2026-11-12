"""Terminal runner: print the repurposing clues for a disease.

    python cli.py "pulmonary arterial hypertension"
    python cli.py "pulmonary arterial hypertension" --pick 2

It prints the safety line first, then the diseases that matched, then two
sections ("New clues" and "Already being studied for this disease"), then
how many medicines were left out, as counts only. A medicine from a group
that is not shown is never named.
"""

import argparse
import sys
from typing import List, Optional

import requests

from moonlight.engine import find_clues
from moonlight.fetch import FetchError, fetch_targets, search_diseases
from moonlight.filter import (
    ALREADY_APPROVED,
    BEING_STUDIED,
    NEW_CLUE,
    NOT_APPROVED,
    UNCLEAR_LINK,
)
from moonlight.records import Disease, Path, Target

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


def _clue_line(path: Path, with_phase: bool) -> str:
    """One result: medicine and forms, protein and score, direction, source."""
    forms = ", ".join(form.name for form in path.medicine.forms)
    parts = [
        f"- {path.medicine.name} (forms: {forms})",
        f"protein {path.target.symbol}, link score {path.score:.2f}",
        DIRECTION_WORDS[path.direction],
    ]
    if with_phase:
        parts.append(f"trial phase: {_phase_words(path.medicine.disease_stage)}")
    if path.sources:
        parts.append(f"source: {path.sources[0]}")
    else:
        parts.append("no source link in the data")
    return " | ".join(parts)


def _section(heading: str, paths: List[Path], with_phase: bool) -> List[str]:
    lines = [heading]
    lines.extend(_clue_line(path, with_phase) for path in paths)
    lines.append(NO_DIRECTION_LINE)
    return lines


def clue_lines(disease: Disease, targets: List[Target]) -> List[str]:
    """The two shown sections, then the left-out counts, as lines of text."""
    tray = find_clues(disease, targets)

    lines = _section(NEW_HEADING, tray[NEW_CLUE], with_phase=False)
    lines.append("")
    lines.extend(_section(STUDIED_HEADING, tray[BEING_STUDIED], with_phase=True))
    lines.append("")
    lines.append(LEFT_OUT_HEADING)
    for group, label in LEFT_OUT_LABELS:
        # A medicine that acts on two proteins is still one medicine.
        medicines = {path.medicine.name for path in tray[group]}
        lines.append(f"- {label}: {len(medicines)}")
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
