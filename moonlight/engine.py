"""The engine: join fetch and filter into one step.

Give it a disease and a list of targets. It fetches the paths for each
target, one after another, and hands them all to the sorting tray in
filter.py. find_clues does not rank: paths stay in the order they were
fetched. find_ranked_clues then puts the shown groups in Kashish's order
using rank.py, and only counts the groups that are left out.
"""

from dataclasses import dataclass
from typing import Dict, Iterable, List

from moonlight.fetch import fetch_paths
from moonlight.filter import BEING_STUDIED, GROUPS, NEW_CLUE, SHOWN_GROUPS, sort_paths
from moonlight.rank import Clue, rank_clues
from moonlight.records import Disease, Path, Target


@dataclass(frozen=True)
class RankedClues:
    """What may be shown, in ranked order, and how many were left out."""

    new_clues: List[Clue]  # one per medicine, ranked
    being_studied: List[Clue]  # one per medicine, ranked
    left_out: Dict[str, int]  # group -> number of medicines. Counts only.


def find_clues(disease: Disease, targets: Iterable[Target]) -> Dict[str, List[Path]]:
    """Paths for every target, sorted into Kashish's groups.

    Every group is in the answer, even when empty. Only the groups in
    filter.SHOWN_GROUPS may be shown.
    """
    paths: List[Path] = []
    for target in targets:
        paths.extend(fetch_paths(disease, target))
    return sort_paths(paths)


def find_ranked_clues(disease: Disease, targets: Iterable[Target]) -> RankedClues:
    """The shown groups as ranked Clues, and the left-out groups as counts.

    A medicine that acts on two proteins is one Clue, and one in a count.
    No medicine from a left-out group is named in the answer.
    """
    tray = find_clues(disease, targets)
    left_out = {
        # A medicine that acts on two proteins is still one medicine.
        group: len({path.medicine.name for path in tray[group]})
        for group in GROUPS
        if group not in SHOWN_GROUPS
    }
    return RankedClues(
        new_clues=rank_clues(tray[NEW_CLUE]),
        being_studied=rank_clues(tray[BEING_STUDIED]),
        left_out=left_out,
    )
