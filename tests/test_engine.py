"""Ticket 2.6. The engine joins fetch and filter.

Examples 1 and 2 from Kashish's answer key (docs/paper-graph-answer-key.jpg)
are tests here. They use the saved files only and never touch the network.
"""

from unittest.mock import patch

import pytest

from moonlight import engine, fetch
from moonlight.filter import GROUPS

# The saved-file stand-in for the network, shared with the fetch tests.
# Importing `offline` (an autouse fixture) switches it on for this file too.
from test_fetch import PAH, fake_post_json, offline  # noqa: F401

FIVE = ("BMPR2", "KCNK3", "ACVRL1", "EDNRA", "PDE5A")


def targets_named(*symbols):
    by_symbol = {t.symbol: t for t in fetch.fetch_targets(PAH)}
    return [by_symbol[symbol] for symbol in symbols]


def counts(tray):
    return {group: len(paths) for group, paths in tray.items()}


# Example 1
def test_five_proteins_together_give_16_2_6_12():
    tray = engine.find_clues(PAH, targets_named(*FIVE))
    assert counts(tray) == {
        "new_clue": 16,
        "being_studied": 2,
        "already_approved": 6,
        "not_approved": 12,
        "unclear_link": 0,
    }
    assert sum(counts(tray).values()) == 36


# Example 2
@pytest.mark.parametrize(
    "symbol, expected",
    [
        ("BMPR2", {"new_clue": 2}),
        ("KCNK3", {"new_clue": 6}),
        ("ACVRL1", {"not_approved": 2}),
        ("EDNRA", {"new_clue": 4, "already_approved": 4, "not_approved": 7}),
        ("PDE5A", {"new_clue": 4, "being_studied": 2, "already_approved": 2,
                   "not_approved": 3}),
    ],
)
def test_counts_by_protein(symbol, expected):
    tray = engine.find_clues(PAH, targets_named(symbol))
    everything = {group: 0 for group in GROUPS}
    everything.update(expected)
    assert counts(tray) == everything


def test_every_group_is_there_even_with_no_targets():
    assert engine.find_clues(PAH, []) == {group: [] for group in GROUPS}


def test_paths_keep_the_order_they_were_fetched_in():
    targets = targets_named("PDE5A", "BMPR2", "KCNK3")  # not score order
    fetched = [p for t in targets for p in fetch.fetch_paths(PAH, t)]
    tray = engine.find_clues(PAH, targets)
    for group, paths in tray.items():
        assert paths == [p for p in fetched if p in paths], group
    # PDE5A was handed in first, so its new clues come before BMPR2's.
    symbols = [p.target.symbol for p in tray["new_clue"]]
    assert symbols == ["PDE5A"] * 4 + ["BMPR2"] * 2 + ["KCNK3"] * 6


def test_each_target_is_fetched_once_with_the_disease():
    targets = targets_named(*FIVE)
    with patch("moonlight.engine.fetch_paths", wraps=fetch.fetch_paths) as spy:
        engine.find_clues(PAH, targets)
    assert [call.args for call in spy.call_args_list] == [(PAH, t) for t in targets]


# ---- Ticket 2.7. The engine hands back the clues in Kashish's ranked order ----

from moonlight.rank import Clue, rank_clues  # noqa: E402
from moonlight.records import Medicine, MedicineForm, Path, Target  # noqa: E402

NEW_ORDER = [
    "DIBOTERMIN ALFA", "EPTOTERMIN ALFA", "SEVOFLURANE", "DESFLURANE",
    "ISOFLURANE", "DOXAPRAM", "ENFLURANE", "HALOTHANE", "ATRASENTAN",
    "SPARSENTAN", "APROCITENTAN", "CLAZOSENTAN", "PENTOXIFYLLINE",
    "DIPYRIDAMOLE", "AVANAFIL", "IBUDILAST",
]


def names(clues):
    return [clue.medicine.name.upper() for clue in clues]


# Example 1
def test_ranked_new_clues_come_in_kashishs_order():
    ranked = engine.find_ranked_clues(PAH, targets_named(*FIVE))
    assert all(isinstance(clue, Clue) for clue in ranked.new_clues)
    assert names(ranked.new_clues) == NEW_ORDER


# Example 2
def test_ranked_being_studied_is_udenafil_then_vardenafil():
    ranked = engine.find_ranked_clues(PAH, targets_named(*FIVE))
    assert all(isinstance(clue, Clue) for clue in ranked.being_studied)
    assert names(ranked.being_studied) == ["UDENAFIL", "VARDENAFIL"]


def test_ranked_order_does_not_depend_on_the_order_of_the_targets():
    forwards = engine.find_ranked_clues(PAH, targets_named(*FIVE))
    backwards = engine.find_ranked_clues(PAH, targets_named(*reversed(FIVE)))
    assert names(backwards.new_clues) == names(forwards.new_clues) == NEW_ORDER
    assert names(backwards.being_studied) == names(forwards.being_studied)


def test_ranked_clues_are_what_rank_clues_makes_of_the_tray():
    targets = targets_named(*FIVE)
    tray = engine.find_clues(PAH, targets)
    ranked = engine.find_ranked_clues(PAH, targets)
    assert ranked.new_clues == rank_clues(tray["new_clue"])
    assert ranked.being_studied == rank_clues(tray["being_studied"])


