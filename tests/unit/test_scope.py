from typing import Any

from ingest import scope


def patent(
    key: str, center: str, status: str = "Issued", pn: str | None = None, exp: str = "2030-01-01"
) -> dict[str, Any]:
    return {
        "patent_key": key,
        "case_number": key,
        "center": center,
        "status": status,
        "patent_number": pn,
        "application_sn": None,
        "patent_expiration_date": exp,
        "source": "nasa_patents",
        "title": key,
    }


def notice(doc: str, pns: list[str] | None = None, cases: list[str] | None = None) -> dict[str, Any]:
    return {
        "document_number": doc,
        "patent_numbers": pns or [],
        "application_sns": [],
        "case_numbers": cases or [],
    }


def test_match_by_patent_number_case_and_family() -> None:
    patents = [
        patent("LAR-11000-1", "L", pn="9000001"),
        patent("LAR-12000-2", "L"),
        patent("LEW-13000-1", "G"),
    ]
    notices = [
        notice("n1", pns=["9000001"]),
        notice("n2", cases=["LAR-12000-1"]),
        notice("n3", cases=["LEW-13000-1"]),
    ]
    m = scope.match(patents, notices)
    assert m["LAR-11000-1"] == [("n1", "patent_number")]
    assert m["LAR-12000-2"] == [("n2", "case_family")]
    assert m["LEW-13000-1"] == [("n3", "case_number")]


def test_select_keeps_matched_then_fills_in_force_first() -> None:
    patents = [
        patent("A-1", "L"),
        patent("A-2", "L", exp="2010-01-01"),
        patent("A-3", "L"),
        patent("B-1", "G"),
        patent("C-1", "K", status="Application"),
        patent("D-1", "X"),
    ]
    chosen = scope.select(patents, {"A-3": [("n", "case_number")]}, centers=["L", "G"], target=3)
    keys = [p["patent_key"] for p in chosen]
    assert "A-3" in keys and "D-1" not in keys and "C-1" not in keys
    assert "A-2" not in keys, "an expired patent should not fill scope before in-force patents"
