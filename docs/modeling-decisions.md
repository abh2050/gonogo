# Modeling decisions

This document explains why the GoNoGo ontology looks the way it does. Each entry names a problem, states the
choice, gives the reason, admits the cost, and points at the file and test that prove the choice works. The
ontology marks the terms that implement each decision with the annotation `gng:modelingDecision`, and a test
checks that every such label points at an entry below.

Read [ontology-guide.md](ontology-guide.md) first for the overview, and open the
[ontology reference](ontology/index.html) for every class and property.

### MD1. A grant is a class

**Problem.** A license relates six things at once: a patent, a licensee, a field of use, a territory, a term,
and an exclusivity type. An RDF property relates two things.

**Choice.** The ontology follows the W3C pattern for n-ary relations. `gng:Grant` is a class, and each
participant hangs off the grant node through its own property: `gng:aboutPatent`, `gng:licensee`,
`gng:fieldOfUse`, `gng:territory`, `gng:exclusivityType`. The term is the grant's valid-time interval,
`gng:validFrom` and `gng:validTo`, so the grant needs no separate term node. One grant can name several
patents by repeating `gng:aboutPatent`. The same idea applies to patent facts: `gng:Patent` holds identity
only, and legal status, ownership, export classification, and filing dates are separate facts about it.

**Why.** A node can carry its own provenance, its own recording time, and a link to the clause it came from. A
binary property cannot. Keeping status off the patent node lets two registries disagree about the same patent
without overwriting each other.

**Cost.** Every question about a license takes one extra hop, and a person who reads the data sees more nodes.

**Evidence.** `gng:Grant` in [gonogo.ttl](../ontology/gonogo.ttl); competency questions CQ04 to CQ06.

### MD2. Proposed grants and executed grants are separate classes

**Problem.** A Federal Register notice says that NASA intends to grant a license. It opens an objection window,
and the license may never be signed. Treating the notice as a license would invent conflicts.

**Choice.** `gng:ProposedGrant` and `gng:ExecutedGrant` are sibling subclasses of `gng:Grant`, declared
disjoint. A `gng:LicenseNotice` creates only a proposed grant. Only a `gng:LicenseAgreement` creates an executed
grant. `gng:Grant` itself is abstract: it equals the union of the two.

**Why.** Rule R2 treats the two differently. An overlap with an executed exclusive grant is a conflict (FAIL).
An overlap with another party's proposed grant needs a lawyer (REVIEW).

**Cost.** Queries that want both must name both classes, or use the superclass.

**Evidence.** The disjointness axiom is checked by HermiT, and `tests/unit/test_shacl.py` shows that the build
rejects a grant that is both. CQ07 reads proposed grants.

### MD3. Fields of use and territories are SKOS concepts, not OWL subclasses

**Problem.** Fields of use form a hierarchy: lasers sit under optics. OWL subclassing would say that every
laser-field license is an optics-field license, as a statement about sets.

**Choice.** Each field is a `skos:Concept` in a `skos:ConceptScheme`, linked by `skos:broader` and
`skos:narrower`. The same holds for territories, exclusivity types, and legal states.

**Why.** The business edits the field list. A change that moves a concept is a policy change, and OWL
subclassing would make it a logical claim that a reasoner enforces everywhere. SKOS keeps the hierarchy as
data that an owner edits, reviews, and releases. It also gives labels, notations, and definitions for free.

**Cost.** The reasoner cannot see inside a concept, so GoNoGo adds the coverage rule by hand (MD4).

**Evidence.** [ontology/schemes/](../ontology/schemes/); the top level of the field scheme reuses the 15 NASA T2
portal categories, and `tests/unit/test_ontology.py` checks that the two lists match.

### MD4. Broader means wider rights coverage

**Problem.** If a grant covers optics, does it cover lasers? The answer decides whether a request conflicts.

**Choice.** A grant for a broader concept covers every narrower concept beneath it, and a request for a broader
concept overlaps every grant on a narrower one. The ontology states the first half as a property chain:
`gng:fieldOfUse o skos:narrowerTransitive` implies `gng:coversField`. The territory scheme works the same way
with `gng:coversTerritory`, so a grant for North America covers a request for the United States.

**Why.** The rule lives in the ontology, so it has one definition. A reasoner derives it, and the pipeline
writes the result into the graph. Rule queries then read `gng:coversField` and need no recursion.

