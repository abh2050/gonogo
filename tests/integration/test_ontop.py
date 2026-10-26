"""Ontop applies the R2RML mapping over PostgreSQL, and the result matches the graph the build wrote.

The test starts a PostgreSQL container and the Ontop container, loads the tables from the graph, materializes
the mapping, and compares triples. It needs Docker and network access for the PostgreSQL JDBC driver.
"""

from __future__ import annotations

import subprocess
import urllib.request
from pathlib import Path

import pytest
from rdflib import RDF, Graph, Literal, URIRef
from rdflib.namespace import DCTERMS

from gonogo.paths import ROOT
from kg.ns import GNG, GRAPH_APPROVED, SCHEMA
from kg.store import Store
from mappings import tables

JDBC = "https://repo1.maven.org/maven2/org/postgresql/postgresql/42.7.4/postgresql-42.7.4.jar"
NET, PG = "gng-ontop-test", "gng-ontop-test-pg"
MAPPED = {
    DCTERMS.identifier,
    DCTERMS.title,
    GNG.caseNumber,
    GNG.patentNumber,
    GNG.applicationSerial,
    GNG.center,
    SCHEMA.legalName,
    GNG.countryCode,
    GNG.registeredAddress,
}


def docker(*args: str, input: str | None = None) -> str:
    out = subprocess.run(["docker", *args], input=input, capture_output=True, text=True, check=True)
    return out.stdout


@pytest.fixture(scope="module")
def materialized(store: Store, tmp_path_factory: pytest.TempPathFactory) -> Graph:
    work = tmp_path_factory.mktemp("ontop")
    jdbc = work / "jdbc"
    jdbc.mkdir()
    urllib.request.urlretrieve(JDBC, jdbc / "postgresql.jar")
    rows = tables.rows_from_graph(store)
    sql = [s + ";" for s in tables.ddl("postgres")] + [s + ";" for t, r in rows.items() for s in tables.inserts(t, r)]
    (work / "ontop.properties").write_text(
        f"jdbc.url=jdbc:postgresql://{PG}:5432/postgres\njdbc.driver=org.postgresql.Driver\njdbc.user=postgres\njdbc.password=pw\n"
    )
    subprocess.run(["docker", "rm", "-f", PG], capture_output=True)
    subprocess.run(["docker", "network", "create", NET], capture_output=True)
    try:
        docker("run", "-d", "--rm", "--name", PG, "--network", NET, "-e", "POSTGRES_PASSWORD=pw", "postgres:16-alpine")
        for _ in range(40):
            if (
                subprocess.run(["docker", "exec", PG, "pg_isready", "-U", "postgres"], capture_output=True).returncode
                == 0
            ):
                break
            subprocess.run(["sleep", "1"])
        docker("exec", "-i", PG, "psql", "-q", "-U", "postgres", "-v", "ON_ERROR_STOP=1", input="\n".join(sql) + "\n")
        docker(
            "run",
            "--rm",
            "--network",
            NET,
            "-v",
            f"{jdbc}:/opt/ontop/jdbc",
            "-v",
            f"{ROOT / 'mappings'}:/mappings:ro",
            "-v",
            f"{work}:/work",
            "ontop/ontop",
            "ontop",
            "materialize",
            "-m",
            "/mappings/gonogo.r2rml.ttl",
            "-p",
            "/work/ontop.properties",
            "-o",
            "/work/out",
            "-f",
            "turtle",
        )
        yield_graph = Graph().parse(work / "out.ttl")
    finally:
        subprocess.run(["docker", "rm", "-f", PG], capture_output=True)
        subprocess.run(["docker", "network", "rm", NET], capture_output=True)
    return yield_graph


def norm(t: tuple[object, object, object]) -> tuple[object, object, object]:
    s, p, o = t
    if isinstance(o, Literal) and o.datatype is not None and str(o.datatype).endswith("#string"):
        o = Literal(str(o))
    return s, p, o


@pytest.mark.docker
def test_ontop_reproduces_the_graphs_triples_for_every_column_it_maps(store: Store, materialized: Graph) -> None:
    graph = store.base[GRAPH_APPROVED]
    subjects = {s for s, _, _ in materialized if (s, RDF.type, None) in materialized}
    want = {
        norm((s, p, o))
        for s in subjects
        for p, o in graph.predicate_objects(s)
        if p in MAPPED or (p == RDF.type and o in (GNG.Patent, GNG.Licensee))
    }
    got = {norm(t) for t in materialized}
    assert got - want == set(), "Ontop produced a triple that the graph does not hold"
    missing = want - got
    # The one honest exception: a company named in two notices with two spellings of one address.
    for s, p, o in missing:
        assert p == GNG.registeredAddress, (s, p, o)
        assert len(set(graph.objects(s, p))) > 1, "a missing triple must belong to a multi-valued property"
    assert len(missing) <= 2