def test_left_out_counts_are_by_group_and_name_no_medicine():
    ranked = engine.find_ranked_clues(PAH, targets_named(*FIVE))
    assert ranked.left_out == {
        "not_approved": 12,
        "already_approved": 6,
        "unclear_link": 0,
    }


def test_ranked_with_no_targets_is_empty_but_complete():
    ranked = engine.find_ranked_clues(PAH, [])
    assert ranked.new_clues == []
    assert ranked.being_studied == []
    assert ranked.left_out == {
        "not_approved": 0, "already_approved": 0, "unclear_link": 0,
    }


def made_up_paths(disease, target):
    """Stands in for fetch_paths: one made-up medicine acting on any protein,
    and one made-up medicine that is not approved anywhere."""
    def one(name, stage):
        form = MedicineForm(id="ID_" + name.upper(), name=name, best_stage=stage)
        return Path(
            medicine=Medicine(name=name, forms=(form,)),
            target=target,
            disease=disease,
            action_types=("INHIBITOR",),
            score=target.score,
            sources=(f"https://example.org/{name}/{target.symbol}",),
        )
    return [one("MADEUPINE", "APPROVAL"), one("NOTYETINE", "PHASE_2")]


# Example 4
def test_a_medicine_on_two_proteins_is_one_clue_with_the_scores_added():
    weak = Target(id="ENSG_AAA", symbol="AAA", name="AAA", score=0.5)
    strong = Target(id="ENSG_BBB", symbol="BBB", name="BBB", score=0.9)
    with patch("moonlight.engine.fetch_paths", side_effect=made_up_paths):
        ranked = engine.find_ranked_clues(PAH, [weak, strong])
    (clue,) = ranked.new_clues
    assert clue.medicine.name == "MADEUPINE"
    assert [p.target.symbol for p in clue.paths] == ["BBB", "AAA"]
    assert clue.total_score == pytest.approx(1.4)
    assert clue.reports == 2
    # Left out on two proteins, but still one medicine.
    assert ranked.left_out["not_approved"] == 1


# ---- Ticket 6.1. Several proteins are fetched at the same time ----

import threading  # noqa: E402
import time  # noqa: E402

from moonlight.filter import sort_paths  # noqa: E402


class SlowOpenTargets:
    """fake_post_json, made slow, counting how many calls run at once."""

    def __init__(self, seconds_for):
        self.seconds_for = seconds_for  # target id -> seconds to wait
        self.lock = threading.Lock()
        self.running = 0
        self.most_at_once = 0
        self.finished = []  # target ids, in the order their answers came back

    def __call__(self, body):
        target_id = body["variables"]["targetId"]
        with self.lock:
            self.running += 1
            self.most_at_once = max(self.most_at_once, self.running)
        try:
            time.sleep(self.seconds_for(target_id))
            return fake_post_json(body)
        finally:
            with self.lock:
                self.running -= 1
                self.finished.append(target_id)


# Example 3
def test_parallel_gives_the_same_clues_in_the_same_order_as_one_at_a_time(offline):
    targets = targets_named(*FIVE)
    one_at_a_time = sort_paths([p for t in targets for p in fetch.fetch_paths(PAH, t)])

    # The first protein answers slowest and the last one fastest, so the
    # answers come back in the opposite order to the one they were asked in.
    wait = {t.id: 0.05 * (len(targets) - n) for n, t in enumerate(targets)}
    slow = SlowOpenTargets(wait.get)
    offline.side_effect = slow
    together = engine.find_clues(PAH, targets)

    assert slow.finished == [t.id for t in reversed(targets)]
    assert slow.most_at_once == 5  # they really did run at the same time
    assert together == one_at_a_time
    for group in GROUPS:  # same clues, same order, written out plainly
        assert [(p.medicine.name, p.target.symbol) for p in together[group]] == \
               [(p.medicine.name, p.target.symbol) for p in one_at_a_time[group]]


def test_parallel_ranked_clues_are_the_same_as_one_at_a_time(offline):
    targets = targets_named(*FIVE)
    tray = sort_paths([p for t in targets for p in fetch.fetch_paths(PAH, t)])
    offline.side_effect = SlowOpenTargets(lambda target_id: 0.01)
    ranked = engine.find_ranked_clues(PAH, targets)
    assert ranked.new_clues == rank_clues(tray["new_clue"])
    assert ranked.being_studied == rank_clues(tray["being_studied"])


def test_at_most_5_proteins_are_fetched_at_once(offline):
    targets = fetch.fetch_targets(PAH)[:10]  # the ten with saved files
    slow = SlowOpenTargets(lambda target_id: 0.03)
    offline.side_effect = slow
    engine.find_clues(PAH, targets)
    assert engine.AT_ONCE == 5
    assert slow.most_at_once == 5


def test_parallel_calls_start_in_the_order_the_targets_were_given():
    targets = targets_named(*FIVE) * 4
    for _ in range(20):
        with patch("moonlight.engine.fetch_paths", wraps=fetch.fetch_paths) as spy:
            engine.find_clues(PAH, targets)
        assert [call.args for call in spy.call_args_list] == [(PAH, t) for t in targets]


def test_a_problem_with_one_protein_is_still_raised(offline):
    targets = targets_named(*FIVE)

    def broken(body):
        if body["variables"]["targetId"] == targets[2].id:
            return {"errors": [{"message": "boom"}]}
        return fake_post_json(body)

    offline.side_effect = broken
    with pytest.raises(fetch.FetchError):
        engine.find_clues(PAH, targets)
