"""The cases that define who may do what: one table for the grid in the UI, the tests, and the AWS equivalence check."""

from __future__ import annotations

from typing import Any

from authz import cedar

CLEAN = {"proposer": "feed", "firstApprover": "", "conflict": False, "upgradesToGo": False}
FLAGGED = CLEAN | {"conflict": True}
SECOND = CLEAN | {"firstApprover": "someone else", "conflict": True}
RELEASE = {"proposer": "someone else", "gatePassed": True, "counselApproved": True}

# (label, action, resource, context). Every action in the schema appears at least once.
CASES: list[tuple[str, str, tuple[str, str], dict[str, Any] | None]] = [
    ("Ask a clearance question", "AskClearance", ("Request", "r"), None),
    ("Read a decision", "ViewDecision", ("Decision", "d"), None),
    ("Rerun a decision", "RerunDecision", ("Decision", "d"), None),
    ("Read the release graph", "ReadGraph", ("Graph", "release"), None),
    ("Read the approved graph", "ReadGraph", ("Graph", "approved"), None),
    ("Read the candidate graph", "ReadGraph", ("Graph", "candidate"), None),
    ("Read the royalty graph", "ReadGraph", ("Graph", "royalty"), None),
    ("Read royalty terms in Snowflake", "ReadRoyaltyTable", ("Decision", "d"), None),
    ("Propose a fact", "ProposeFact", ("Candidate", "c"), None),
    ("Approve a clean fact", "ApproveFact", ("Candidate", "c"), CLEAN),
    ("Approve a conflicting fact alone", "ApproveFact", ("Candidate", "c"), FLAGGED),
    ("Submit a flagged approval", "SubmitForSecondReview", ("Candidate", "c"), FLAGGED),
    ("Second review", "SecondReview", ("Candidate", "c"), SECOND),
    ("Reject a fact", "RejectFact", ("Candidate", "c"), None),
    ("Reject a link", "RejectLink", ("IdentityPair", "p"), None),
    ("Link two companies", "LinkIdentity", ("IdentityPair", "p"), CLEAN),
    ("Override a verdict", "OverrideVerdict", ("Decision", "d"), None),
    ("Read release history", "ReadReleaseHistory", ("Release", "r"), None),
    ("Propose a release", "ProposeRelease", ("Release", "r"), None),
    ("Approve an impact report", "ApproveImpactReport", ("Release", "r"), RELEASE),
    ("Publish a release", "PublishRelease", ("Release", "r"), RELEASE),
]


def evaluate(name: str = "pat") -> list[dict[str, Any]]:
    """Each case with the answer for every role, from the local Cedar engine."""
    return [
        {
            "label": label,
            "action": action,
            "allowed": {
                role: cedar.authorize(cedar.Principal(name, role), action, res, ctx).allowed for role in cedar.ROLES
            },
        }
        for label, action, res, ctx in CASES
    ]
