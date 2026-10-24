# ADR 0001. Upper ontology alignment

**Status:** Accepted, 2026-10-24
**Scope:** `ontology/gonogo.ttl` and the vocabularies it reuses

## Context

An upper ontology gives a model a shared set of top-level categories, such as things that persist and things
that happen. Three candidates fit a project like this one:

- **BFO**, the Basic Formal Ontology. It is a small top-level ontology and an ISO standard (ISO/IEC 21838-2).
  It splits the world into continuants, which persist, and occurrents, which unfold in time. Biomedical
  ontologies in the OBO Foundry build on it.
- **CCO**, the Common Core Ontologies. They are mid-level ontologies that extend BFO with classes for agents,
  artifacts, events, and information.
- **FIBO**, the Financial Industry Business Ontology. It models financial instruments, parties, and contracts.
  Its foundations include modules for agreements and contracts.

GoNoGo's ontology has 42 classes, 21 object properties, and 48 datatype properties. Its job is to hold the facts that seven clearance rules read, together
with the provenance and time dimensions that make a past decision reproducible. Two other facts shape the
choice. The model must stay readable by the people who edit its vocabularies, and a reasoner must check it
inside a continuous integration run.

## Decision

GoNoGo does **not** import BFO, CCO, or FIBO. It reuses four small, widely deployed vocabularies and declares
only the terms it uses.

| Vocabulary | Terms GoNoGo reuses | Used for |
|---|---|---|
| PROV-O | `prov:Entity`, `prov:Activity`, `prov:Agent`, `prov:Person`, `prov:SoftwareAgent`, `prov:wasGeneratedBy`, `prov:wasDerivedFrom`, `prov:wasAttributedTo`, `prov:wasAssociatedWith`, `prov:startedAtTime` | Where each fact came from, which run produced it, and who approved it |
| SKOS | `skos:Concept`, `skos:ConceptScheme`, `skos:inScheme`, `skos:broader`, `skos:narrower`, `skos:broaderTransitive`, `skos:narrowerTransitive`, `skos:hasTopConcept`, `skos:topConceptOf`, `skos:prefLabel`, `skos:notation`, `skos:definition` | Fields of use, territories, exclusivity types, and legal states as editable vocabularies |
| Dublin Core Terms | `dct:title`, `dct:description`, `dct:identifier`, `dct:source` | Names and identifiers of documents, patents, and schemes |
| schema.org | `schema:Organization`, `schema:legalName`, `schema:url` | Licensee and co-owner names, and document links |

`ontology/imports/external-terms.ttl` declares exactly these terms, with the axioms their home vocabularies
state, so that a reasoner can check the ontology under OWL 2 DL without downloading the full vocabularies.

GoNoGo adds no alignment axioms to BFO, CCO, or FIBO now. If a future integration needs them, they belong in a
separate alignment file that maps `gng:` terms to the upper ontology. The core ontology then stays unchanged.

schema.org has no class for a patent, so `gng:Patent` is GoNoGo's own class.

## Reasons

1. **The commitment is larger than the model.** BFO commits a model to a view of the world: each class must be
   a continuant or an occurrent, and a license, a notice, and a clause each need a careful reading under that
   view. That work pays off when many ontologies must interoperate. GoNoGo has one application and no peer
   ontology to align with.
2. **The model carries its own time semantics.** Bitemporal facts, with valid time and recording time, are the
   central requirement. BFO treats time through its occurrent categories, and CCO builds temporal regions on
   top. Neither provides a ready-made valid-time and recording-time pair. GoNoGo would have to add its own
   properties on top of the upper ontology and then explain how the two relate.
3. **FIBO's contract model is larger than the need.** A license here relates six things and has no obligations,
   payments, or lifecycle to model. FIBO's agreement and contract modules describe parties, roles, and
   obligations in a finance setting, and importing them adds an import chain that a reader would have to learn
   before reading a single GoNoGo grant. The decision to keep `gng:Grant` as an n-ary relation (MD1) is the
   direct alternative.
4. **Reuse where reuse pays.** PROV-O, SKOS, Dublin Core, and schema.org solve problems that GoNoGo shares with
   many other models: provenance, controlled vocabularies, document metadata, and organization names. Tools
   and readers already know them.
5. **The reasoner has to run in CI.** HermiT checks the merged ontology and schemes in under a
   second of reasoning time. A large imported hierarchy would slow every run and add classes that no rule reads.

## Consequences

- The ontology is easy to read in full. Its reference documentation fits on one page.
- Interoperability with an upper-ontology-based system needs a mapping step that GoNoGo does not provide today.
- A reviewer who expects BFO categories will not find them. This ADR is the explanation they should find
  instead.
- If the project grows into a shared ontology with other teams, this decision should be revisited. The
  alignment file approach keeps that change small.

## Alternatives considered

- **Import BFO and subclass its categories.** Rejected for reasons 1 and 2.
- **Import CCO for agents and events.** Rejected for the same reasons, plus the size of the import.
- **Import FIBO's agreements module for `gng:Grant`.** Rejected for reason 3.
- **Use no external vocabulary at all.** Rejected for reason 4. It would reinvent provenance and SKOS.
