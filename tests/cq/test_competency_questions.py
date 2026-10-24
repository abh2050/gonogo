"""Run every competency question against the sample world, on rdflib and on Fuseki.

Each CQ has a SPARQL template (NN_name.rq) and a file of hand-worked cases (NN_name.expected.json).
The sample world lives in tests/cq/data/. The release graph is the real ontology and schemes, so a
change to the hierarchy that alters an answer fails here.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from rdflib import Graph

from kg import build, materialize
from kg.ns import GRAPH_APPROVED, GRAPH_RELEASE
from kg.templates import TemplateError, render
from tests.cq.engines import FusekiEngine, RdflibEngine

HERE = Path(__file__).parent
PREFIXES = {
    "ex:": "https://example.org/cq/",
    "gng:": "https://w3id.org/gonogo/ontology#",
    "policy:": "https://w3id.org/gonogo/policy/",
}
ALLOWLIST = [GRAPH_APPROVED, GRAPH_RELEASE]


def expand(cell: str | None) -> str | None:
    if cell is None or not (cell.startswith("<") and cell.endswith(">")):
        return cell
    inner = cell[1:-1]
    for prefix, base in PREFIXES.items():
        if inner.startswith(prefix):
            return f"<{base}{inner[len(prefix) :]}>"
    return cell


def all_cases() -> list[Any]:
    params = []
    for expected_file in sorted(HERE.glob("*.expected.json")):
        spec = json.loads(expected_file.read_text())
        template = expected_file.with_name(expected_file.name.replace(".expected.json", ".rq"))
        for i, case in enumerate(spec["cases"]):
            params.append(pytest.param(template, case, id=f"{spec['id']}-{i + 1}"))
    return params


@pytest.fixture(scope="module")
def sample_graphs() -> dict[str, Graph]:
    release = build.Builder()
    release.build_release()
    approved = Graph().parse(HERE / "data" / "sample-approved.ttl")
    graphs = {GRAPH_RELEASE: release.release, GRAPH_APPROVED: approved}
    materialize.apply(graphs)
    return graphs


@pytest.fixture(scope="module")
def rdflib_engine(sample_graphs: dict[str, Graph]) -> RdflibEngine:
    return RdflibEngine(sample_graphs)


@pytest.fixture(scope="module")
def fuseki_engine(sample_graphs: dict[str, Graph]) -> Iterator[FusekiEngine]:
    engine = FusekiEngine(sample_graphs)
    yield engine
    engine.close()


def check(engine: Any, template: Path, case: dict[str, Any]) -> None:
    query = render(template.read_text(), case["params"], ALLOWLIST)
    variables, rows = engine.select(query)
    assert variables == case["vars"]
    expected = sorted((tuple(expand(c) for c in row) for row in case["rows"]), key=repr)
    assert sorted(rows, key=repr) == expected, case["name"]


@pytest.mark.parametrize(("template", "case"), all_cases())
def test_cq_on_rdflib(rdflib_engine: RdflibEngine, template: Path, case: dict[str, Any]) -> None:
    check(rdflib_engine, template, case)


@pytest.mark.docker
@pytest.mark.parametrize(("template", "case"), all_cases())
def test_cq_on_fuseki(fuseki_engine: FusekiEngine, template: Path, case: dict[str, Any]) -> None:
    check(fuseki_engine, template, case)


def test_there_are_fifteen_questions() -> None:
    files = sorted(HERE.glob("[0-9][0-9]_*.rq"))
    assert len(files) == 15
    for rq in files:
        assert rq.with_name(rq.name.replace(".rq", ".expected.json")).exists()
        assert "{{FROM}}" in rq.read_text() or rq.name.startswith("14")


def test_every_template_names_its_graphs() -> None:
    for rq in HERE.glob("[0-9][0-9]_*.rq"):
        assert "{{FROM}}" in rq.read_text(), f"{rq.name} could read every named graph"


def test_a_template_without_from_is_rejected() -> None:
    with pytest.raises(TemplateError, match="FROM"):
        render("SELECT * WHERE { ?s ?p ?o }", {}, ALLOWLIST)


def test_an_empty_allowlist_is_rejected() -> None:
    with pytest.raises(TemplateError, match="allowlist"):
        render("SELECT * {{FROM}} WHERE { ?s ?p ?o }", {}, [])


@pytest.mark.parametrize(
    "bad",
    [
        {"iri": "http://x/> ; DROP"},
        {"date": "tomorrow"},
        {"datetime": "2026-11-01"},
        {"int": "1; DROP"},
        {"iri": "a", "date": "2026-01-01"},
        {"float": "1.5"},
    ],
)
def test_unsafe_parameters_are_rejected(bad: dict[str, str]) -> None:
    with pytest.raises(TemplateError):
        render("SELECT * {{FROM}} WHERE { ?s ?p {{x}} }", {"x": bad}, ALLOWLIST)


def test_the_asof_filter_needs_a_cutoff() -> None:
    with pytest.raises(TemplateError, match="cutoff"):
        render("SELECT * {{FROM}} WHERE { ?f a gng:Grant . {{ASOF ?f}} }", {}, ALLOWLIST)
