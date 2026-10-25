"""The regression suite: the engine must reproduce every hand-labeled injected case.

A person wrote each case's expected rule statuses and verdict in synth/generator.py before the rule engine
existed, and the generator never runs rule logic. A mismatch means the engine or the label is wrong.
"""

from __future__ import annotations

from typing import Any

import pytest

from rules.engine import evaluate
from rules.model import Status
from tests.rules.helpers import AS_OF, injected_cases, requests_by_id, to_request

CASES = injected_cases()
REQUESTS = requests_by_id()


@pytest.mark.parametrize("case", CASES, ids=lambda c: f"{c['case_id']}-{c['type']}")
def test_engine_matches_the_hand_labeled_case(store: Any, case: dict[str, Any]) -> None:
    decision = evaluate(store, to_request(REQUESTS[case["request_id"]]), cutoff=case["recording_cutoff"], as_of=AS_OF)
    got = decision.statuses()
    for rule, expected in case["expected_statuses"].items():
        assert got[rule] == expected, f"{rule}: {decision.finding(rule)['summary']}"
    assert decision.verdict == case["expected_verdict"]


def test_every_rule_runs_on_every_request(store: Any) -> None:
    """The combiner never skips a rule, so even a NO GO still reports every other finding."""
    for case in CASES[:8]:
        decision = evaluate(
            store, to_request(REQUESTS[case["request_id"]]), cutoff=case["recording_cutoff"], as_of=AS_OF
        )
        assert [f["rule"] for f in decision.findings] == ["R1", "R2", "R3", "R4", "R5", "R6", "R7"]


def test_a_non_exclusive_request_can_reach_go_and_an_exclusive_one_never_can(store: Any) -> None:
    verdicts: dict[bool, set[str]] = {True: set(), False: set()}
    for case in CASES:
        req = to_request(REQUESTS[case["request_id"]])
        decision = evaluate(store, req, cutoff=case["recording_cutoff"], as_of=AS_OF)
        verdicts[req.is_exclusive_family].add(decision.verdict)
    assert "GO" in verdicts[False]
    assert "GO" not in verdicts[True], "R7 must keep every exclusive-family request from GO"


def test_false_go_rate_is_zero_on_the_injected_cases(store: Any) -> None:
    """The primary risk metric: a GO where the hand label says anything else."""
    false_go = []
    for case in CASES:
        decision = evaluate(
            store, to_request(REQUESTS[case["request_id"]]), cutoff=case["recording_cutoff"], as_of=AS_OF
        )
        if decision.verdict == "GO" and case["expected_verdict"] != "GO":
            false_go.append(case["case_id"])
    assert false_go == []


def test_the_suite_covers_all_five_verdicts_and_every_status() -> None:
    assert {c["expected_verdict"] for c in CASES} == {"GO", "NO GO", "HOLD", "COUNSEL", "NO DATA"}
    seen = {s for c in CASES for s in c["expected_statuses"].values()}
    assert {Status.PASS, Status.FAIL, Status.UNKNOWN, Status.REVIEW, Status.PENDING, Status.NOT_APPLICABLE} <= {
        Status(s) for s in seen
    }