**Cost.** Every edit to `skos:broader` changes legal outcomes. The release pipeline must show each changed
verdict before a hierarchy edit goes live (Gate 3). `test_a_hierarchy_edit_changes_what_a_grant_covers` shows
the effect: moving the laser concept out of optics drops it from a grant's coverage.

**Evidence.** `gng:coversField` and `gng:coversTerritory` in the ontology; competency questions CQ04, CQ05, CQ08.

### MD5. The open world assumption, and why a missing fact is not a negative fact

**Problem.** The graph has no ownership record for patent P7. Does P7 have no co-owners?

**Choice.** No. OWL reasons under the open world assumption: what the graph does not say is unknown. GoNoGo
keeps that meaning. A missing record means unknown, and rule R6 returns UNKNOWN, which the combiner turns into
NO DATA. The system refuses to treat an absence as proof.

**Why.** Absence of evidence is the most common reason a clearance goes wrong. A person who reads GO must be
able to trust that every fact behind it was recorded.

**Cost.** The system returns NO DATA more often than a closed-world system would return GO.

**Evidence.** CQ10 and CQ12 return no rows for the patent with no classification and the patent with no
ownership record. The rule engine in Gate 2 turns those empty results into UNKNOWN.

### MD6. A negative fact is a fact

**Problem.** Some patents truly have no co-owners. The system must be able to say so, and must tell that case
apart from "nobody checked".

**Choice.** A `gng:OwnershipRecord` carries `gng:coOwnerListIsComplete`. A record with the flag `true` and no
`gng:coOwner` statements asserts that the patent has no co-owners. A record with the flag `false` lists the
co-owners that someone knows about. No record means unknown (MD5).

**Why.** OWL cannot express this distinction by itself, because a missing statement and a false statement look
the same to a reasoner. The flag makes the author's claim explicit, and the rule engine, not the reasoner,
acts on it.

**Evidence.** CQ12 returns three different answers for three patents: complete with none, complete with two,
and incomplete. CQ11 lists the co-owners that have not consented.

### MD7. Facts are bitemporal, and evidence is a clause span

**Problem.** A grant has dates on which it applies. A correction can arrive months later and change what the
system believed. A past verdict must still reproduce.

**Choice.** Every `gng:BitemporalFact` has two times. `gng:validFrom` and `gng:validTo` say when the fact holds
in the world. `gng:recordedAt` says when the system recorded it. `gng:supersededAt` says when a correction
replaced it. A correction adds a new fact that `gng:supersedes` the old one. It never deletes the old one. A
query that supplies a recording cutoff sees only facts recorded at or before the cutoff and not yet superseded.
The template engine adds that filter to every query (`{{ASOF ?fact}}` in `kg/templates.py`).

Each fact also points at the exact words it came from. A `gng:Clause` holds a character span in a
`gng:SourceDocument`, and a SHACL constraint checks that the stored text equals the characters at the span.

**Why.** The valid time answers whether a grant applies on a date. The recording time answers what the system
knew when it decided. Reproducing a decision needs both.

**Cost.** Two time dimensions confuse readers at first, and every query needs the filter.

**Evidence.** CQ13 returns a different grant before and after a correction. `test_the_injected_conflicts_can_be_found_by_querying_the_graph`
runs the generator's ground truth against the loaded graph with each case's own cutoff.

### MD8. Provenance with PROV-O, and a label on every synthetic fact

**Problem.** A reader of a verdict needs to know where each fact came from, who approved it, and whether it is
real.

**Choice.** The ontology reuses PROV-O. Every fact has exactly one `prov:wasGeneratedBy` activity: a bulk load
of registry data, an extraction from text, or a run of the synthetic generator. Every fact in the approved
graph has an approver through `gng:approvedBy`: a steward, or a named standing policy. The bulk-load policy
approves public registry data and never approves a fact that a language model extracted. The synthetic-load
policy approves labeled synthetic data. Synthetic facts carry `prov:wasGeneratedBy` the generator run, and that
link is the label that says so.

**Why.** The label cannot be forgotten, because the shapes require a generating activity on every fact.

**Evidence.** CQ14 returns the document, clause text, activity, and approver for a grant. CQ15 counts synthetic
and real facts by class. `shapes/approved-shapes.ttl` fails any approved fact that has no approver.

### MD9. Licensee names stay as written until a steward links them

**Problem.** The Federal Register writes "GenH2" in one notice and "GenH2 Corporation" in another.