@pytest.mark.docker
def test_every_patent_and_licensee_row_became_a_node(materialized: Graph, store: Store) -> None:
    assert len(set(materialized.subjects(RDF.type, GNG.Patent))) == 300
    expected = len(tables.rows_from_graph(store)["licensee"])
    assert len(set(materialized.subjects(RDF.type, GNG.Licensee))) == expected


@pytest.mark.docker
def test_a_null_column_produces_no_triple(materialized: Graph, store: Store) -> None:
    rows = tables.rows_from_graph(store)["patent_master"]
    nulls = [r["patent_key"] for r in rows if r["patent_number"] is None]
    assert nulls
    for key in nulls[:20]:
        assert (URIRef(f"https://w3id.org/gonogo/id/patent/{key}"), GNG.patentNumber, None) not in materialized


def test_the_mapping_file_parses_and_covers_the_three_tables() -> None:
    mapping = Graph().parse(ROOT / "mappings" / "gonogo.r2rml.ttl")
    rr = "http://www.w3.org/ns/r2rml#"
    maps = list(mapping.subjects(RDF.type, URIRef(rr + "TriplesMap")))
    assert len(maps) == 4
    text = (ROOT / "mappings" / "gonogo.r2rml.ttl").read_text()
    for table in tables.TABLES:
        assert f'"{table}"' in text or f"FROM {table}" in text


@pytest.mark.docker
def test_a_finance_question_is_answered_as_sparql_over_the_verdict_table(store: Store, tmp_path: Path) -> None:
    """Count verdicts through Ontop, with no copy of the data, and compare with the same count in Python."""
    from collections import Counter

    from rules.book import load_book, to_request
    from rules.engine import evaluate
    from service import snowflake

    decisions = [
        evaluate(
            store,
            to_request(r),
            cutoff="2026-11-01T00:00:00Z",
            as_of="2026-11-01",
            user="pat",
            role="licensing_manager",
        ).to_dict()
        for r in load_book()
    ]
    rows = [snowflake.row_for(d) for d in decisions]
    expected = Counter(r["verdict"] for r in rows)
    jdbc = tmp_path / "jdbc"
    jdbc.mkdir()
    urllib.request.urlretrieve(JDBC, jdbc / "postgresql.jar")
    sql = [s + ";" for s in tables.ddl("postgres")] + [s + ";" for s in tables.inserts("verdict_log", rows)]
    (tmp_path / "ontop.properties").write_text(
        f"jdbc.url=jdbc:postgresql://{PG}:5432/postgres\njdbc.driver=org.postgresql.Driver\njdbc.user=postgres\njdbc.password=pw\n"
    )
    (tmp_path / "q.rq").write_text(
        "PREFIX gng: <https://w3id.org/gonogo/ontology#>\n"
        "SELECT ?verdict (COUNT(?d) AS ?n) WHERE { ?d a gng:Decision ; gng:verdict ?verdict . "
        "?d gng:decisionPatent ?p } GROUP BY ?verdict ORDER BY ?verdict\n"
    )
    subprocess.run(["docker", "rm", "-f", PG], capture_output=True)
    subprocess.run(["docker", "network", "create", NET], capture_output=True)
    try:
        docker("run", "-d", "--rm", "--name", PG, "--network", NET, "-e", "POSTGRES_PASSWORD=pw", "postgres:16-alpine")
        for _ in range(40):
            if (
                subprocess.run(["docker", "exec", PG, "pg_isready", "-U", "postgres"], capture_output=True).returncode
                == 0
            ):
                break
            subprocess.run(["sleep", "1"])
        docker("exec", "-i", PG, "psql", "-q", "-U", "postgres", "-v", "ON_ERROR_STOP=1", input="\n".join(sql) + "\n")
        docker(
            "run",
            "--rm",
            "--network",
            NET,
            "-v",
            f"{jdbc}:/opt/ontop/jdbc",
            "-v",
            f"{ROOT / 'mappings'}:/mappings:ro",
            "-v",
            f"{tmp_path}:/work",
            "ontop/ontop",
            "ontop",
            "query",
            "-m",
            "/mappings/gonogo.r2rml.ttl",
            "-p",
            "/work/ontop.properties",
            "-q",
            "/work/q.rq",
            "-o",
            "/work/answer.csv",
        )
    finally:
        subprocess.run(["docker", "rm", "-f", PG], capture_output=True)
        subprocess.run(["docker", "network", "rm", NET], capture_output=True)
    lines = (tmp_path / "answer.csv").read_text().strip().splitlines()[1:]
    got = {line.split(",")[0].strip('"'): int(line.split(",")[1].strip('"')) for line in lines}
    assert got == dict(expected), (got, dict(expected))
