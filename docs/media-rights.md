# What carries over to media rights clearance

GoNoGo clears patent licenses. A studio that wants to know whether it may stream a film in a territory asks a
question of the same shape: who holds which rights, for which use, where, and when, and does a new request
collide with a grant that already exists? This page separates the architecture that would carry over from the
rules that would not.

## Patterns that carry over

| Pattern | In GoNoGo | In media rights |
|---|---|---|
| **Write the questions first** | Fifteen competency questions drive the model ([ontology/competency_questions.md](../ontology/competency_questions.md)) | "May we stream season two in Germany from March?" and "Which grants block it?" decide which classes the model needs |
| **Hierarchies as vocabularies** | Fields of use and territories are SKOS concepts, and a grant on a broader one covers the narrower ones (MD3, MD4) | Territories nest the same way. Media nest too: "all electronic media" covers "streaming", which covers "ad-supported streaming" |
| **A missing fact is not a yes** | The open world assumption. No ownership record gives NO DATA, not GO (MD5) | An unknown rights holder, or an unrecorded earlier sale, must block a clearance and not pass it |
| **A negative fact is a fact** | "This patent has no co-owners" is recorded as a complete empty list (MD6) | "No third party holds music sync rights" needs a record that says so |
| **Facts carry two times** | Valid time and recording time, so any past decision can be rerun (MD7) | Rights windows, holdbacks, and retroactive corrections (a reversion, an amended contract) need the same two axes |
| **Evidence is a clause span** | Every fact points to the clause that states it | A clearance that cannot point at the contract language is not auditable |
| **Confidential terms in their own graph** | Royalty terms never leave the royalty graph (MD11) | Minimum guarantees, advances, and most-favored-nation terms are the first thing a rights team must not leak |
| **A model reads, rules decide** | The model proposes a field of use. It never decides a verdict | The same boundary keeps a language model from clearing a license it should not |
| **Risky approvals need two people** | Conflicting or verdict-raising approvals wait for counsel (ADR 0002) | A change that would flip a blocked title to cleared is exactly what a second reviewer is for |
| **Reproducible decisions** | Every decision records its cutoff, release, and a signature over its findings | A dispute over a clearance months later can be settled by rerunning it |
| **Governed model changes** | Ontology releases ship with an impact report and counsel's approval | Adding a new media type to the hierarchy should show which past clearances it changes |

## Rules that do not carry over

| GoNoGo rule | Why it stays behind |
|---|---|
| **R1 Patent in force** | Patents expire by a fixed term and lapse when fees go unpaid. Copyright terms depend on the work, the country, and the date of the author's death. Chain of title replaces legal status. |
| **R3 Co-exclusive cap** | A patent license can cap the number of co-exclusive licensees. Media deals use windows, holdbacks, and first-negotiation or matching rights instead. |
| **R4 Notice window** | NASA must publish its intent to grant an exclusive license and wait for objections (35 U.S.C. 209). Private rights deals have no public notice period. |
| **R5 Export control** | Patent technology can be export controlled. Media is limited by sanctions and by where a platform may geo-block. |
| **R6 Co-owner consent** | A patent's co-owners must all consent. Media co-ownership is usually split by territory and by medium, so consent is per slice. |
| **R7 Statutory review** | A federal statute sends exclusive patent licenses to counsel. No such statute exists here. |

## Where the model itself would change

- **More dimensions.** A patent grant has a field and a territory. A media grant also has a platform, a language, a
  window, a holdback, and a format. Each is a vocabulary in the same style, but the grant node carries more of them,
  and the overlap rule has to compare them all.
- **Splits.** Rights are often split by territory or by medium between holders, so ownership is a set of slices,
  not one record per patent.
- **Cross-title rights.** A soundtrack, a character, and a script each carry rights that a title inherits. The graph
  needs a way to say that one grant covers another work's contribution.
- **Data.** NASA publishes its notices and patent registry. Media rights deals are private. The public data that
  made the real-data parts of GoNoGo possible would not exist, and the evaluation would need synthetic data,
  as the agreements here do, labeled as such.

## The short version

Keep the shape: an ontology written from the questions, vocabularies for hierarchies, an open world, facts that
carry two times and a source, confidential terms in their own graph, rules that decide and a model that only
reads, two people for risky approvals, and a decision that can be rerun. Replace the rules with the domain's own,
and expect the grant node to grow more dimensions.
