import pytest

from ingest import normalize


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("9,297,368", "9297368"),
        ("US 9297368 B2", "9297368"),
        ("0", None),
        ("", None),
        (None, None),
        ("RE40,000", "RE40000"),
    ],
)
def test_patent_number(raw: str | None, expected: str | None) -> None:
    assert normalize.patent_number(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("13/033,085", "13033085"), ("17/ 119,632", "17119632"), ("62/616,479", "62616479"), ("0", None)],
)
def test_application_serial(raw: str, expected: str | None) -> None:
    assert normalize.application_serial(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected", "root"),
    [
        ("ARC-14231-2DIV", "ARC-14231-2DIV", "ARC-14231"),
        ("LEW- 20196-1", "LEW-20196-1", "LEW-20196"),
        ("KSC-12871", "KSC-12871", "KSC-12871"),
        ("NASA Case No. LAR-19046-1.", "LAR-19046-1", "LAR-19046"),
        ("LAR-TOPS-116", None, None),
    ],
)
def test_case_number(raw: str, expected: str | None, root: str | None) -> None:
    assert normalize.case_number(raw) == expected
    assert normalize.case_root(raw) == root
