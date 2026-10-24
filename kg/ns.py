"""Namespaces, graph IRIs, and identifier helpers for the GoNoGo knowledge graph."""

from __future__ import annotations

import re
from urllib.parse import quote

from rdflib import Namespace

GNG = Namespace("https://w3id.org/gonogo/ontology#")
ID = Namespace("https://w3id.org/gonogo/id/")
FIELD = Namespace("https://w3id.org/gonogo/field/")
TERRITORY = Namespace("https://w3id.org/gonogo/territory/")
EXCL = Namespace("https://w3id.org/gonogo/exclusivity/")
STATE = Namespace("https://w3id.org/gonogo/legal-state/")
CENTER = Namespace("https://w3id.org/gonogo/center/")
SCHEME = Namespace("https://w3id.org/gonogo/scheme/")
POLICY = Namespace("https://w3id.org/gonogo/policy/")
RUN = Namespace("https://w3id.org/gonogo/run/")
PROV = Namespace("http://www.w3.org/ns/prov#")
DCT = Namespace("http://purl.org/dc/terms/")
SCHEMA = Namespace("https://schema.org/")
SKOS = Namespace("http://www.w3.org/2004/02/skos/core#")

RELEASE_VERSION = "0.1.0"
GRAPH_BASE = "https://w3id.org/gonogo/graph/"
GRAPH_RELEASE = GRAPH_BASE + f"release/{RELEASE_VERSION}"
GRAPH_APPROVED = GRAPH_BASE + "approved"
GRAPH_CANDIDATE = GRAPH_BASE + "candidate"
GRAPH_ROYALTY = GRAPH_BASE + "royalty"
GRAPHS = [GRAPH_RELEASE, GRAPH_APPROVED, GRAPH_CANDIDATE, GRAPH_ROYALTY]

# The synthetic generator, as the run that produced every synthetic fact (prov:wasGeneratedBy).
GENERATOR_RUN = "https://w3id.org/gonogo/synth/generator/v0.1"
GENERATOR_AGENT = "https://w3id.org/gonogo/synth/generator"
BULK_LOAD_POLICY = POLICY["bulk-load-v1"]
FR_EXTRACTOR = "gonogo-regex-extractor/0.1"

US_NAMES = {"united states", "united states of america", "the united states"}


def slug(value: str) -> str:
    """A readable, IRI-safe slug: lower case, alphanumerics and single hyphens."""
    s = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return s or "x"


def iri_part(value: str) -> str:
    """Percent-encode a key for use as an IRI path segment, keeping hyphens and letters readable."""
    return quote(value, safe="-._~")


def patent_iri(key: str) -> str:
    return str(ID["patent/" + iri_part(key)])


def territory_for(text: str | None) -> str | None:
    """Map a notice's territory words to a territory concept by exact name. No guessing."""
    if not text:
        return None
    t = text.strip().lower()
    if t in US_NAMES:
        return str(TERRITORY["US"])
    if t == "worldwide":
        return str(TERRITORY["WORLD"])
    return None
