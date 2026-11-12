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
