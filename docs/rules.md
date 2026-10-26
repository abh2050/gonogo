# Rules, verdicts, and the steward loop

GoNoGo will not say GO until every fact it needs is on record and a person has approved each one. Take
this request:

> Orbital Lens Works, Inc. wants a non-exclusive license to NASA case LAR-17317-2 for test and measurement
> in United States from January 1, 2027 to December 31, 2031.

Six rules have what they need. R5, the export control rule, finds no export classification for the patent,
so the verdict is NO DATA. A proposed classification does exist, but it sits in the candidate graph, and no
rule reads that graph. Once a steward approves it, R5 passes and the verdict becomes GO. The rerun names R5
as the rule that changed and the steward as the person who supplied the evidence. A rerun of the first
decision from its stored cutoff still gives NO DATA.

The rest of this page explains each step of that example. The code lives in [rules/](../rules/),
[kg/actions.py](../kg/actions.py), [er/](../er/), [agent/](../agent/), and [api/index.py](../api/index.py).

## From a question to a verdict

[agent/parser.py](../agent/parser.py) reads the question with fixed patterns. It maps "test and measurement"
to the concept `test-and-measurement` in the field scheme, "LAR-17317-2" to a patent in the graph, and the two
dates to ISO dates. It records the character span each value came from. When it cannot find a part, it lists
that part as missing, because a guessed field of use would decide a license. All 43 synthetic requests parse
to their recorded values.

[er/resolver.py](../er/resolver.py) then matches "Orbital Lens Works, Inc." against the licensees in the
graph. It follows any `owl:sameAs` link that a steward has approved, so a rule that looks for the licensee
also finds its other spellings.

Each of the seven rules fills fixed SPARQL templates from [rules/templates/](../rules/templates/) with typed
parameters. A template must name its graphs with `FROM`, and no rule's list includes the candidate graph or
the royalty graph. Every template also filters facts by recording time (`{{ASOF ?fact}}`), so a rule sees
the graph as it stood at the decision's cutoff and not as it stands today.

The combiner in [config/precedence.yaml](../config/precedence.yaml) (version 1.0.0) turns the seven
statuses into one verdict. [rules/explain.py](../rules/explain.py) then writes one sentence per rule from the
structured findings. In Gate 2, no language model writes any part of the explanation.

## The seven rules

| Rule | Question | PASS | FAIL | Other outcomes |
|---|---|---|---|---|
| R1 Patent in force | Is the patent alive on the start date? | USPTO shows it in force, or a derived expiry (filing + 20 years) lies after the start | Lapsed, ended, never issued, or expired before the start | UNKNOWN when only the old NASA snapshot speaks, or no dates exist |
| R2 Overlapping grants | Does an existing grant conflict? | No overlap | An overlapping executed grant conflicts with the request's exclusivity | REVIEW when another party's proposed grant overlaps |
| R3 Co-exclusive cap | Would the request exceed the cap? | Within the smallest stated cap | Above it | UNKNOWN with no cap; NOT_APPLICABLE unless co-exclusive |
| R4 Notice window | Has the requester's objection window closed? | Every matching window closed | | PENDING while open; REVIEW when no notice names the requester; NOT_APPLICABLE for non-exclusive |
| R5 Export control | May the licensee's country receive it? | Unrestricted, or the country is permitted | | REVIEW for a restricted country; UNKNOWN with no classification |
| R6 Co-owner consent | Has every co-owner consented? | A complete record with no co-owners, or every co-owner consented | | REVIEW for a missing consent; UNKNOWN for a missing or incomplete record |
| R7 Statutory review | Does 35 U.S.C. 209 need counsel? | | | REVIEW for every exclusive-family request; NOT_APPLICABLE otherwise |

R2 and R3 test overlap in both directions along the hierarchies. A grant for *Optics* covers a request for
*Lasers*, and a request for *Optics* overlaps a grant for *Lasers*. Territories work the same way.

## The combiner

The combiner checks this list from the top, and the first status that appears among the results decides:

| Status | Verdict |
|---|---|
| FAIL | NO GO |
| PENDING | HOLD |
| REVIEW | COUNSEL |
| UNKNOWN | NO DATA |
| none of the above | GO |

NOT_APPLICABLE takes no part. Every rule runs on every request, so the verdict card shows the other findings
under a NO GO. Because R7 returns REVIEW for every exclusive request, an exclusive request can never reach GO.
`tests/rules/test_combiner.py` checks the policy against every combination of statuses.

## The decision record

The rerun in the opening example works because each decision stores everything the answer depended on:

| Field | Meaning |
|---|---|
| `request` | The canonical request: concept ids and ISO dates, never free text |
| `recording_cutoff` | The recording time the rules saw. Facts recorded later are invisible to this decision. |
| `evaluation_time` | The date against which the rules judged "in force" and "window open" |
| `release_version`, `rule_versions`, `combiner_policy_version` | The ontology release and the code that decided |
| `findings` | Each rule's status and summary, the facts it read, and the source clauses behind them |
| `facts_read` | Every fact IRI any rule read |
| `signature` | SHA-256 over the findings in canonical JSON |
| `events_applied` | How many steward actions the graph held |

`rerun(store, record)` evaluates the record again with its stored cutoff. The steward's approval was recorded
after that cutoff, so the bitemporal filter hides it, and the signature matches the original.
`tests/rules/test_loop.py` checks this for all 44 injected cases and again after steward actions.

## The steward loop