**Choice.** Each distinct spelling becomes its own `gng:Licensee` node. Each grant also records
`gng:licenseeNameAsWritten`. A steward links two nodes with `owl:sameAs`, with provenance (Gate 2).

**Why.** A rule must not merge two companies on a guess. Merging is a decision, so it goes through an action
that records who made it.

**Cost.** Until a steward approves a link, queries that count licensees see the spellings as separate parties.

### MD10. Two registries, one patent

**Problem.** The NASA Patents snapshot says that US 8,077,103 expires on 2027-07-06. The USPTO says that the
patent expired for unpaid maintenance fees. Both are real.

**Choice.** Each registry's answer is its own `gng:PatentLegalStatus` fact with its own source, recording time,
and expiration basis. The graph keeps both. Rule R1 prefers the USPTO fact and falls back to the NASA fact only
when the USPTO has no record. An expiration date that GoNoGo computed from other dates carries
`gng:expirationIsDerived true`, and the card must say so.

**Why.** Overwriting one source with the other would hide the disagreement, and the disagreement is the
finding: of 263 patents that the NASA snapshot calls in force, the USPTO shows 181 lapsed.

**Evidence.** CQ02 returns both answers for one patent. CQ03 finds patents whose only evidence is a filing date.

### MD11. Named graphs organize facts, and royalty terms stay in their own graph

**Problem.** Licensing managers may read executed grants but not royalty terms. Stewards review candidate facts
before anyone relies on them.

**Choice.** Four named graphs hold the data: `release/0.1.0` (the ontology, schemes, and policies),
`approved`, `candidate`, and `royalty`. An agreement's full text contains its royalty article, so the full text
and the royalty clause live in the `royalty` graph. The approved graph holds the other clauses.

**Why.** Graph-level access control is only as good as the graph boundaries. A leak through a text literal would
defeat it.

**Cost.** The graph does not hold a complete copy of an agreement for a manager. The original document sits in
storage behind its own permission check.

**Evidence.** `test_royalty_terms_and_agreement_text_stay_out_of_the_approved_graph`. Gate 3 adds the
Verified Permissions policies and a leakage suite.

### MD12. The reasoner, SHACL, and the rules each do one job

**Problem.** Three tools can check data. Without a clear split, a rule can end up hidden in a shape or an axiom.

**Choice.** The reasoner derives what follows from the model: types, hierarchy closure, rights coverage, and
inconsistencies. SHACL checks that facts are complete and well formed. Rule functions (R1 to R7) decide what a
fact means for a request, and the combiner turns rule statuses into a verdict. Governed actions (`gng:Action`)
are the only way to change the graph. A language model never decides a verdict and never writes a query.

**Why.** Each concern has one owner and one place to read. A shape that says "a lapsed patent needs a lapse
date" is about completeness. A rule that says "a lapsed patent fails R1" is about meaning.

**Evidence.** [shapes/gonogo-shapes.ttl](../shapes/gonogo-shapes.ttl) contains no verdict logic.
`tests/unit/test_shacl.py` breaks valid data 13 ways and checks that the shapes reject each.

### MD13. Inference is materialized before load, and the closure is checked

**Problem.** Neptune does not reason at query time.

**Choice.** The build computes the OWL 2 RL closure with owlrl and writes the entailments that rules need into
the graphs: defined-class types, subclass types, SKOS transitive links, and rights coverage. It keeps a short
whitelist of predicates, so the loaded graphs stay readable. Rule queries also use property paths where that is
cheap, as a second safeguard.

The build then checks that no individual belongs to two disjoint classes. This step matters because range axioms
type whatever a property points at. A grant that names a territory as its field of use would turn that territory
into a `gng:FieldOfUse`, and a SHACL class check would pass. The disjointness axiom is what rejects the
mistake, so the build enforces it.

**Why.** A reasoner and a validator answer different questions. Running both, in the right order, catches more
than either does alone.

**Evidence.** `test_a_territory_used_as_a_field_of_use_fails_the_consistency_check`, and the ROBOT and HermiT
tests in `tests/unit/test_robot.py`, which reject three deliberately inconsistent datasets.

### MD14. A model proposes a field of use as a candidate fact, with its prompt, model, and quote

**Problem.** Of the 41 real notices in scope, 24 state no field of use. The 18 marked `limited_unspecified` say
only that "the fields of use may be limited". A model asked to name a field would name one anyway.

