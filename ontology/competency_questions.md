# Competency questions

A competency question is a question that the ontology must let a user answer. Writing the questions before the
model tells the modeler which classes and properties earn their place. The 15 questions below come from the seven
clearance rules (R1 to R7), plus the questions that reproducibility, provenance, and the open world assumption
raise.

Each question is an executable SPARQL template in [tests/cq/](../tests/cq/) with a file of hand-worked cases.
A person computed every expected answer from the sample world in
[tests/cq/data/sample-approved.ttl](../tests/cq/data/sample-approved.ttl) before any query ran. The tests run
each case on two engines, rdflib in process and a real Fuseki server, and the release graph in those tests is
the real ontology and SKOS schemes. A change to the hierarchy that alters an answer fails a test.

Three things in every template come from `kg/templates.py`, the same engine that the query service uses in
Gate 3:

- `{{FROM}}` expands to one `FROM` clause per allowlisted graph. A template without it is rejected, because
  Neptune treats the default graph as the union of every named graph.
- `{{ASOF ?fact}}` expands to the bitemporal filter: the system had recorded the fact by the cutoff, and no
  correction had superseded it by then.
- `{{name}}` is a typed parameter. The engine validates IRIs, dates, and integers, so no value can inject query
  text.

## Coverage

| Question | What it asks | Rule |
|---|---|---|
| CQ01 | Patents named by a notice | R4 |
| CQ02 | What each registry says about a patent's status | R1 |
| CQ03 | Patents whose expiration can only be derived | R1 |
| CQ04 | Grants that overlap a requested field | R2 |
| CQ05 | Grants that overlap a requested territory | R2 |
| CQ06 | Grants that overlap a requested term | R2, R3 |
| CQ07 | Proposed grants held by other parties | R2 |
| CQ08 | Co-exclusive holders and the stated cap | R3 |
| CQ09 | Notices with an open objection window | R4 |
| CQ10 | Export classification and permitted territories | R5 |
| CQ11 | Listed co-owners who have not consented | R6 |
| CQ12 | Ownership completeness, including no record | R6 |
| CQ13 | What the system knew at a recording cutoff | All rules |
| CQ14 | Source clause, activity, and approver of a fact | All findings |
| CQ15 | Synthetic versus real facts | Labeling |

## CQ01. Which patents does a license notice name?

**Rule:** R4 (matching the notice to a patent)
**Ontology constructs:** gng:announcedIn, gng:aboutPatent, gng:caseNumber
**Query:** [tests/cq/01_notice_patents.rq](../tests/cq/01_notice_patents.rq)

Hand-worked cases:

- **Notice N1 names two patents.** Answer: TST-10001-1; TST-10004-1.
- **Notice N2 announces no grant.** Answer: no rows.

## CQ02. What does each registry say about whether patent P is alive on a given day, as the system knew it at the recording cutoff?

**Rule:** R1
**Ontology constructs:** gng:PatentLegalStatus, gng:legalState, gng:expirationDate, gng:expirationIsDerived, bitemporal filter
**Query:** [tests/cq/02_status_sources.rq](../tests/cq/02_status_sources.rq)

Hand-worked cases:

- **P2: USPTO says lapsed, the NASA snapshot still shows a 2027 expiration.** Answer: regNASA | none | 2027-07-06 | false; regUSPTO2 | lapsed | 2030-09-10 | true.
- **P1: one registry, in force, with a derived expiration.** Answer: regUSPTO1 | in force | 2036-05-02 | true.
- **P2 before the lapse began: no status is valid yet.** Answer: no rows.

## CQ03. Which patents have a filing date but no registry expiration date, so that a rule could derive an expiration?

**Rule:** R1 (derived expiration, labeled derived)
**Ontology constructs:** gng:FilingRecord, gng:filingDate, gng:expirationDate, absence as unknown
**Query:** [tests/cq/03_derivable_expiration.rq](../tests/cq/03_derivable_expiration.rq)

Hand-worked cases:

- **P3 has only a filing date.** Answer: P3 | 2016-05-02.
- **Before the filing record was recorded, nothing is derivable.** Answer: no rows.

## CQ04. Which executed grants on patent P overlap a requested field of use, in either direction on the field hierarchy?

