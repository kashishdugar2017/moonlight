"""The sorting tray: put each medicine into one group, using Kashish's rules.

Nothing here fetches or ranks. It only looks at a Medicine family's two
stages (best_stage and disease_stage, both worked out in records.py) and
answers two questions in order.
"""

from typing import Dict, Iterable, List

from moonlight.records import Medicine, Path

NOT_APPROVED = "not_approved"
NEW_CLUE = "new_clue"
BEING_STUDIED = "being_studied"
ALREADY_APPROVED = "already_approved"
UNCLEAR_LINK = "unclear_link"

GROUPS = (NOT_APPROVED, NEW_CLUE, BEING_STUDIED, ALREADY_APPROVED, UNCLEAR_LINK)

# Only these two are ever shown: new_clue in the main list, being_studied in
# the separate "Already being studied for this disease" box.
SHOWN_GROUPS = (NEW_CLUE, BEING_STUDIED)


def group_of(medicine: Medicine) -> str:
    """Which group a medicine family belongs to.

    Question 1: is the family approved for at least one disease?
    Question 2: what is the family's link to OUR disease?
    """
    # Question 1. If the answer is no, stop here, even if there is a link.
    if medicine.best_stage != "APPROVAL":
        return NOT_APPROVED

    # Question 2.
    link = medicine.disease_stage
    if link is None:
        return NEW_CLUE
    if link == "APPROVAL":
        return ALREADY_APPROVED
    if link.startswith("PHASE_") or link.startswith("EARLY_PHASE_"):
        return BEING_STUDIED
    if link in ("WITHDRAWAL", "UNKNOWN"):
        return UNCLEAR_LINK
    raise ValueError(f"Do not know how to sort disease stage: {link!r}")


def sort_paths(paths: Iterable[Path]) -> Dict[str, List[Path]]:
    """Group paths by their medicine's group.

    Every group is always in the answer, even when empty. Paths keep the
    order they came in. Only the groups in SHOWN_GROUPS may be shown.
    """
    tray: Dict[str, List[Path]] = {group: [] for group in GROUPS}
    for path in paths:
        tray[group_of(path.medicine)].append(path)
    return tray
