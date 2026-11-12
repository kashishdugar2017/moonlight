"""Rank: put the clues in order using Kashish's rule. Plain code, no AI.

    1. Highest protein score first. Pieces of the same machine count once,
       using the strongest piece. Different machines add.
    2. If tied, more reports first. Reports are the number of sources,
       added across the medicine's paths.
    3. If still tied, alphabetical by medicine name, ignoring case.

A medicine appears once, as one Clue naming every protein it acts on.
fetch says which proteins are pieces of one machine (Path.same_machine_ids).
Nothing here fetches or filters. Being first on the list does not mean best.
"""

import math
from dataclasses import dataclass
from typing import Dict, Iterable, List, Tuple

from moonlight.records import Medicine, Path

RULE_TEXT = (
    "Ordered by how strongly the proteins are linked to the disease. "
    "Pieces of the same machine count once. "
    "If a medicine acts on different machines, the scores are added. "
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
    def machines(self) -> Tuple[Tuple[Path, ...], ...]:
        """The paths grouped into machines.

        Two paths are in the same machine when either one names the other's
        protein in same_machine_ids. Inside a machine, and from machine to
        machine, the strongest protein comes first.
        """
        groups: List[List[Path]] = []
        for path in self.paths:  # already strongest first
            linked = [
                group for group in groups
                if any(
                    path.target.id in other.same_machine_ids
                    or other.target.id in path.same_machine_ids
                    for other in group
                )
            ]
            joined = [p for group in linked for p in group] + [path]
            groups = [group for group in groups if not any(group is g for g in linked)]
            groups.append(joined)
        order = {id(path): place for place, path in enumerate(self.paths)}
        groups = [sorted(group, key=lambda p: order[id(p)]) for group in groups]
        groups.sort(key=lambda group: order[id(group[0])])
        return tuple(tuple(group) for group in groups)

    @property
    def total_score(self) -> float:
        """The strongest protein score in each machine, added across machines."""
        return math.fsum(max(p.score for p in machine) for machine in self.machines)

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