**Choice.** The extractor may answer "none stated". When it names a field, the field must be a concept in the
SKOS scheme, and its quote must appear word for word in the notice. Code checks both, so a failed check drops
the proposal. A passing proposal becomes a `gng:FieldOfUseAssignment` in the candidate graph, with its own property
`gng:assignsField`, so an approved assignment never edits the grant. (The first draft reused `gng:fieldOfUse`,
whose domain is `gng:Grant`, and the build's disjointness check rejected it.) It points at the
grant it describes (`gng:aboutGrant`), at a clause that holds the quote, and at a `gng:Extraction` run that
records the model ID and the prompt version. No rule reads the candidate graph. A steward approves an
assignment, and only then does R2 see the field.

**Why.** The model contributes a reading of the words and nothing else. The prompt version and model ID let a
reader reproduce or challenge the proposal, and the verbatim quote lets a steward check it in seconds.

**Cost.** An assignment narrows what a notice leaves open, so a wrong approval can hide a real overlap. Gate 3
adds a second reviewer for any approval that would move a verdict to GO (ADR 0002).

**Evidence.** `tests/agent/test_field_extractor.py` runs the checks against a fake client, including a quote
that is not in the notice and a concept that is not in the scheme.

### MD15. Who proposed a fact is recorded, and a fact that changes a verdict needs a second person

**Problem.** The engine let one steward approve a fact that contradicted an approved fact, and that approval
turned COUNSEL into GO without anyone else seeing it. The record showed who approved the fact, but nothing
stopped the approver from being the proposer.

**Choice.** Every candidate carries `gng:proposedBy`: a steward, a licensee, a feed, or a model agent. The
engine computes two flags for each approval. The first says the fact conflicts with an approved fact
(`kg/governance.py`). The second says that approving it would move a verdict from COUNSEL or NO GO to GO,
found by rerunning the questions on the same patent before and after. Cedar policies read the flags and
decide. An approval with no flag takes effect at once. A flagged approval waits in `PENDING_SECOND_REVIEW`
and changes nothing until counsel approves it, and counsel is never the first approver. Nobody approves a
fact that they proposed. The approved fact records both approvers (`gng:approvedBy`, `gng:secondApprovedBy`).

**Why.** The graph keeps what happened, and the policy decides who may make it happen. Cedar holds the rules
as text that a reviewer can read, and the same text runs in Verified Permissions.

**Cost.** A flagged approval takes two people, so it is slower. Real stewards will meet the flag on facts that
legitimately correct an older record, and counsel's queue will grow. Counting the flags per month shows
whether the threshold is right.

**Evidence.** ADR 0002, `tests/authz/test_policies.py` (every role against every action), and
`tests/rules/test_separation.py`, which runs the decoy through the whole sequence.

### MD16. Verdicts go to a table for finance, and Ontop shows the table as a graph

**Problem.** Finance analysts read verdicts and royalty terms in Snowflake and may not query the graph. At the
same time, reports about decisions benefit from the ontology: a finance question such as "how many exclusive
requests ended in COUNSEL last quarter" reads better as SPARQL over `gng:Decision` than as a column list.

**Choice.** Each decision writes one summary row to a verdict table, with the verdict, the signature, the user and
role, the release, the combiner version, and the recording cutoff. An R2RML mapping (`mappings/gonogo.r2rml.ttl`)
describes the table as `gng:Decision` individuals, and Ontop answers SPARQL over them without copying anything.
The same mapping also describes the patent master and licensee tables, so the mapping is the contract between
Snowflake and the ontology. The rules never read Ontop: a rule reads only facts that were loaded with recording
times, so a decision reproduces. Decisions get their own property, `gng:decisionPatent`, because
`gng:aboutPatent` belongs to facts.

**Why.** A virtual graph over reporting data costs nothing to keep in sync, and the mapping documents what each
column means. Materializing the same mapping produces the same triples as the build for the columns it covers,
which a test checks.

**Cost.** Ontop is another service to run, and the mapping must change when a table does. The writeback is
idempotent but not transactional with the decision record, so a crash between the two leaves a decision with no
finance row until the next write.

**Evidence.** `tests/integration/test_ontop.py` materializes the mapping over PostgreSQL and compares it with the
graph. `tests/service/test_writeback.py` checks the writeback, and says what a live Snowflake account would add.

