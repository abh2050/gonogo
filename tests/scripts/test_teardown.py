"""The teardown script's own logic, with fake AWS clients. Its first real run failed on exactly the case tested here."""

from __future__ import annotations

from typing import Any

import pytest

from scripts import teardown


class FakeError(Exception):
    pass


class FakeS3:
    class exceptions:  # noqa: N801
        ClientError = FakeError
        NoSuchBucket = type("NoSuchBucket", (FakeError,), {})

    def __init__(self, locked: bool) -> None:
        self.locked, self.deleted = locked, []

    def get_object_lock_configuration(self, Bucket: str) -> dict[str, Any]:  # noqa: N803
        if not self.locked:
            raise FakeError("ObjectLockConfigurationNotFoundError")
        return {"ObjectLockConfiguration": {"ObjectLockEnabled": "Enabled"}}

    def get_paginator(self, name: str) -> Any:
        page = {
            "Versions": [{"Key": "a", "VersionId": "1"}, {"Key": "b", "VersionId": "2"}],
            "DeleteMarkers": [{"Key": "c", "VersionId": "3"}],
        }
        return type("P", (), {"paginate": lambda self, Bucket: [page]})()

    def delete_objects(self, **kw: Any) -> None:
        if kw.get("BypassGovernanceRetention") and not self.locked:
            raise FakeError("x-amz-bypass-governance-retention is only applicable to Object Lock enabled buckets.")
        self.deleted.append(kw)


@pytest.mark.parametrize("locked", [True, False])
def test_a_bucket_is_emptied_and_the_bypass_is_sent_only_where_object_lock_is_on(locked: bool) -> None:
    s3 = FakeS3(locked)
    assert teardown.empty_bucket({"s3": s3}, "b") == 3
    assert ("BypassGovernanceRetention" in s3.deleted[0]) is locked


def test_a_teardown_that_leaves_something_billing_is_a_failure() -> None:
    left = [{"resource": "AWS::Neptune::DBCluster gonogo-x", "why": "bills while idle"}]
    billing = [x for x in left if any(w in x["why"] for w in ("bills", "storage cost", "a key bills"))]
    assert billing, "Neptune is the resource this guard exists for"


def test_the_budget_and_a_pending_key_are_not_counted_as_billing() -> None:
    kept = teardown.KEPT_ON_PURPOSE["AWS::Budgets::Budget gonogo-monthly"]
    pending = "pending deletion until 2026-11-01, the shortest wait KMS allows; not billed"
    for why in (kept, pending):
        assert not any(w in why for w in ("bills", "storage cost", "a key bills")), why
