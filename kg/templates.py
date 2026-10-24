"""Parameterized SPARQL templates.

A template is SPARQL text with three kinds of placeholder:

  {{FROM}}          replaced by one FROM clause per allowlisted graph IRI
  {{ASOF ?var}}     replaced by the bitemporal filter for the fact bound to ?var
  {{name}}          replaced by a typed, validated parameter

A template without {{FROM}} is rejected. Neptune treats the default graph as the union of every named
graph, so a query that names no graph would read confidential graphs. The query service in Gate 3 uses
this module, and the competency-question tests use it today.

The bitemporal filter keeps a fact only when the system had recorded it at the recording cutoff and no
correction had superseded it by then:

    ?fact gng:recordedAt ?r . FILTER(?r <= cutoff)
    FILTER NOT EXISTS { ?fact gng:supersededAt ?s . FILTER(?s <= cutoff) }

No rule ever sees an LLM-written query. Templates are reviewed text, and parameters are typed values.
"""

from __future__ import annotations

import re

_ASOF = re.compile(r"\{\{ASOF (\?[A-Za-z_]\w*)\}\}")
_PARAM = re.compile(r"\{\{([A-Za-z_]\w*)\}\}")
_IRI_OK = re.compile(r"^[^\s<>\"{}|\\^`]+$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DATETIME = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$")
_INT = re.compile(r"^-?\d+$")

PREFIXES = """\
PREFIX gng:    <https://w3id.org/gonogo/ontology#>
PREFIX skos:   <http://www.w3.org/2004/02/skos/core#>
PREFIX prov:   <http://www.w3.org/ns/prov#>
PREFIX dct:    <http://purl.org/dc/terms/>
PREFIX schema: <https://schema.org/>
PREFIX xsd:    <http://www.w3.org/2001/XMLSchema#>
PREFIX rdfs:   <http://www.w3.org/2000/01/rdf-schema#>
PREFIX excl:   <https://w3id.org/gonogo/exclusivity/>
"""


class TemplateError(ValueError):
    """Raised when a template or a parameter is unsafe or incomplete."""


def term(param: dict[str, str]) -> str:
    """Turn a typed parameter into a SPARQL term. Exactly one type key is allowed."""
    if len(param) != 1:
        raise TemplateError(f"A parameter has exactly one type key, got {sorted(param)}")
    ((kind, value),) = param.items()
    if kind == "iri":
        if not _IRI_OK.match(value):
            raise TemplateError(f"Unsafe IRI: {value!r}")
        return f"<{value}>"
    if kind == "date":
        if not _DATE.match(value):
            raise TemplateError(f"Bad date: {value!r}")
        return f'"{value}"^^xsd:date'
    if kind == "datetime":
        if not _DATETIME.match(value):
            raise TemplateError(f"Bad dateTime: {value!r}")
        return f'"{value}"^^xsd:dateTime'
    if kind == "int":
        if not _INT.match(value):
            raise TemplateError(f"Bad integer: {value!r}")
        return value
    if kind == "string":
        escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        return f'"{escaped}"'
    raise TemplateError(f"Unknown parameter type: {kind}")


def asof(var: str, cutoff: str) -> str:
    name = var.lstrip("?")
    return (
        f"{var} gng:recordedAt ?rec_{name} . FILTER(?rec_{name} <= {cutoff})\n"
        f"  FILTER NOT EXISTS {{ {var} gng:supersededAt ?sup_{name} . FILTER(?sup_{name} <= {cutoff}) }}"
    )


def render(template: str, params: dict[str, dict[str, str]], graphs: list[str], prefixes: bool = True) -> str:
    """Fill a template. Raise TemplateError when it has no {{FROM}}, no graphs, or a missing parameter."""
    if "{{FROM}}" not in template:
        raise TemplateError("The template has no {{FROM}} placeholder, so it could read every named graph.")
    if not graphs:
        raise TemplateError("The graph allowlist is empty.")
    for g in graphs:
        if not _IRI_OK.match(g):
            raise TemplateError(f"Unsafe graph IRI: {g!r}")
    terms = {name: term(value) for name, value in params.items()}

    def asof_sub(m: re.Match[str]) -> str:
        if "cutoff" not in terms:
            raise TemplateError("{{ASOF}} needs a cutoff parameter.")
        return asof(m.group(1), terms["cutoff"])

    text = _ASOF.sub(asof_sub, template)
    text = text.replace("{{FROM}}", "\n".join(f"FROM <{g}>" for g in graphs))

    def param_sub(m: re.Match[str]) -> str:
        name = m.group(1)
        if name not in terms:
            raise TemplateError(f"Missing parameter: {name}")
        return terms[name]

    text = _PARAM.sub(param_sub, text)
    return (PREFIXES + text) if prefixes else text


def strip_from(query: str) -> str:
    """Remove FROM clauses. An in-memory engine uses this after it merges the named graphs itself."""
    return re.sub(r"^FROM <[^>]+>\n?", "", query, flags=re.M)
