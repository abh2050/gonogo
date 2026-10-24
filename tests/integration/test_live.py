"""Live checks. Run with: uv run pytest -m network / -m docker / -m aws"""

import httpx
import pytest

from gonogo import aws


@pytest.mark.network
@pytest.mark.parametrize(
    ("method", "url", "body"),
    [
        ("GET", "https://data.nasa.gov/docs/legacy/NASA_Patents/NASA_Patents_rows.csv", None),
        (
            "GET",
            "https://www.federalregister.gov/api/v1/documents.json?conditions[agencies][]="
            "national-aeronautics-and-space-administration&per_page=1",
            None,
        ),
        ("GET", "https://technology.nasa.gov/api/api/patent/LEW", None),
        (
            "POST",
            "https://ntrs.nasa.gov/api/citations/search",
            {"q": "shape memory alloy", "page": {"size": 1}},
        ),
    ],
)
def test_source_is_reachable(method: str, url: str, body: dict[str, object] | None) -> None:
    r = httpx.request(method, url, json=body, timeout=60, follow_redirects=True)
    assert r.status_code == 200


@pytest.mark.network
def test_t2_spec_endpoint_still_missing() -> None:
    """docs/data-sources.md records that the spec's T2 endpoint returns 404."""
    r = httpx.get("https://technology.nasa.gov/api/1.0/patent/search/LEW", timeout=60)
    assert r.status_code == 404


@pytest.mark.docker
def test_fuseki_insert_and_select() -> None:
    assert httpx.get("http://localhost:3030/$/ping", timeout=10).status_code == 200
    update = "INSERT DATA { <urn:gonogo:test> <urn:gonogo:p> 'ok' }"
    r = httpx.post(
        "http://localhost:3030/gonogo/update",
        data={"update": update},
        auth=("admin", "gonogo-local"),
        timeout=10,
    )
    assert r.status_code in (200, 204)
    q = "SELECT ?o WHERE { <urn:gonogo:test> <urn:gonogo:p> ?o }"
    r = httpx.get(
        "http://localhost:3030/gonogo/query",
        params={"query": q},
        headers={"Accept": "application/sparql-results+json"},
        timeout=10,
    )
    assert [b["o"]["value"] for b in r.json()["results"]["bindings"]] == ["ok"]
    httpx.post(
        "http://localhost:3030/gonogo/update",
        data={"update": update.replace("INSERT", "DELETE")},
        auth=("admin", "gonogo-local"),
        timeout=10,
    )


@pytest.mark.docker
def test_neo4j_bolt() -> None:
    from neo4j import GraphDatabase

    with GraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", "gonogo-local")) as driver:
        records, _, _ = driver.execute_query("RETURN 1 AS ok")
    assert records[0]["ok"] == 1


@pytest.mark.aws
def test_aws_preflight_is_read_only_and_finds_claude() -> None:
    s = aws.session()
    assert s.region_name == "us-east-2"
    assert s.client("sts").get_caller_identity()["Account"]
    assert aws.claude_profile().split(".", 1)[0] in {"us", "global"}


@pytest.mark.network
def test_uspto_open_data_portal_reports_the_known_lapse() -> None:
    """US 8,077,103 lapsed for unpaid maintenance fees on 2020-01-20 (status date)."""
    from gonogo import env

    key = env.get("USPTO_API_KEY")
    if not key:
        pytest.skip("USPTO_API_KEY is not set")
    r = httpx.get("https://api.uspto.gov/api/v1/patent/applications/11774574", headers={"X-API-KEY": key}, timeout=60)
    assert r.status_code == 200
    meta = r.json()["patentFileWrapperDataBag"][0]["applicationMetaData"]
    assert "Maintenance Fees" in meta["applicationStatusDescriptionText"]
