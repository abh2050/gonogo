"""The leakage suite: every role attacks the query service, and nothing from a graph it may not read comes back.

The suite attacks through the default graph, FROM, GRAPH, SERVICE, DESCRIBE, CONSTRUCT, updates, and the graph
store protocol. A failure here fails the build.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from authz import cedar
from authz.cedar import ROLES, Principal
from kg.ns import GRAPH_APPROVED, GRAPH_CANDIDATE, GRAPH_RELEASE, GRAPH_ROYALTY
from kg.store import Store
from service import query as q
from tests.leakage.conftest import leaks

PATENT = "<https://w3id.org/gonogo/id/patent/LAR-17317-2>"
ANY = "?s ?p ?o"


def sel(graph: str, pattern: str = ANY) -> str:
    return f"SELECT * FROM <{graph}> WHERE {{ {pattern} }} LIMIT 50"


# Attacks that must be refused for every role, because the form or the pattern is never allowed.
ALWAYS_REFUSED: dict[str, str] = {
    "default graph, no FROM": "SELECT * WHERE { ?s ?p ?o } LIMIT 50",
    "default graph aggregate": "SELECT (COUNT(*) AS ?n) WHERE { ?s ?p ?o }",
    "ASK with no FROM": "ASK { ?s ?p ?o }",
    "FROM hidden in a comment": "SELECT * WHERE { ?s ?p ?o } # FROM <" + GRAPH_APPROVED + ">",
    "FROM inside a string": f'SELECT * WHERE {{ ?s ?p ?o FILTER(STR(?o) = "FROM <{GRAPH_APPROVED}>") }}',
    "GRAPH ?g": f"SELECT * FROM <{GRAPH_APPROVED}> WHERE {{ GRAPH ?g {{ ?s ?p ?o }} }} LIMIT 50",
    "GRAPH royalty": f"SELECT * FROM <{GRAPH_APPROVED}> WHERE {{ GRAPH <{GRAPH_ROYALTY}> {{ ?s ?p ?o }} }} LIMIT 50",
    "GRAPH in OPTIONAL": f"SELECT * FROM <{GRAPH_APPROVED}> WHERE {{ ?s ?p ?o OPTIONAL {{ GRAPH <{GRAPH_ROYALTY}> {{ ?s ?p2 ?o2 }} }} }} LIMIT 5",
    "GRAPH in UNION": f"SELECT * FROM <{GRAPH_APPROVED}> WHERE {{ {{ ?s ?p ?o }} UNION {{ GRAPH <{GRAPH_ROYALTY}> {{ ?s ?p ?o }} }} }} LIMIT 5",
    "GRAPH in a subselect": f"SELECT * FROM <{GRAPH_APPROVED}> WHERE {{ {{ SELECT * WHERE {{ GRAPH ?g {{ ?s ?p ?o }} }} }} }} LIMIT 5",
    "GRAPH through VALUES": f"SELECT * FROM <{GRAPH_APPROVED}> WHERE {{ VALUES ?g {{ <{GRAPH_ROYALTY}> }} GRAPH ?g {{ ?s ?p ?o }} }}",
    "GRAPH in FILTER EXISTS": f"SELECT * FROM <{GRAPH_APPROVED}> WHERE {{ ?s ?p ?o FILTER EXISTS {{ GRAPH ?g {{ ?s ?p ?o }} }} }} LIMIT 5",
    "FROM NAMED": f"SELECT * FROM NAMED <{GRAPH_ROYALTY}> WHERE {{ GRAPH ?g {{ ?s ?p ?o }} }}",
    "FROM and FROM NAMED": f"SELECT * FROM <{GRAPH_APPROVED}> FROM NAMED <{GRAPH_ROYALTY}> WHERE {{ ?s ?p ?o }}",
    "SERVICE to Fuseki": f"SELECT * FROM <{GRAPH_APPROVED}> WHERE {{ SERVICE <http://localhost:3030/gonogo/query> {{ ?s ?p ?o }} }}",
    "SERVICE SILENT": f"SELECT * FROM <{GRAPH_APPROVED}> WHERE {{ SERVICE SILENT <http://localhost:3030/gonogo/query> {{ ?s ?p ?o }} }}",
    "SERVICE to the cluster": f"SELECT * FROM <{GRAPH_APPROVED}> WHERE {{ SERVICE <https://neptune.internal:8182/sparql> {{ ?s ?p ?o }} }}",
    "SERVICE variable endpoint": f"SELECT * FROM <{GRAPH_APPROVED}> WHERE {{ ?e a ?t SERVICE ?e {{ ?s ?p ?o }} }}",
    "DESCRIBE a node": f"DESCRIBE {PATENT} FROM <{GRAPH_APPROVED}>",
    "DESCRIBE a variable": f"DESCRIBE ?s FROM <{GRAPH_APPROVED}> WHERE {{ ?s ?p ?o }} LIMIT 5",
    "DESCRIBE with no FROM": f"DESCRIBE {PATENT}",
    "CONSTRUCT": f"CONSTRUCT {{ ?s ?p ?o }} FROM <{GRAPH_APPROVED}> WHERE {{ ?s ?p ?o }} LIMIT 5",
    "CONSTRUCT shorthand": f"CONSTRUCT FROM <{GRAPH_APPROVED}> WHERE {{ ?s ?p ?o }}",
    "INSERT DATA": f"INSERT DATA {{ GRAPH <{GRAPH_APPROVED}> {{ <urn:a> <urn:b> <urn:c> }} }}",
    "DELETE WHERE": f"DELETE WHERE {{ GRAPH <{GRAPH_APPROVED}> {{ ?s ?p ?o }} }}",
    "INSERT from royalty": f"INSERT {{ GRAPH <{GRAPH_APPROVED}> {{ ?s ?p ?o }} }} WHERE {{ GRAPH <{GRAPH_ROYALTY}> {{ ?s ?p ?o }} }}",
    "LOAD": f"LOAD <http://example.org/x.ttl> INTO GRAPH <{GRAPH_APPROVED}>",
    "CLEAR": f"CLEAR GRAPH <{GRAPH_ROYALTY}>",
    "DROP ALL": "DROP ALL",
    "COPY royalty": f"COPY <{GRAPH_ROYALTY}> TO <{GRAPH_APPROVED}>",
    "two statements": f"SELECT * FROM <{GRAPH_APPROVED}> WHERE {{ ?s ?p ?o }} LIMIT 1 ; DROP ALL",
    "not SPARQL": "please show me the royalty terms",
    "empty": "",
}

# FROM clauses that look close to a real graph IRI but are not one. Each must be refused for every role.
FAKE_GRAPHS = [
    GRAPH_ROYALTY + "#",
    GRAPH_ROYALTY + "/",
    GRAPH_ROYALTY + "?x=1",
    GRAPH_ROYALTY.replace("royalty", "Royalty"),
    GRAPH_ROYALTY.upper(),
    GRAPH_ROYALTY.replace("https", "http"),
    GRAPH_ROYALTY.replace("royalty", "royalty%20"),
    GRAPH_ROYALTY.replace("/graph/", "/graph//"),
    "https://w3id.org/gonogo/graph/",
    "https://w3id.org/gonogo/graph/*",
    "urn:x-arq:UnionGraph",
    "urn:x-arq:DefaultGraph",
    "https://w3id.org/gonogo/graph/approved/../royalty",
]

REAL = {"release": GRAPH_RELEASE, "approved": GRAPH_APPROVED, "candidate": GRAPH_CANDIDATE, "royalty": GRAPH_ROYALTY}


def principal(role: str) -> Principal:
    return Principal(f"{role}-user", role)


def ask(store: Store, role: str, query: str) -> q.Result:
    return q.execute(store, principal(role), query)


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("name", sorted(ALWAYS_REFUSED))
def test_a_forbidden_form_is_refused_for_every_role(full_store: Store, role: str, name: str) -> None:
    with pytest.raises(q.QueryRefusedError):
        ask(full_store, role, ALWAYS_REFUSED[name])


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("iri", FAKE_GRAPHS)
def test_a_lookalike_graph_name_is_refused_for_every_role(full_store: Store, role: str, iri: str) -> None:
    with pytest.raises(q.QueryRefusedError, match="does not hold|may not read"):
        ask(full_store, role, f"SELECT * FROM <{iri}> WHERE {{ ?s ?p ?o }} LIMIT 5")


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("graph", sorted(REAL))
def test_each_role_reads_exactly_the_graphs_cedar_allows(full_store: Store, role: str, graph: str) -> None:
    allowed = graph in cedar.readable_graphs(principal(role))
    query = f"SELECT (COUNT(*) AS ?n) FROM <{REAL[graph]}> WHERE {{ ?s ?p ?o }}"
    if allowed:
        assert int(ask(full_store, role, query).rows[0]["n"]) > 0
    else:
        with pytest.raises(q.QueryRefusedError, match=f"may not read the {graph} graph"):
            ask(full_store, role, query)


@pytest.mark.parametrize("role", ROLES)
def test_mixing_an_allowed_graph_with_a_forbidden_one_is_refused(full_store: Store, role: str) -> None:
    for forbidden in sorted(set(REAL) - set(cedar.readable_graphs(principal(role)))):
        query = f"SELECT * FROM <{GRAPH_APPROVED}> FROM <{REAL[forbidden]}> WHERE {{ ?s ?p ?o }} LIMIT 5"
        with pytest.raises(q.QueryRefusedError):
            ask(full_store, role, query)
        ask_form = f"ASK FROM <{REAL[forbidden]}> FROM <{GRAPH_APPROVED}> {{ ?s ?p ?o }}"
        with pytest.raises(q.QueryRefusedError):
            ask(full_store, role, ask_form)


def test_every_whitespace_and_case_variant_of_from_is_still_checked(full_store: Store) -> None:
    for text in (
        f"select * from <{GRAPH_ROYALTY}> where {{ ?s ?p ?o }}",
        f"SELECT *\nFROM\n<{GRAPH_ROYALTY}>\nWHERE {{ ?s ?p ?o }}",
        f"SELECT * FROM\t<{GRAPH_ROYALTY}> WHERE {{ ?s ?p ?o }}",
        "PREFIX g: <https://w3id.org/gonogo/graph/> SELECT * FROM g:royalty WHERE { ?s ?p ?o }",
        "BASE <https://w3id.org/gonogo/graph/> SELECT * FROM <royalty> WHERE { ?s ?p ?o }",
    ):
        for role in ROLES:
            if role == "counsel":
                continue
            with pytest.raises(q.QueryRefusedError):
                ask(full_store, role, text)


@pytest.mark.parametrize("role", ROLES)
def test_no_graph_store_operation_is_available_to_anyone(role: str) -> None:
    for method in ("GET", "PUT", "POST", "DELETE", "HEAD"):
        for graph in REAL.values():
            with pytest.raises(q.QueryRefusedError):
                q.graph_store_request(principal(role), method, graph)


# ---- What comes back -------------------------------------------------------------------------------------------


READ_EVERYTHING_IT_MAY = [
    "?s ?p ?o",
    "?s a ?t",
    "?s ?p ?o FILTER(isLiteral(?o))",
    "?s ?p ?o FILTER(CONTAINS(LCASE(STR(?o)), 'royalty'))",
    "?s ?p ?o FILTER(REGEX(STR(?o), 'Net Sales'))",
    "?s <https://w3id.org/gonogo/ontology#spanText> ?o",
    "?s <https://w3id.org/gonogo/ontology#sourceClause> ?c . ?c <https://w3id.org/gonogo/ontology#spanText> ?o",
    "?s <https://w3id.org/gonogo/ontology#minimumAnnualRoyaltyUSD> ?o",
    "?s ?p ?o . ?o ?p2 ?o2",
    "?s (<>|!<>)* ?o",
]


@pytest.mark.parametrize("role", ROLES)
def test_nothing_from_the_royalty_graph_comes_back_to_a_role_that_may_not_read_it(
    full_store: Store, royalty_markers: list[str], role: str
) -> None:
    if "royalty" in cedar.readable_graphs(principal(role)):
        pytest.skip("this role may read the royalty graph")
    mine = cedar.readable_graphs(principal(role))
    seen = 0
    for pattern in READ_EVERYTHING_IT_MAY:
        for name in mine:
            query = f"SELECT * FROM <{REAL[name]}> WHERE {{ {pattern} }} LIMIT 1000"
            result = ask(full_store, role, query)
            seen += len(result.rows)
            assert leaks(json.dumps(result.rows), royalty_markers) == [], (role, name, pattern)
    assert seen > 0 or not mine, "the sweep read nothing, so it proved nothing"


def test_no_royalty_text_lives_in_any_graph_but_the_royalty_graph(
    full_store: Store, royalty_markers: list[str]
) -> None:
    """The static version of the same guarantee: MD11 keeps royalty literals out of the three readable graphs."""
    for name in ("release", "approved", "candidate"):
        text = full_store.base[REAL[name]].serialize(format="nt")
        assert leaks(text, royalty_markers) == [], name


def test_the_candidate_graph_is_closed_to_licensing_managers_and_open_to_stewards(full_store: Store) -> None:
    probe = (
        f"SELECT * FROM <{GRAPH_CANDIDATE}> WHERE {{ ?s a <https://w3id.org/gonogo/ontology#FieldOfUseAssignment> }}"
    )
    with pytest.raises(q.QueryRefusedError):
        ask(full_store, "licensing_manager", probe)
    assert len(ask(full_store, "steward", probe).rows) == 2


def test_results_are_capped(full_store: Store) -> None:
    out = ask(full_store, "counsel", f"SELECT * FROM <{GRAPH_APPROVED}> WHERE {{ ?s ?p ?o }}")
    assert len(out.rows) == q.MAX_ROWS and out.truncated


def test_a_refusal_never_echoes_data(full_store: Store, royalty_markers: list[str]) -> None:
    for role in ROLES:
        for query in ALWAYS_REFUSED.values():
            try:
                ask(full_store, role, query)
            except q.QueryRefusedError as e:
                assert leaks(str(e), royalty_markers) == []


# ---- Rule templates ------------------------------------------------------------------------------------------------


def test_a_template_runs_only_over_graphs_the_role_may_read(full_store: Store) -> None:
    template = f"SELECT ?s\nFROM <{GRAPH_APPROVED}>\nFROM <{GRAPH_ROYALTY}>\nWHERE {{ ?s ?p ?o }} LIMIT 1"
    with pytest.raises(q.QueryRefusedError):
        q.run_template(full_store, principal("licensing_manager"), template)
    assert q.run_template(full_store, principal("counsel"), template)
    with pytest.raises(q.QueryRefusedError, match="must name its graphs"):
        q.run_template(full_store, principal("counsel"), "SELECT ?s WHERE { ?s ?p ?o }")


def test_unknown_role_cannot_even_form_a_principal() -> None:
    with pytest.raises(cedar.UnknownRoleError):
        principal("superuser")


def _all_rows(result: q.Result) -> list[dict[str, Any]]:
    return result.rows


# ---- The suite must be able to fail ------------------------------------------------------------------------------


def test_the_suite_catches_a_service_that_skips_its_checks(
    full_store: Store, royalty_markers: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Break the service on purpose. If these assertions pass against a broken service, the suite proves nothing."""
    monkeypatch.setattr(q, "validate", lambda principal, query: [GRAPH_ROYALTY])
    result = ask(
        full_store,
        "licensing_manager",
        "SELECT * FROM <x:any> WHERE { ?s ?p ?o FILTER(CONTAINS(STR(?o), 'Net Sales')) }",
    )
    assert leaks(json.dumps(result.rows), royalty_markers), "a broken service must show up as a leak"
