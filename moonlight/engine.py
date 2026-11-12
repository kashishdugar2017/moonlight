"""The engine: join fetch and filter into one step.

Give it a disease and a list of targets. It fetches the paths for each
target, one after another, and hands them all to the sorting tray in
filter.py. Nothing here ranks: paths stay in the order they were fetched.
"""

from typing import Dict, Iterable, List

from moonlight.fetch import fetch_paths
from moonlight.filter import sort_paths
from moonlight.records import Disease, Path, Target


def find_clues(disease: Disease, targets: Iterable[Target]) -> Dict[str, List[Path]]:
    """Paths for every target, sorted into Kashish's groups.

    Every group is in the answer, even when empty. Only the groups in
    filter.SHOWN_GROUPS may be shown.
    """
    paths: List[Path] = []
    for target in targets:
        paths.extend(fetch_paths(disease, target))
    return sort_paths(paths)