**Rule:** R2
**Ontology constructs:** gng:coversField (property chain over skos:narrowerTransitive), skos:broaderTransitive
**Query:** [tests/cq/04_field_overlap.rq](../tests/cq/04_field_overlap.rq)

Hand-worked cases:

- **A request for lenses-and-mirrors sits under the broad Optics grant G1, and beside the laser grants G3 and G4 (siblings do not overlap).** Answer: G1 | grant covers request.
- **A request for Optics covers the narrower laser grants.** Answer: G1 | grant covers request; G3 | request covers grant; G4 | request covers grant.
- **A request for Aerospace covers the narrower spacecraft grant G2.** Answer: G2 | request covers grant.

## CQ05. Which executed grants on patent P overlap a requested territory, in either direction on the territory hierarchy?

**Rule:** R2
**Ontology constructs:** gng:coversTerritory (property chain), skos:broaderTransitive, ISO 3166 countries under regions
**Query:** [tests/cq/05_territory_overlap.rq](../tests/cq/05_territory_overlap.rq)

Hand-worked cases:

- **A United States request sits inside the North America grant G1 and equals the US grants G3 and G4.** Answer: G1 | grant covers request; G3 | grant covers request; G4 | grant covers request.
- **A North America request covers the narrower US grants.** Answer: G1 | grant covers request; G3 | request covers grant; G4 | request covers grant.
- **A Germany request overlaps only the Germany grant G2.** Answer: G2 | grant covers request.
- **A Europe request covers the Germany grant G2.** Answer: G2 | request covers grant.

## CQ06. Which executed grants on patent P have a term that overlaps a requested term?

**Rule:** R2 (and R3)
**Ontology constructs:** gng:validFrom, gng:validTo, partial overlaps, expired grants, bitemporal filter
**Query:** [tests/cq/06_term_overlap.rq](../tests/cq/06_term_overlap.rq)

Hand-worked cases:

- **A 2027 to 2031 request overlaps the three live grants.** Answer: G1 | 2025-01-01 | 2034-12-31; G3 | 2026-01-01 | 2035-12-31; G4 | 2026-02-01 | 2035-12-31.
- **A 2018 request overlaps only the grant that has since expired.** Answer: G2 | 2018-01-01 | 2024-12-31.
- **A request that straddles the end of G2 and the start of G1 overlaps both partially.** Answer: G1 | 2025-01-01 | 2034-12-31; G2 | 2018-01-01 | 2024-12-31.
- **A request after every term ends overlaps nothing.** Answer: no rows.

## CQ07. Which proposed grants on patent P belong to a party other than the requester?

