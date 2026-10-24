"""USPTO summary logic, checked against hand-built records shaped like real Open Data Portal responses."""

from pathlib import Path
from typing import Any

import httpx
import respx

from ingest import uspto
from ingest.common import Fetcher


def wrapper(
    events: list[tuple[str, str]],
    status: str = "Patented Case",
    grant: str | None = "2011-12-13",
    assignees: list[str] | None = None,
    pta: int = 0,
) -> dict[str, Any]:
    return {
        "applicationNumberText": "11774574",
        "applicationMetaData": {
            "applicationStatusDescriptionText": status,
            "applicationStatusDate": "2020-01-20",
            "filingDate": "2007-07-07",
            "grantDate": grant,
            "patentNumber": "8077103",
        },
        "patentTermAdjustmentData": {"adjustmentTotalQuantity": pta},
        "eventDataBag": [{"eventCode": c, "eventDate": d, "eventDescriptionText": c} for c, d in events],
        "assignmentBag": [{"assigneeBag": [{"assigneeNameText": n} for n in (assignees or [])]}],
    }


def test_maintenance_fee_lapse_is_lapsed() -> None:
    rec = uspto.summarize(
        wrapper(
            [("REM.", "2019-08-05"), ("EXP.", "2020-01-20")],
            status="Patent Expired Due to NonPayment of Maintenance Fees Under 37 CFR 1.362",
        ),
        None,
    )
    assert rec["legal_state"] == "lapsed" and not rec["reinstated"]


def test_accepted_late_payment_reinstates() -> None:
    rec = uspto.summarize(wrapper([("EXP.", "2024-06-24"), ("PMFG", "2025-05-21")]), None)
    assert rec["legal_state"] == "in_force"
    assert rec["reinstated"] and rec["lapse_period"] == ["2024-06-24", "2025-05-21"]


def test_term_uses_pta_and_earliest_non_provisional_parent() -> None:
    cont = {
        "patentFileWrapperDataBag": [
            {
                "parentContinuityBag": [
                    {
                        "parentApplicationFilingDate": "2005-01-10",
                        "claimParentageTypeCodeDescriptionText": "is a Division of",
                    },
                    {
                        "parentApplicationFilingDate": "2004-01-10",
                        "claimParentageTypeCodeDescriptionText": "Claims Priority from Provisional Application",
                    },
                ]
            }
        ]
    }
    rec = uspto.summarize(wrapper([], pta=100), cont)
    assert rec["earliest_parent_filing_date"] == "2005-01-10"
    assert rec["expiration_computed"] == "2025-04-20"  # 2025-01-10 + 100 days
    assert rec["legal_state"] == "term_ended"


def test_pre_1995_filing_uses_longer_of_two_terms() -> None:
    assert uspto.term_expiration("1990-03-01", None, "1996-05-01", 0) == (
        "2013-05-01",
        "pre-1995 filing: later of filing + 20 years and grant + 17 years",
    )


def test_not_granted_and_co_assignees() -> None:
    rec = uspto.summarize(
        wrapper(
            [],
            status="Abandoned -- Failure to Respond",
            grant=None,
            assignees=[
                "NASA",
                "UNITED STATES OF AMERICA AS REPRESENTED BY THE ADMINISTRATOR OF NASA",
                "PURDUE RESEARCH FOUNDATION",
            ],
        ),
        None,
    )
    assert rec["legal_state"] == "abandoned"
    assert rec["co_assignees"] == ["PURDUE RESEARCH FOUNDATION"]


@respx.mock
def test_api_key_header_is_sent_but_never_cached(tmp_path: Path) -> None:
    route = respx.get("https://api.example.test/x").mock(return_value=httpx.Response(200, json={"ok": True}))
    Fetcher("demo", raw_root=tmp_path, headers={"X-API-KEY": "secret-value"}).fetch("https://api.example.test/x")
    assert route.calls[0].request.headers["X-API-KEY"] == "secret-value"
    assert all("secret-value" not in p.read_text() for p in (tmp_path / "demo").iterdir())
