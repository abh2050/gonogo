"""The combiner applies the versioned precedence policy and nothing else."""

from __future__ import annotations

import itertools

import pytest
import yaml

from gonogo.paths import ROOT
from rules.model import Status
from rules.policy import combine, load_policy, policy_version

ALL = list(Status)


def oracle(statuses: set[Status]) -> str:
    """The GoNoGo spec, written out as plain conditions, independent of the YAML file."""
    if Status.FAIL in statuses:
        return "NO GO"
    if Status.PENDING in statuses:
        return "HOLD"
    if Status.REVIEW in statuses:
        return "COUNSEL"
    if Status.UNKNOWN in statuses:
        return "NO DATA"
    return "GO"


@pytest.mark.parametrize("size", [1, 2, 3])
def test_policy_matches_the_spec_for_every_combination(size: int) -> None:
    for combo in itertools.combinations_with_replacement(ALL, size):
        assert combine(combo) == oracle(set(combo)), combo


def test_all_seven_rules_with_any_mix_follow_the_same_precedence() -> None:
    for combo in itertools.product([Status.PASS, Status.NOT_APPLICABLE, Status.UNKNOWN, Status.FAIL], repeat=4):
        assert combine(combo + (Status.PASS,) * 3) == oracle(set(combo) | {Status.PASS})


def test_not_applicable_takes_no_part() -> None:
    assert combine([Status.NOT_APPLICABLE] * 7) == "GO"
    assert combine([Status.PASS, Status.NOT_APPLICABLE, Status.UNKNOWN]) == "NO DATA"


def test_the_policy_is_versioned_and_changing_it_changes_verdicts() -> None:
    assert policy_version() == "1.0.0"
    flipped = yaml.safe_load((ROOT / "config" / "precedence.yaml").read_text())
    flipped["precedence"][0], flipped["precedence"][1] = flipped["precedence"][1], flipped["precedence"][0]
    # With PENDING above FAIL, a request with both would read HOLD. The default policy says NO GO.
    assert combine([Status.FAIL, Status.PENDING], flipped) == "HOLD"
    assert combine([Status.FAIL, Status.PENDING], load_policy()) == "NO GO"


def test_the_policy_names_every_verdict_once() -> None:
    verdicts = [e["verdict"] for e in load_policy()["precedence"]] + [load_policy()["default_verdict"]]
    assert sorted(verdicts) == sorted(["NO GO", "HOLD", "COUNSEL", "NO DATA", "GO"])
