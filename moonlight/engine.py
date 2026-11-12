"""The engine: join fetch and filter into one step.

Give it a disease and a list of targets. It fetches the paths for the
targets, up to AT_ONCE of them at the same time, and hands them all to the
sorting tray in filter.py. The paths are put back in the order the targets
were given, so the answer is the same as fetching one after another.
find_clues does not rank. find_ranked_clues then puts the shown groups in
Kashish's order using rank.py, and only counts the groups that are left out.

preload(disease_ids) fills the saved results for a list of diseases ahead
of time. From a terminal:

    python -m moonlight.engine MONDO_0015924 EFO_0000685
"""

import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional

from moonlight import fetch
from moonlight.fetch import fetch_disease, fetch_paths, fetch_targets
from moonlight.filter import BEING_STUDIED, GROUPS, NEW_CLUE, SHOWN_GROUPS, sort_paths
from moonlight.rank import Clue, rank_clues
from moonlight.records import Disease, Path, Target

AT_ONCE = 5  # the most proteins fetched at the same time
PRELOAD_TARGETS = 25  # the same number of proteins cli.py looks at


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
    for found in _fetch_all(disease, list(targets)):
        paths.extend(found)
    return sort_paths(paths)


def _fetch_all(disease: Disease, targets: List[Target]) -> List[List[Path]]:
    """fetch_paths for every target, AT_ONCE at a time, answers in target order.

    Like swimmers in five lanes. Each swimmer dives in only after the one
    before has dived in, so they always start in the order given. They swim
    at the same time, and the results are written down by lane number, not
    by who touched the wall first.
    """
    if not targets:
        return []
    # go[n] is set when target n may start. The first may start at once.
    go = [threading.Event() for _ in range(len(targets) + 1)]
    go[0].set()

    def one(number: int) -> List[Path]:
        go[number].wait()
        fetch.started(go[number + 1].set)  # the next starts when this one has begun
        try:
            return fetch_paths(disease, targets[number])
        finally:
            fetch.started(None)
            go[number + 1].set()  # also if it never asked, or went wrong

    with ThreadPoolExecutor(max_workers=AT_ONCE) as pool:
        waiting = [pool.submit(one, number) for number in range(len(targets))]
        try:
            return [answer.result() for answer in waiting]
        except BaseException:
            for answer in waiting:
                answer.cancel()  # do not start the ones still in the queue
            raise


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


def preload(disease_ids: Iterable[str], top_targets: int = PRELOAD_TARGETS) -> List[str]:
    """Fill the saved results for these disease ids. -> the ids that were loaded.

    For each disease it asks for the disease record, its top proteins and
    the medicines for each protein: the questions a search for that disease
    asks. An id Open Targets does not know is skipped. Explanations are not
    made here.
    """
    loaded = []
    for disease_id in disease_ids:
        disease = fetch_disease(disease_id)
        if disease is None:
            continue
        find_clues(disease, fetch_targets(disease, top_targets))
        loaded.append(disease.id)
    return loaded


def main(argv: Optional[List[str]] = None) -> int:
    wanted = sys.argv[1:] if argv is None else argv
    if not wanted:
        print("Give one or more disease ids, like: python -m moonlight.engine MONDO_0015924")
        return 2
    loaded = preload(wanted)
    for disease_id in wanted:
        print(f"{disease_id}: {'saved' if disease_id in loaded else 'not known to Open Targets'}")
    return 0 if len(loaded) == len(wanted) else 1


if __name__ == "__main__":
    sys.exit(main())
