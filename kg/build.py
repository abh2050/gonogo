"""Build the GoNoGo knowledge graph from the processed, scoped, and synthetic data.

Four named graphs result:

  release/<version>  the ontology, SKOS schemes, reference data, and the approval policies
  approved           approved facts: real registry and notice data, plus labeled synthetic data
  candidate          proposed facts that wait for a steward
  royalty            confidential royalty terms, and the full text of every agreement

Every fact carries its valid time, its recording time, its provenance, and the policy or steward that
approved it. Every synthetic fact also carries prov:wasGeneratedBy the generator run.
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from rdflib import RDF, RDFS, XSD, Graph, Literal, URIRef

from gonogo.paths import DATA, ONTOLOGY, PROCESSED, ROOT, SCOPE, SYNTHETIC
from kg.ns import (
    BULK_LOAD_POLICY,
    DCT,
    EXCL,
    FIELD,
    FR_EXTRACTOR,
    GENERATOR_AGENT,
    GENERATOR_RUN,
    GNG,
    GRAPH_APPROVED,
    GRAPH_CANDIDATE,
    GRAPH_RELEASE,
    GRAPH_ROYALTY,
    ID,
    POLICY,
    PROV,
    RUN,
    SCHEMA,
    STATE,
    TERRITORY,
    iri_part,
    patent_iri,
    slug,
    territory_for,
)

SYNTHETIC_POLICY = POLICY["synthetic-load-v1"]
RELEASE_FILES = [
    ONTOLOGY / "gonogo.ttl",
    ONTOLOGY / "imports" / "external-terms.ttl",
    ONTOLOGY / "reference" / "centers.ttl",
    *sorted((ONTOLOGY / "schemes").glob("*.ttl")),
]
STATE_BY_NOTATION = {
    "in_force": STATE["in-force"],
    "lapsed": STATE["lapsed"],
    "term_ended": STATE["term-ended"],
    "abandoned": STATE["abandoned"],
    "not_granted": STATE["not-granted"],
}
HOUSE_VALID_FROM = "2000-01-01"


def jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open() as f:
        return [json.loads(line) for line in f if line.strip()]


def date(value: str) -> Literal:
    return Literal(value[:10], datatype=XSD.date)


def dt(value: str) -> Literal:
    return Literal(value.replace("+00:00", "Z"), datatype=XSD.dateTime)


def boolean(value: bool) -> Literal:
    return Literal(bool(value), datatype=XSD.boolean)


def integer(value: int) -> Literal:
    return Literal(int(value), datatype=XSD.integer)


class Builder:
    def __init__(self) -> None:
        self.release = Graph()
        self.approved = Graph()
        self.candidate = Graph()
        self.royalty = Graph()
        self.centers: dict[str, URIRef] = {}
        self.patents: dict[str, dict[str, Any]] = {}
        self.uspto: dict[str, dict[str, Any]] = {}
        self.t2_by_case: dict[str, dict[str, Any]] = {}
        self.t2_by_patent: dict[str, dict[str, Any]] = {}
        self.notice_keys: dict[str, list[str]] = defaultdict(list)
        self.notice_docs: set[str] = set()

    # ---- release graph -----------------------------------------------------------------------

    def build_release(self) -> None:
        for path in RELEASE_FILES:
            self.release.parse(path)
        g = self.release
        for policy, label, definition in [
            (
                BULK_LOAD_POLICY,
                "Bulk-load policy v1",
                "Standing approval for public system-of-record data (NASA Patents dataset, USPTO Open Data "
                "Portal, Federal Register notices read by the deterministic extractor). It never approves a "
                "fact that a language model extracted.",
            ),
            (
                SYNTHETIC_POLICY,
                "Synthetic-load policy v1",
                "Standing approval to load labeled synthetic evaluation data from the seeded generator.",
            ),
        ]:
            g.add((policy, RDF.type, GNG.ApprovalPolicy))
            g.add((policy, RDFS.label, Literal(label, lang="en")))
            g.add((policy, DCT.description, Literal(definition, lang="en")))
        for node in g.subjects(RDF.type, GNG.NASACenter):
            if isinstance(node, URIRef):
                self.centers[str(g.value(node, RDFS.label))] = node

    # ---- provenance activities ---------------------------------------------------------------

    def activity(self, iri: URIRef, kind: URIRef, started: str, **props: Literal) -> URIRef:
        g = self.approved
        g.add((iri, RDF.type, kind))
        g.add((iri, PROV.startedAtTime, dt(started)))
        for pred, value in props.items():
            g.add((iri, GNG[pred], value))
        return iri

    def generator_run(self, seed: int) -> URIRef:
        g = self.approved
        run = URIRef(GENERATOR_RUN)
        g.add((run, RDF.type, GNG.SyntheticGeneration))
        g.add((run, GNG.generatorSeed, integer(seed)))
        g.add((run, PROV.startedAtTime, dt("2026-10-24T00:00:00Z")))
        g.add((run, PROV.wasAssociatedWith, URIRef(GENERATOR_AGENT)))
        g.add((URIRef(GENERATOR_AGENT), RDF.type, GNG.Generator))
        g.add((URIRef(GENERATOR_AGENT), RDFS.label, Literal("GoNoGo synthetic generator", lang="en")))
        return run

    # ---- fact helpers ------------------------------------------------------------------------

    def fact(
        self,
        g: Graph,
        node: URIRef,
        cls: URIRef,
        patents: list[str],
        recorded_at: str,
        valid_from: str,
        activity: URIRef,
        approver: URIRef | None,
        valid_to: str | None = None,
        synthetic: bool = False,
    ) -> None:
        g.add((node, RDF.type, cls))
        for key in patents:
            g.add((node, GNG.aboutPatent, URIRef(patent_iri(key))))
        g.add((node, GNG.recordedAt, dt(recorded_at)))
        g.add((node, GNG.validFrom, date(valid_from)))
        if valid_to:
            g.add((node, GNG.validTo, date(valid_to)))
        g.add((node, PROV.wasGeneratedBy, activity))
        if approver is not None:
            g.add((node, GNG.approvedBy, approver))

    def clause(self, g: Graph, iri: URIRef, doc: URIRef, kind: str, start: int, end: int, text: str) -> URIRef:
        g.add((iri, RDF.type, GNG.Clause))
        g.add((iri, GNG.inDocument, doc))
        g.add((iri, GNG.clauseKind, Literal(kind)))
        g.add((iri, GNG.spanStart, Literal(start, datatype=XSD.nonNegativeInteger)))
        g.add((iri, GNG.spanEnd, Literal(end, datatype=XSD.nonNegativeInteger)))
        g.add((iri, GNG.spanText, Literal(text)))
        return iri

    # ---- patents and registry status ---------------------------------------------------------

    def load_inputs(self) -> None:
        with (SCOPE / "patents_in_scope.csv").open() as f:
            for row in csv.DictReader(f):
                self.patents[row["patent_key"]] = row
                for doc in filter(None, row["matched_notices"].split(";")):
                    self.notice_keys[doc].append(row["patent_key"])
        # uspto.jsonl also holds lookups for out-of-scope candidates; only in-scope patents enter the graph.
        self.uspto = {
            r["patent_key"]: r
            for r in jsonl(PROCESSED / "uspto.jsonl")
            if r["found"] and r["patent_key"] in self.patents
        }
        for tech in jsonl(PROCESSED / "t2_portal.jsonl"):
            for case in tech["case_numbers"]:
                self.t2_by_case[case] = tech
            for number in tech["patent_numbers"]:
                self.t2_by_patent[number] = tech
        self.nasa_meta = json.loads((PROCESSED / "nasa_patents.meta.json").read_text())

    def build_patents(self) -> None:
        g = self.approved
        for key, row in sorted(self.patents.items()):
            node = URIRef(patent_iri(key))
            g.add((node, RDF.type, GNG.Patent))
            g.add((node, DCT.identifier, Literal(key)))
            g.add((node, DCT["title"], Literal(row["title"])))
            if row["case_number"]:
                g.add((node, GNG.caseNumber, Literal(row["case_number"])))
            if row["patent_number"]:
                g.add((node, GNG.patentNumber, Literal(row["patent_number"])))
            u = self.uspto.get(key)
            serial = (u or {}).get("application_number") or row["application_sn"]
            if serial:
                g.add((node, GNG.applicationSerial, Literal(serial)))
            g.add((node, GNG["center"], self.centers[row["center"]]))
            tech = self.t2_by_case.get(row["case_number"]) or self.t2_by_patent.get(row["patent_number"])
            if tech is None and row["tops_id"]:
                tech = next((t for t in self.t2_by_case.values() if t["tops_id"] == row["tops_id"]), None)
            if tech:
                g.add((node, GNG.topsId, Literal(tech["tops_id"])))
                if tech["category"]:
                    g.add((node, GNG.t2Category, Literal(tech["category"])))
                if tech["abstract"]:
                    g.add((node, DCT.description, Literal(tech["abstract"])))
                if tech["trl"] is not None:
                    g.add((node, GNG.technologyReadinessLevel, integer(tech["trl"])))

    def build_legal_status(self) -> None:
        g = self.approved
        nasa_run = self.activity(RUN["ingest/nasa-patents"], GNG.BulkLoad, self.nasa_meta["csv_retrieved_at"])
        uspto_run = self.activity(
            RUN["ingest/uspto"], GNG.BulkLoad, min(u["retrieved_at"] for u in self.uspto.values())
        )
        nasa_doc = ID["registry/nasa-patents"]
        g.add((nasa_doc, RDF.type, GNG.RegistryRecord))
        g.add((nasa_doc, DCT["title"], Literal("NASA Patents dataset (data.nasa.gov, gquh-watm), CSV export")))
        g.add((nasa_doc, SCHEMA.url, Literal(self.nasa_meta["csv_url"], datatype=XSD.anyURI)))
        g.add((nasa_doc, GNG.retrievedAt, dt(self.nasa_meta["csv_retrieved_at"])))
        snapshot_day = self.nasa_meta["catalog_metadata_modified"][:10]

        for key, row in sorted(self.patents.items()):
            if row["source"] == "nasa_patents":
                node = ID["status/nasa/" + iri_part(key)]
                self.fact(
                    g,
                    node,
                    GNG.PatentLegalStatus,
                    [key],
                    self.nasa_meta["csv_retrieved_at"],
                    snapshot_day,
                    nasa_run,
                    BULK_LOAD_POLICY,
                )
                g.add((node, PROV.wasDerivedFrom, nasa_doc))
                g.add((node, GNG.statusText, Literal(row["status"])))
                if row["status"] == "Application":
                    g.add((node, GNG.legalState, STATE["application"]))
                if row["patent_expiration_date"]:
                    g.add((node, GNG.expirationDate, date(row["patent_expiration_date"])))
                    g.add((node, GNG.expirationBasis, Literal("NASA Patents dataset nominal expiration date")))
                    g.add((node, GNG.expirationIsDerived, boolean(False)))
        for key, u in sorted(self.uspto.items()):
            doc = ID["registry/uspto/" + u["application_number"]]
            g.add((doc, RDF.type, GNG.RegistryRecord))
            g.add((doc, DCT.identifier, Literal(u["application_number"])))
            g.add((doc, DCT["title"], Literal(f"USPTO file wrapper for application {u['application_number']}")))
            g.add((doc, SCHEMA.url, Literal(u["source_url"], datatype=XSD.anyURI)))
            g.add((doc, GNG.retrievedAt, dt(u["retrieved_at"])))
            node = ID["status/uspto/" + iri_part(key)]
            valid_from = u["status_date"] or u["grant_date"] or u["filing_date"] or u["retrieved_at"][:10]
            self.fact(g, node, GNG.PatentLegalStatus, [key], u["retrieved_at"], valid_from, uspto_run, BULK_LOAD_POLICY)
            g.add((node, PROV.wasDerivedFrom, doc))
            g.add((node, GNG.legalState, STATE_BY_NOTATION[u["legal_state"]]))
            g.add((node, GNG.statusText, Literal(u["status_text"].strip())))
            if u["filing_date"]:
                g.add((node, GNG.filingDate, date(u["filing_date"])))
            if u["grant_date"]:
                g.add((node, GNG.grantDate, date(u["grant_date"])))
            if u["expiration_computed"]:
                g.add((node, GNG.expirationDate, date(u["expiration_computed"])))
                g.add((node, GNG.expirationBasis, Literal(u["expiration_basis"])))
                g.add((node, GNG.expirationIsDerived, boolean(True)))
            if u["grant_date"]:
                g.add((node, GNG.termAdjustmentDays, Literal(u["pta_days"], datatype=XSD.nonNegativeInteger)))
                g.add((node, GNG.hasTerminalDisclaimer, boolean(u["terminal_disclaimer"])))
            if u["lapse_events"]:
                g.add((node, GNG.lapseDate, date(u["lapse_events"][-1]["date"])))
            if u["reinstated"]:
                g.add((node, GNG.reinstatedOn, date(u["lapse_period"][1])))

    # ---- real notices ------------------------------------------------------------------------

    def build_notices(self) -> None:
        g = self.approved
        run = self.activity(
            RUN["extract/federal-register"],
            GNG.Extraction,
            "2026-10-24T18:00:00Z",
            extractionModel=Literal(FR_EXTRACTOR),
        )
        wanted = set((SCOPE / "notices_in_scope.txt").read_text().split())
        for rec in jsonl(PROCESSED / "federal_register.jsonl"):
            number = rec["document_number"]
            if number not in wanted:
                continue
            doc = ID["notice/fr-" + number]
            self.notice_docs.add(number)
            g.add((doc, RDF.type, GNG.LicenseNotice))
            g.add((doc, DCT.identifier, Literal(number)))
            g.add((doc, DCT["title"], Literal(rec["title"])))
            g.add((doc, SCHEMA.url, Literal(rec["html_url"], datatype=XSD.anyURI)))
            g.add((doc, GNG.retrievedAt, dt(rec["retrieved_at"])))
            g.add((doc, GNG.fullText, Literal(rec["text"])))
            for ident in sorted({*rec["patent_numbers"], *rec["application_sns"], *rec["case_numbers"]}):
                g.add((doc, GNG.namesIdentifier, Literal(ident)))
            clauses = []
            for i, span in enumerate(rec["spans"]):
                clauses.append(
                    self.clause(
                        g,
                        ID[f"clause/fr-{number}/{i:02d}"],
                        doc,
                        span["type"],
                        span["start"],
                        span["end"],
                        span["text"],
                    )
                )
            grant = ID["grant/proposed/fr-" + number]
            keys = sorted(self.notice_keys[number])
            self.fact(
                g, grant, GNG.ProposedGrant, keys, rec["retrieved_at"], rec["publication_date"], run, BULK_LOAD_POLICY
            )
            g.add((grant, GNG.announcedIn, doc))
            g.add((grant, GNG.publishedOn, date(rec["publication_date"])))
            for c in clauses:
                g.add((grant, GNG.sourceClause, c))
            options = rec["exclusivity_options"] or (
                [rec["exclusivity"]] if rec["exclusivity"] and rec["exclusivity"] != "unspecified" else []
            )
            for option in options:
                g.add((grant, GNG.exclusivityType, EXCL[slug(option)]))
            territory = territory_for(rec["territory"])
            if territory:
                g.add((grant, GNG.territory, URIRef(territory)))
            g.add((grant, GNG.fieldOfUseStatus, Literal(rec["field_of_use_status"])))
            if rec["field_of_use"]:
                g.add((grant, GNG.fieldOfUseText, Literal(rec["field_of_use"])))
            if rec["objection_deadline"]:
                g.add((grant, GNG.objectionDeadline, date(rec["objection_deadline"])))
                g.add((grant, GNG.objectionDeadlineBasis, Literal(rec["objection_deadline_basis"])))
            if rec["licensee"]:
                lic = ID["licensee/real/" + slug(rec["licensee"])]
                g.add((lic, RDF.type, GNG.Licensee))
                g.add((lic, SCHEMA.legalName, Literal(rec["licensee"])))
                if rec["licensee_address"]:
                    g.add((lic, GNG.registeredAddress, Literal(rec["licensee_address"])))
                g.add((grant, GNG.licensee, lic))
                g.add((grant, GNG.licenseeNameAsWritten, Literal(rec["licensee"])))

    # ---- synthetic facts ---------------------------------------------------------------------

    def synthetic_fact(
        self,
        g: Graph,
        node: URIRef,
        cls: URIRef,
        patents: list[str],
        recorded_at: str,
        valid_from: str,
        run: URIRef,
        valid_to: str | None = None,
    ) -> None:
        self.fact(g, node, cls, patents, recorded_at, valid_from, run, SYNTHETIC_POLICY, valid_to)

    def build_synthetic(self) -> None:
        g = self.approved
        manifest = json.loads((SYNTHETIC / "manifest.json").read_text())
        run = self.generator_run(manifest["seed"])

        def mark(node: URIRef, graph: Graph = g) -> None:
            graph.add((node, PROV.wasGeneratedBy, run))

        licensees = jsonl(SYNTHETIC / "licensees.jsonl")
        for lic in licensees:
            node = ID["licensee/" + lic["id"]]
            g.add((node, RDF.type, GNG.Licensee))
            g.add((node, SCHEMA.legalName, Literal(lic["name"])))
            g.add((node, GNG.countryCode, Literal(lic["country"])))
            g.add((node, GNG.registeredAddress, Literal(lic["address"])))
            for variant in lic["variants"]:
                g.add((node, GNG.nameVariant, Literal(variant)))
            mark(node)
        co_owners = jsonl(SYNTHETIC / "co_owners.jsonl")
        for co in co_owners:
            node = ID["coowner/" + co["id"]]
            g.add((node, RDF.type, GNG.CoOwner))
            g.add((node, SCHEMA.legalName, Literal(co["name"])))
            g.add((node, GNG.countryCode, Literal(co["country"])))
            mark(node)

        # Real co-assignees from USPTO assignment records.
        real_co: dict[str, URIRef] = {}
        for u in self.uspto.values():
            for name in u["co_assignees"]:
                node = ID["coowner/uspto/" + slug(name)]
                real_co[f"USPTO:{name}"] = node
                g.add((node, RDF.type, GNG.CoOwner))
                g.add((node, SCHEMA.legalName, Literal(name.title() if name.isupper() else name)))

        def co_owner_node(ref: str) -> URIRef:
            return real_co[ref] if ref.startswith("USPTO:") else ID["coowner/" + ref]

        agreements = jsonl(SYNTHETIC / "agreements.jsonl")
        agreement_ids = {a["agreement_id"] for a in agreements}
        for a in agreements:
            agr = a["agreement_id"]
            doc = ID["agreement/" + agr]
            g.add((doc, RDF.type, GNG.LicenseAgreement))
            g.add((doc, DCT.identifier, Literal(agr)))
            g.add((doc, DCT["title"], Literal(a["clauses"][0]["text"])))
            g.add((doc, GNG.storedAt, Literal(a["pdf_file"])))
            mark(doc)
            if a["seed_notice"] and a["seed_notice"] in self.notice_docs:
                g.add((doc, GNG.seededFrom, ID["notice/fr-" + a["seed_notice"]]))
            # The full text holds the royalty article, so it lives in the confidential graph.
            text = (ROOT / a["text_file"]).read_text()
            self.royalty.add((doc, GNG.fullText, Literal(text)))
            clause_nodes: dict[str, URIRef] = {}
            for c in a["clauses"]:
                node = ID[f"clause/{agr}/{c['kind']}"]
                clause_nodes[c["clause_id"]] = node
                target = self.royalty if c["kind"] == "royalty" else g
                self.clause(target, node, doc, c["kind"], c["start"], c["end"], c["text"])
                mark(node, target)
            grant = ID["grant/executed/" + agr]
            self.synthetic_fact(
                g, grant, GNG.ExecutedGrant, a["patent_keys"], a["recorded_at"], a["valid_from"], run, a["valid_to"]
            )
            g.add((grant, GNG.executedUnder, doc))
            g.add((grant, GNG.licensee, ID["licensee/" + a["licensee_id"]]))
            g.add((grant, GNG.licenseeNameAsWritten, Literal(a["licensee_as_written"])))
            g.add((grant, GNG.fieldOfUse, FIELD[a["field_concept"]]))
            g.add((grant, GNG.fieldOfUseText, Literal(a["field_text"])))
            g.add((grant, GNG.territory, TERRITORY[a["territory"]]))
            g.add((grant, GNG.exclusivityType, EXCL[slug(a["exclusivity"])]))
            g.add((grant, GNG.executedOn, date(a["executed_on"])))
            g.add((grant, GNG.sublicenseAllowed, boolean(a["sublicense_allowed"])))
            if a["co_exclusive_cap"]:
                g.add((grant, GNG.coExclusiveCap, Literal(a["co_exclusive_cap"], datatype=XSD.positiveInteger)))
            if a["superseded_at"]:
                g.add((grant, GNG.supersededAt, dt(a["superseded_at"])))
            if a["supersedes"]:
                assert a["supersedes"] in agreement_ids
                g.add((grant, GNG.supersedes, ID["grant/executed/" + a["supersedes"]]))
            for clause_id in sorted({v for v in a["fact_clauses"].values() if not v.endswith("#royalty")}):
                g.add((grant, GNG.sourceClause, clause_nodes[clause_id]))
            # Confidential royalty term, in its own graph.
            term = ID["royalty/" + agr]
            r = self.royalty
            self.synthetic_fact(
                r, term, GNG.RoyaltyTerm, a["patent_keys"], a["recorded_at"], a["valid_from"], run, a["valid_to"]
            )
            r.add((term, GNG.royaltyOf, grant))
            r.add((term, GNG.royaltyPercent, Literal(str(a["confidential"]["royalty_pct"]), datatype=XSD.decimal)))
            r.add(
                (
                    term,
                    GNG.minimumAnnualRoyaltyUSD,
                    Literal(a["confidential"]["minimum_annual_usd"], datatype=XSD.nonNegativeInteger),
                )
            )
            r.add((term, GNG.sourceClause, clause_nodes[a["fact_clauses"]["royalty"]]))

        for n in jsonl(SYNTHETIC / "proposed_grants.jsonl"):
            doc = ID["notice/" + n["notice_id"]]
            g.add((doc, RDF.type, GNG.LicenseNotice))
            g.add((doc, DCT.identifier, Literal(n["notice_id"])))
            g.add((doc, DCT["title"], Literal("Synthetic notice of intent to grant a patent license")))
            g.add((doc, GNG.fullText, Literal(n["text"])))
            mark(doc)
            c = self.clause(g, ID[f"clause/{n['notice_id']}/notice"], doc, "notice", 0, len(n["text"]), n["text"])
            mark(c)
            grant = ID["grant/proposed/" + n["notice_id"]]
            self.synthetic_fact(
                g, grant, GNG.ProposedGrant, n["patent_keys"], n["recorded_at"], n["publication_date"], run
            )
            g.add((grant, GNG.announcedIn, doc))
            g.add((grant, GNG.sourceClause, c))
            g.add((grant, GNG.publishedOn, date(n["publication_date"])))
            g.add((grant, GNG.objectionDeadline, date(n["objection_deadline"])))
            g.add((grant, GNG.objectionDeadlineBasis, Literal("stated date")))
            g.add((grant, GNG.licensee, ID["licensee/" + n["licensee_id"]]))
            g.add((grant, GNG.exclusivityType, EXCL[slug(n["exclusivity"])]))
            g.add((grant, GNG.fieldOfUse, FIELD[n["field_concept"]]))
            g.add((grant, GNG.territory, TERRITORY[n["territory"]]))
            g.add((grant, GNG.fieldOfUseStatus, Literal("stated")))

        ownership_by_key: dict[str, dict[str, Any]] = {}
        for o in jsonl(SYNTHETIC / "ownership.jsonl"):
            ownership_by_key[o["patent_key"]] = o
            node = ID["ownership/" + iri_part(o["patent_key"])]
            self.synthetic_fact(g, node, GNG.OwnershipRecord, [o["patent_key"]], o["recorded_at"], o["valid_from"], run)
            g.add((node, GNG.coOwnerListIsComplete, boolean(o["completeness"] == "complete")))
            for ref in o["co_owners"]:
                g.add((node, GNG.coOwner, co_owner_node(ref)))
                if ref.startswith("USPTO:") and o["patent_key"] in self.uspto:
                    u = self.uspto[o["patent_key"]]
                    g.add((node, PROV.wasDerivedFrom, ID["registry/uspto/" + u["application_number"]]))
        for c in jsonl(SYNTHETIC / "consents.jsonl"):
            node = ID["consent/" + iri_part(c["consent_id"].removeprefix("CON-"))]
            self.synthetic_fact(
                g, node, GNG.ConsentRecord, [c["patent_key"]], c["recorded_at"], c["recorded_at"][:10], run
            )
            g.add((node, GNG.consentBy, co_owner_node(c["co_owner_id"])))
            g.add((node, GNG.consentScope, Literal(c["scope"])))
        for e in jsonl(SYNTHETIC / "export_classifications.jsonl"):
            node = ID["export/" + iri_part(e["patent_key"])]
            cls = GNG.RestrictedExport if e["classification"] == "restricted" else GNG.UnrestrictedExport
            self.synthetic_fact(g, node, cls, [e["patent_key"]], e["recorded_at"], e["recorded_at"][:10], run)
            for code in e["permitted_countries"]:
                g.add((node, GNG.permittedTerritory, TERRITORY[code]))
        for fr in jsonl(SYNTHETIC / "filing_dates.jsonl"):
            node = ID["filing/" + iri_part(fr["patent_key"])]
            self.synthetic_fact(
                g, node, GNG.FilingRecord, [fr["patent_key"]], fr["recorded_at"], fr["filing_date"], run
            )
            g.add((node, GNG.filingDate, date(fr["filing_date"])))
        for cand in jsonl(SYNTHETIC / "candidate_facts.jsonl"):
            if cand["fact_type"] == "ExportClassification":
                node = ID["export/" + iri_part(cand["patent_key"]) + "/candidate"]
                cls = GNG.RestrictedExport if cand["classification"] == "restricted" else GNG.UnrestrictedExport
            else:
                node = ID["ownership/" + iri_part(cand["patent_key"]) + "/candidate"]
                cls = GNG.OwnershipRecord
            self.synthetic_fact(
                self.candidate, node, cls, [cand["patent_key"]], cand["proposed_at"], HOUSE_VALID_FROM, run
            )
            self.candidate.remove((node, GNG.approvedBy, None))
            self.candidate.add((node, RDFS.comment, Literal(f"Proposed from a {cand['source']}.", lang="en")))
            self.candidate.add((node, GNG.proposedBy, self.proposer(cand["proposed_by"])))
            if cls == GNG.OwnershipRecord:
                self.candidate.add((node, GNG.coOwnerListIsComplete, boolean(cand["completeness"] == "complete")))
                for ref in cand["co_owners"]:
                    self.candidate.add((node, GNG.coOwner, co_owner_node(ref)))
            for code in cand.get("permitted_countries", []):
                self.candidate.add((node, GNG.permittedTerritory, TERRITORY[code]))

    def proposer(self, who: dict[str, str]) -> URIRef:
        """The agent that put a candidate fact forward. A licensee is its own node; a feed is a software agent."""
        if who["kind"] == "licensee":
            return ID["licensee/" + who["id"]]
        node = ID["agent/feed/" + slug(who["name"])]
        self.approved.add((node, RDF.type, PROV.SoftwareAgent))
        self.approved.add((node, RDFS.label, Literal(who["name"])))
        return node

    def build_field_proposals(self) -> None:
        """Model-proposed fields of use become candidate facts. Nothing here is approved."""
        rows = jsonl(PROCESSED / "field_proposals.jsonl") if (PROCESSED / "field_proposals.jsonl").exists() else []
        spend = json.loads((PROCESSED / "field_proposals.spend.json").read_text()) if rows else {}
        proposed = [r for r in rows if r["status"] == "proposed"]
        if not proposed:
            return
        run = self.activity(
            RUN["field-extract/" + spend["prompt_version"].split("/")[-1]],
            GNG.Extraction,
            spend["ran_at"],
            extractionModel=Literal(spend["model"]),
            promptVersion=Literal(spend["prompt_version"]),
        )
        for r in proposed:
            grant = ID["grant/proposed/" + r["notice"]]
            if (grant, RDF.type, GNG.ProposedGrant) not in self.approved:
                continue  # the notice is outside the 41 in scope, so it has no grant node to describe
            doc = ID["notice/" + r["notice"]]
            clause = self.clause(
                self.candidate, ID[f"clause/{r['notice']}/field-claim"], doc, "field", r["start"], r["end"], r["quote"]
            )
            node = ID[f"field-claim/{r['notice']}/candidate"]
            patents = [str(p).rsplit("/", 1)[-1] for p in self.approved.objects(grant, GNG.aboutPatent)]
            published = str(self.approved.value(grant, GNG.publishedOn))
            self.fact(self.candidate, node, GNG.FieldOfUseAssignment, patents, spend["ran_at"], published, run, None)
            self.candidate.add((node, GNG.aboutGrant, grant))
            self.candidate.add((node, GNG.assignsField, FIELD[r["field"]]))
            agent = ID["agent/model/" + slug(spend["model"])]
            self.approved.add((agent, RDF.type, GNG.ModelAgent))
            self.approved.add((agent, RDFS.label, Literal(spend["model"])))
            self.candidate.add((node, GNG.proposedBy, agent))
            self.candidate.add((node, GNG.sourceClause, clause))
            self.candidate.add(
                (
                    node,
                    RDFS.comment,
                    Literal(f"Proposed by {spend['model']} with prompt {spend['prompt_version']}.", lang="en"),
                )
            )

    # ---- orchestration -----------------------------------------------------------------------

    def build(self) -> dict[str, Graph]:
        self.load_inputs()
        self.build_release()
        self.build_patents()
        self.build_legal_status()
        self.build_notices()
        self.build_field_proposals()
        self.build_synthetic()
        return {
            GRAPH_RELEASE: self.release,
            GRAPH_APPROVED: self.approved,
            GRAPH_CANDIDATE: self.candidate,
            GRAPH_ROYALTY: self.royalty,
        }


def build_graphs() -> dict[str, Graph]:
    return Builder().build()


__all__ = ["DATA", "Builder", "build_graphs"]