**Rule:** R2 (overlap with another party's proposed grant needs counsel)
**Ontology constructs:** gng:ProposedGrant is separate from gng:ExecutedGrant, gng:licensee
**Query:** [tests/cq/07_proposed_by_others.rq](../tests/cq/07_proposed_by_others.rq)

Hand-worked cases:

- **Alpha Optics asks while Delta Welding holds a proposed grant.** Answer: PG1 | Delta Welding Co..
- **Delta Welding asks, so its own proposed grant does not count.** Answer: no rows.
- **Before the notice was recorded the system knew of no proposed grant.** Answer: no rows.

## CQ08. How many licensees already hold co-exclusive rights that reach a requested field and territory on a given day, and what cap do the agreements state?

**Rule:** R3
**Ontology constructs:** gng:coversField, gng:coversTerritory, gng:coExclusiveCap, aggregation, absence of a cap as unknown
**Query:** [tests/cq/08_coexclusive_holders.rq](../tests/cq/08_coexclusive_holders.rq)

Hand-worked cases:

- **Two licensees hold the laser field in the US and the cap is two.** Answer: 2 | 2.
- **Only one had started by mid-January 2026.** Answer: 1 | 2.
- **Lenses and mirrors have no co-exclusive holder, so no cap is stated.** Answer: 0 | none.

## CQ09. Which notices for patent P still have an open objection window on a given day?

**Rule:** R4
**Ontology constructs:** gng:objectionDeadline, gng:publishedOn, gng:announcedIn
**Query:** [tests/cq/09_open_window.rq](../tests/cq/09_open_window.rq)

Hand-worked cases:

- **The window closes on 4 November, so it is open on 1 November.** Answer: N1 | 2026-11-04.
- **The window has closed by 10 November.** Answer: no rows.
- **The notice does not exist yet on 1 October.** Answer: no rows.

## CQ10. What is the export classification of patent P, and which territories may a licensee sit in?

**Rule:** R5
**Ontology constructs:** gng:RestrictedExport, gng:UnrestrictedExport, gng:permittedTerritory, gng:iso3166Alpha2, absence as unknown
**Query:** [tests/cq/10_export_classification.rq](../tests/cq/10_export_classification.rq)

Hand-worked cases:

- **P5 is restricted to the US and Canada.** Answer: restricted | CA; restricted | US.
- **P4 is unrestricted.** Answer: unrestricted | none.
- **P7 has no classification, which is unknown and not 'unrestricted'.** Answer: no rows.

## CQ11. Which listed co-owners of patent P have not consented?

**Rule:** R6
**Ontology constructs:** gng:OwnershipRecord, gng:coOwner, gng:ConsentRecord, gng:consentBy, FILTER NOT EXISTS
**Query:** [tests/cq/11_consent_missing.rq](../tests/cq/11_consent_missing.rq)

Hand-worked cases:

- **P5 lists two co-owners and only Beta University consented.** Answer: CO1 | Alpha Institute.
- **P4 lists no co-owners, so nobody is missing consent.** Answer: no rows.
- **P6's incomplete record still names a co-owner who has not consented.** Answer: CO1 | Alpha Institute.

## CQ12. Does patent P have an ownership record, does the record claim that its co-owner list is complete, and how many co-owners does it list?

**Rule:** R6
**Ontology constructs:** gng:coOwnerListIsComplete (explicit negative fact), open world: no record means unknown
**Query:** [tests/cq/12_ownership_completeness.rq](../tests/cq/12_ownership_completeness.rq)

Hand-worked cases:

- **P4: complete with no co-owners, which is an explicit negative fact.** Answer: true | 0.
- **P5: complete with two co-owners.** Answer: true | 2.
- **P6: incomplete, one known co-owner.** Answer: false | 1.
- **P7: no record at all, which is unknown.** Answer: no rows.

## CQ13. Which executed grants on patent P did the system know about, and not yet consider replaced, at a recording cutoff?

**Rule:** Every rule (reproducing a past decision)
**Ontology constructs:** gng:recordedAt, gng:supersededAt, gng:supersedes, bitemporal reproducibility
**Query:** [tests/cq/13_as_of_cutoff.rq](../tests/cq/13_as_of_cutoff.rq)

Hand-worked cases:

- **On 25 October the system still believed the grant was for Optics.** Answer: GA | Optics | none.
- **After the 26 October correction the grant is for Aerospace and says what it replaced.** Answer: GB | Aerospace | GA.
- **Before any grant was recorded the system knew nothing.** Answer: no rows.

## CQ14. For a grant, which document and clause span does each fact come from, which activity generated it, and who approved it?

**Rule:** Every finding (the verdict card cites these)
**Ontology constructs:** gng:sourceClause, gng:inDocument, gng:spanText, prov:wasGeneratedBy, gng:approvedBy
**Query:** [tests/cq/14_provenance.rq](../tests/cq/14_provenance.rq)

Hand-worked cases:

- **G1 cites its grant clause and its term clause.** Answer: agreement-G1 | grant | NASA grants Licensee an exclusive license under the Licensed Patents. | generator run | policy:synthetic-load-v1; agreement-G1 | term | This Agreement takes effect on January 1, 2025. | generator run | policy:synthetic-load-v1.

## CQ15. How many facts of each kind are synthetic, and how many are real?

**Rule:** None (the README and the verdict card use this to label synthetic data)
**Ontology constructs:** prov:wasGeneratedBy the generator run, subclass typing from the defined hierarchy
**Query:** [tests/cq/15_synthetic_labels.rq](../tests/cq/15_synthetic_labels.rq)

Hand-worked cases:

- **The sample world.** Answer: ConsentRecord | true | 1; ExecutedGrant | true | 6; ExportClassification | true | 2; FilingRecord | true | 1; OwnershipRecord | true | 3; PatentLegalStatus | false | 4; ProposedGrant | false | 1.