A steward changes the graph through governed actions. Each one needs a name, a role, and a reason, and Cedar
decides whether that role may do it ([ADR 0002](adr/0002-separation-of-duties.md)):

| Action | Effect |
|---|---|
| `propose_fact` | Puts a candidate fact forward, recording who proposed it. Changes no verdict. |
| `approve_fact` | Copies the candidate into the approved graph as a new fact: `prov:wasGeneratedBy` the action, `gng:approvedBy` the steward, `prov:wasDerivedFrom` the candidate. It supersedes the current fact of the same kind for the same patent (`gng:supersedes`, `gng:supersededAt`), and the old fact stays. SHACL validates the new triples first. |
| `second_review` | Counsel approves or denies an approval that a steward submitted and that is waiting. |
| `reject_fact` | Records the decision. The graph's facts do not change. |
| `link_identity` | Writes `owl:sameAs` between two licensee nodes, plus a dated `gng:IdentityLink` that carries the score and the method |
| `reject_link` | Records that two nodes are different organizations, so the resolver stops proposing the pair |

### When one person is enough

Before an approval takes effect, the engine applies it to a copy of the store and computes two flags. The fact
may **conflict** with a fact that is already approved, such as an ownership record that leaves out a listed
co-owner. Or the approval may **move a verdict from COUNSEL or NO GO to GO** for a question on the same patent,
either one in the request book or one that the steward's own session asked. Cedar then reads the flags:

| Flags | What the steward may do | What happens |
|---|---|---|
| none | `ApproveFact` | The fact takes effect now |
| either | `SubmitForSecondReview` | The approval waits in `PENDING_SECOND_REVIEW`, adds no fact, and changes no verdict |
| any | nothing, if the steward proposed the fact | Refused |

Counsel then makes the second approval, and counsel must be a different person from the steward and from the
proposer. Counsel never approves a fact alone. The approved fact records both approvers.

The log stays honest. Each event records its route, and replaying a log recomputes the route from the graph. A log
that someone edited from `pending_second_review` to `immediate` fails on replay.

The event log replays from the frozen graph to the same graph every time, and `to_sparql_update` writes the same
triples as `INSERT DATA` for Fuseki or Neptune. The demo clock records event *n* at 2026-11-01T00:00:00Z plus *n*
seconds, so the same clicks give the same decision ids on any day.

### What the demo queue holds

| Candidate | Proposed by | What approval does | Should a steward approve it? |
|---|---|---|---|
| Unrestricted export classification for LAR-17317-2 | A review desk (synthetic) | R5 UNKNOWN → PASS, verdict NO DATA → GO. No flag, so one steward is enough. | Yes. The patent had no classification. |
| Ownership record for LEW-18605-2, complete with no co-owners | A feed (synthetic) | R6 UNKNOWN → PASS, verdict NO DATA → GO. One steward is enough. | Yes. It completes an incomplete record. |
| Ownership record for LAR-17381-1, complete with no co-owners | The licensee (synthetic) | Both flags fire: it drops co-owner COO-001, and it would move COUNSEL to GO. The approval waits for counsel. | No. The recorded assignment lists a co-owner, so approval would hide a missing consent. |
| A field of use for two real notices (coatings, aerogels) | A language model | R2 narrows an unstated field to the named one. The queue shows the notice's own words. | Check the quote. Both quote an invention's description and not a stated field of use. |
| Identity link between "GenH2" and "GenH2 Corporation", from two real notices | The resolver | For an exclusive request: R4 and R2 REVIEW → PASS, and R7 keeps COUNSEL. For a non-exclusive request in the session, it would move COUNSEL to GO, so it waits for counsel. | Yes, on the evidence in the notices. |

The third row is the reason for the two-person rule. Before it, GoNoGo acted on that wrong approval exactly as it
acted on a right one, and the only protection was a record that someone could read afterward.

## Entity resolution

The resolver strips legal suffixes such as Inc., LLC, Corporation, GmbH, and K.K. It then scores token
overlap and character similarity, and compares addresses when both sides have one. Equal names after
normalization are a match. Names that score 0.74 or higher go to the steward queue as ambiguous, and so do
equal names at conflicting addresses. The resolver never links two nodes on its own; only a steward's
`link_identity` does. These are the results on [er/labeled_pairs.jsonl](../er/labeled_pairs.jsonl)
(`python -m er.evaluate`):

| Split | Counted as same | Pairs | Precision | Recall |
|---|---|---:|---:|---:|
| test | automatic match | 49 | 1.00 | 0.91 |
| test | match or proposed | 49 | 0.87 | 0.91 |
| holdout | automatic match | 20 | 1.00 | 1.00 |
| holdout | match or proposed | 20 | 0.83 | 1.00 |

I tuned the resolver once after looking at errors on the test split, so the test split no longer measures
unseen data. I wrote the 20 holdout pairs after that change, and they are the honest number. Twenty pairs
is a small sample, though, and one more miss would move recall by five points.

## Where a language model fits

The Gate 2 parser is deterministic. [agent/model_parser.py](../agent/model_parser.py) can ask Claude on
Bedrock to fill the parts the parser missed, through a fixed tool schema. The code checks the model's answer
against the same vocabularies: it drops an unknown concept, an unknown patent, or a malformed date, and lists
that part as missing. The model never sees the graph and never writes a query. It stays off unless you set
`GONOGO_MODEL_PARSER=1`, and neither the public demo nor the tests call it.
