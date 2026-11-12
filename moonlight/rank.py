"""Rank: put the clues in order using Kashish's rule. Plain code, no AI.

    1. Highest protein score first. If a medicine acts on more than one of
       the disease's proteins, their scores are added.
    2. If tied, more reports first. Reports are the number of sources,
       added across the medicine's paths.
    3. If still tied, alphabetical by medicine name, ignoring case.

A medicine appears once, as one Clue naming every protein it acts on.
Nothing here fetches or filters. Being first on the list does not mean best.
"""

import math
from dataclasses import dataclass
from typing import Dict, Iterable, List, Tuple

from moonlight.records import Medicine, Path

RULE_TEXT = (
    "Ordered by how strongly the proteins are linked to the disease. "
    "If a medicine acts on more than one protein, the scores are added. "
    "Ties: more reports first, then alphabetical. "
    "Being first on the list does not mean best."
)


def _family_id(medicine: Medicine) -> str:
    """The id shared by a medicine and its tablet forms.

    fetch puts the parent first when it has a row of its own. Otherwise the
    first form is a tablet form and points at the parent.
    """
    first = medicine.forms[0]
    return first.parent_id or first.id


@dataclass(frozen=True)
class Clue:
    """One medicine with all its paths, strongest protein first."""

    paths: Tuple[Path, ...]

    def __post_init__(self):
        if not self.paths:
            raise ValueError("A Clue needs at least one path.")
        # Strongest protein first. Equal scores go by protein symbol, so the
        # order never depends on the order the paths arrived in.
        ordered = sorted(self.paths, key=lambda p: (-p.score, p.target.symbol, p.target.id))
        object.__setattr__(self, "paths", tuple(ordered))

        families = {_family_id(p.medicine) for p in ordered}
        if len(families) != 1:
            raise ValueError("All paths in a Clue must share one medicine.")
        proteins = [p.target.id for p in ordered]
        if len(set(proteins)) != len(proteins):
            # Adding the same protein's score twice would be wrong.
            raise ValueError(
                f"{self.medicine.name} has two paths through the same protein."
            )

    @property
    def medicine(self) -> Medicine:
        return self.paths[0].medicine

    @property
    def total_score(self) -> float:
        """The protein scores of all the paths, added."""
        return math.fsum(p.score for p in self.paths)

    @property
    def reports(self) -> int:
        """The number of sources, added across the paths."""
        return sum(len(p.sources) for p in self.paths)


def _sort_key(clue: Clue):
    name = clue.medicine.name
    return (
        -clue.total_score,  # rule 1: highest score first
        -clue.reports,  # rule 2: more reports first
        name.casefold(),  # rule 3: alphabetical, ignoring case
        name,  # the last two only make the order
        _family_id(clue.medicine),  # the same every time
    )


def rank_clues(paths: Iterable[Path]) -> List[Clue]:
    """Join paths that share a medicine into one Clue, then order the clues."""
    by_family: Dict[str, List[Path]] = {}
    for path in paths:
        by_family.setdefault(_family_id(path.medicine), []).append(path)
    clues = [Clue(paths=tuple(group)) for group in by_family.values()]
    return sorted(clues, key=_sort_key)
