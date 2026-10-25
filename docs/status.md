# Status

## Gate 2: rules, verdicts, entity resolution, the steward loop, and the live demo

**State:** complete and waiting for approval. Gate 3 has not started.
**Date:** 2026-10-24
**Live demo:** https://gonogo-livid.vercel.app/#/ask

Gate 2 is done, and the whole loop runs in a browser with no AWS account: ask, read the verdict, approve the
missing fact, and watch the rerun name the rule that changed. Two things need you before Gate 3. First, I did
not build the model-proposed field-of-use facts that the Gate 1 status promised, because they need paid
Bedrock calls. Second, I moved the Vercel project's root directory to the repository root.

### Deliverables

| Deliverable | Where | State |
|---|---|---|
| Rules R1 to R7 as SPARQL templates plus Python | `rules/`, `rules/templates/` (11 templates) | Done. Every template names its graphs and filters by recording time. |
| Versioned combiner | `config/precedence.yaml` (1.0.0), `rules/policy.py` | Done. Tested against every combination of statuses. |
| Decision record and rerun | `rules/decision.py`, `rules/engine.py` | Done. A rerun from the stored cutoff reproduces the signature for all 44 injected cases and after steward actions. |
| Explanations and diffs | `rules/explain.py` | Done. One sentence per rule; a diff names the rule that changed and the evidence behind it. |
| Governed actions as a replayable event log | `kg/actions.py`, `kg/store.py` | Done. Approve, reject, link, and keep apart. SHACL validates each approval. The log replays to the same graph, and exports as SPARQL Update. |
| Deterministic entity resolver with labeled pairs | `er/`, `er/labeled_pairs.jsonl` (120 pairs) | Done. Automatic matches made no false link on any split. |
| Request parser | `agent/parser.py`, `agent/model_parser.py` | Done. All 43 synthetic requests parse to their recorded values. The model fallback is built and tested with a fake client, and is off by default. |
| API | `api/index.py` | Done. One FastAPI app, local and on Vercel. Stateless. |
| UI: Ask, Steward, History, provenance graph | `ui/src/pages/`, `ui/src/components/` | Done. D3 for the provenance graph and the session timeline. |
| Public demo on Vercel | `vercel.json`, `api/snapshot/` | Live. The real engine runs as a Vercel function over a committed snapshot, with no AWS account. |
| Documentation | [docs/rules.md](rules.md), [docs/public-demo.md](public-demo.md), `api/README.md` | Done. |

### Test results

| Suite | Command | Result |
|---|---|---|
| Lint, format, types | `ruff check`, `ruff format --check`, `mypy` (strict, 56 files) | Pass |
| Offline | `uv run pytest` | 528 passed |
| Regression | `tests/rules/test_regression.py` | 44 of 44 injected cases give the expected status on every rule and the expected verdict. No case returned a false GO. |
| Steward loop | `tests/rules/test_loop.py` | 17 passed, including both NO DATA → GO approvals, the decoy, the GenH2 link, reproducibility, and replay |
| API over HTTP | `tests/api/test_api.py` | 17 passed. Each of the 8 example questions reaches the verdict it states. |
| Fuseki and Neo4j | `uv run pytest -m docker` | 44 passed |
| HermiT | `uv run pytest -m robot` | 6 passed |
| UI | `npm run build` | Pass |
| Browser | Playwright on Chrome, the full loop in light and dark themes | No console errors |
| Drift checks | `kg.docs`, `kg.export_viz`, and a fresh build against `api/snapshot/` | The committed files match. CI repeats all three. |

### What the work found

1. **GoNoGo acts on a wrong approval exactly as on a right one.** The demo queue holds a decoy, a proposed
   ownership record that leaves out a co-owner, and approving it turns COUNSEL into GO. The queue shows the
   conflict with the recorded assignment, and a test checks both paths. Nothing in the engine can catch this
   mistake; the provenance record only makes it findable afterward.
2. **An identity link changed two rules on real data.** Two real Federal Register notices name "GenH2" and
   "GenH2 Corporation". Once a steward links them, an exclusive request by GenH2 Corporation finds its own
   closed notice (R4 REVIEW → PASS), and the proposed grant to GenH2 stops counting as another party's
   (R2 REVIEW → PASS). R7 keeps the verdict at COUNSEL, as it does for every exclusive request.
3. **The name score depended on argument order.** For pair P053, (a, b) scored 0.5088 and (b, a) scored
   0.5351, because Python's `SequenceMatcher` and the greedy token pairing both depend on order. A symmetry
   test over all 120 labeled pairs caught it. The fix changed no outcome on the labeled pairs.
4. **SHACL rejected valid approvals until it saw two steps of context.** An approved fact keeps its synthetic
   origin, and a shape checks that the generator run was associated with a generator. With one step of
   context, the validator never saw the generator's type.
5. **The patent key is the identifier, not the case number.** Patents named by notices are keyed by their US
   number (`US10431355`), so the parser maps both case numbers and patent numbers to the graph's key.

### Decisions and deviations

| Topic | Decision | Made by |
|---|---|---|
| Demo session | The browser holds the event log and the server replays it on every call. Nothing is stored server side, and a new tab starts fresh. | Me |
| Demo clock | Requests are evaluated on 2026-11-01, and event *n* is recorded *n* seconds later, so a session reproduces exactly. | Me |
| Vercel project root | Changed from `ui/` to the repository root, because a function under `ui/` cannot import the engine. The build still runs in `ui/`. | Me, using the Vercel access you gave |
| Explanations | Written from the structured findings, not by a model, in Gate 2 | Me |
| Two more candidate facts and a decoy | Added to the generator without consuming its random stream, so every other synthetic file is byte-identical | Me |
| `config/aws.yaml` budget | The file now says `budget_usd: 10` (it said 50). I did not make that change and left it as it is. | You, I assume |

### Not done, and why

- **Model-proposed field-of-use facts for the real notices.** The Gate 1 status said Gate 2 would add them.
  Only 24 of 92 real notices state a field the patterns can read. A model could propose the rest as candidate
  facts with citation spans, for a steward to approve. That needs paid Bedrock calls (about 70 notices,
  well under $1 at current prices), so I did not run it without asking. See question 1.
- **Rules on Fuseki.** The rules run on the in-memory store. The same templates run on Fuseki for the
  competency questions, and Gate 3 runs the rules through the query service on Neptune.

### Open questions for you

1. **Field-of-use extraction.** Should I build the Bedrock extractor for the real notices now (under $1, with
   a citation check and steward approval), or move it into Gate 3 with the rest of the AWS work?
2. **Gate 3 approval.** Gate 3 deploys the AWS stack behind its deploy flags, adds Cedar authorization, the
   leakage and prompt-injection suites, and the release workflow, records the evidence, and tears it down.

### Gate 3 preview

Gate 3 builds the CDK app (Neptune Serverless, the Fargate agent, the Lambda rules and SHACL container, Step
Functions with a steward callback, API Gateway with Cognito, Verified Permissions with Cedar), the query
service's graph allowlist, the leakage and injection test suites, the Snowflake and Ontop mapping, and the
release workflow. Each deployment session ends with `scripts/teardown.sh`.

## Gate 1: ontology, vocabularies, shapes, and the graph load

**State:** approved.
**Date:** 2026-10-24

### Deliverables

| Deliverable | Where | State |
|---|---|---|
| OWL 2 ontology: 42 classes, 21 object properties, 48 data properties | [ontology/gonogo.ttl](../ontology/gonogo.ttl) | Done. Every term has a label and a definition, and a test enforces both. |
| SKOS schemes: 15 field tops and 36 narrower fields, 22 territories (17 ISO 3166 countries), 4 exclusivity types, 6 legal states | [ontology/schemes/](../ontology/schemes/) | Done. The generator now reads its hierarchy from these files. |
| SHACL shapes | [shapes/](../shapes/) | Done. 23 node shapes, 6 SHACL-SPARQL constraints. No shape decides a verdict. |
| 15 competency questions, each with a SPARQL template and hand-worked answers | [ontology/competency_questions.md](../ontology/competency_questions.md), `tests/cq/` | Done. 42 cases, run on rdflib and on a real Fuseki server. |
| SPARQL template engine (graph allowlist, bitemporal filter, typed parameters) | `kg/templates.py` | Done. The Gate 3 query service will use it unchanged. |
| ROBOT and HermiT in CI | `scripts/robot.sh`, `tests/unit/test_robot.py`, `.github/workflows/ci.yml` | Done. Consistent, no unsatisfiable class, and three inconsistent datasets rejected. |
| Inference materialized with owlrl before load | `kg/materialize.py` | Done, with a disjointness check on the closure. |
| Knowledge graph build and load into local Fuseki | `kg/build.py`, `kg/load.py`, `python -m kg all` | Done. 4 named graphs, 46,029 triples, loaded in 3 seconds. |
| pyLODE reference documentation | [docs/ontology/](ontology/index.html) | Generated for the ontology, the field scheme, and the shapes. CI regenerates it and fails on any difference. |
| ADR 0001 on upper ontology alignment | [docs/adr/0001-upper-ontology-alignment.md](adr/0001-upper-ontology-alignment.md) | Done. |
| Ontology guide and 13 modeling decisions | [docs/ontology-guide.md](ontology-guide.md), [docs/modeling-decisions.md](modeling-decisions.md) | Done. A test checks that every annotation in the ontology points at a decision that exists. |
| Visualizations | `ui/` | Done. Five views: overview, ontology graph, vocabularies, data findings, time model. Built with D3 and Chart.js. |
| Public demo plan | [docs/public-demo.md](public-demo.md) | Written. Nothing is deployed. |

### Test results

| Suite | Command | Result |
|---|---|---|
| Lint, format, types | `ruff check`, `ruff format --check`, `mypy` (strict, 30 files) | Pass |
| Offline | `uv run pytest` | 286 passed |
| Fuseki and Neo4j | `uv run pytest -m docker` | 44 passed (every competency question on Fuseki, plus Gate 0's checks) |
| HermiT | `uv run pytest -m robot` | 6 passed |
| Live sources | `uv run pytest -m network` | 6 passed. data.nasa.gov answered slowly (its redirect took 20 seconds on some attempts), so the check now retries. |
| AWS preflight | `uv run pytest -m aws` | 1 passed |
| UI | `npm run build` (type-check, then Vite build) | Pass |
| Drift checks | `python -m kg.docs`, `python -m kg.export_viz` | The committed files match. CI repeats both. |

**How the checks were made to fail.** A check that never fails proves nothing, so each layer has tests that
break valid data on purpose. `tests/unit/test_shacl.py` breaks a valid graph 13 ways and checks that the shapes
reject each one. Three more tests feed the build an inconsistent graph and expect a build failure. HermiT
rejects three inconsistent datasets in `tests/ontology/inconsistent/`.

### What the work found

1. **A range axiom hides a mistake from SHACL.** A grant that used a territory as its field of use made the
   closure type that territory as a field of use, so the SHACL class check passed. The disjointness axiom is
   what catches it. The build now checks disjointness on every individual after the closure
   (modeling decision MD13).
2. **Running the questions on two engines caught a real error.** rdflib accepted a query that reused a bound
   variable as an aggregate alias, and Fuseki rejected it, as the SPARQL specification requires.
3. **Real data can find the generator's ground truth.** The test
   `test_the_injected_conflicts_can_be_found_by_querying_the_graph` takes each of the 13 injected R2 conflicts
   and finds its agreement through the field and territory hierarchies. All 13 are found.
4. **Royalty text sits inside the agreements.** An agreement's full text contains its royalty article, so
   the full text and the royalty clause live in the confidential graph, and a test checks that no royalty
   wording reaches the approved graph (MD11).
5. **The retroactive-correction cases needed new dates.** They used a cutoff of 2026-03-01, which predates
   the moment the real data entered the system (2026-10-24). At that cutoff, the real USPTO facts would not
   exist, so rule R1 would return UNKNOWN. The cases now use a cutoff of 2026-10-25 and a correction recorded
   on 2026-10-26. A test checks that every real fact was recorded before the earlier cutoff.

### Decisions and deviations

| Topic | Decision | Made by |
|---|---|---|
| "SHACL 1.1" | The W3C has no SHACL 1.1. The shapes use SHACL Core and SHACL-SPARQL constraints, which pySHACL implements. | Me |
| The term of a grant | A grant's term is its valid-time interval (`validFrom`, `validTo`), not a separate node. The spec lists "a term" among the six participants, and the interval is that participant. | Me |
| Taxonomy source of truth | The SKOS files now hold the hierarchy and labels. The generator reads them, and a small YAML file holds only the title keywords. The generator's output stayed byte-identical. | Me |
| Reused vocabularies | Declared by hand in `external-terms.ttl` instead of imported, so HermiT runs offline in about a second. | Me |
| Licensee names | A synthetic agreement keeps both the canonical licensee and the spelling it was written with. Each real notice licensee is its own node, and entity resolution in Gate 2 links them. | Me |
| Approval of bulk data | Two named standing policies approve public registry data and labeled synthetic data. The bulk-load policy never approves a fact that a language model extracted. | Me |
| Dependency pin | `kurra==3.0.5`, because pyLODE 3.6.0 imports a function that later kurra versions removed. | Me |
| UI libraries | D3 for graphs and hierarchies, Chart.js for charts, React and Vite for the app, hosted on Vercel in Gate 3. | You, with my choice of libraries |

### Not done, and why

- **The w3id.org persistent IRI.** Your spec asks for `https://w3id.org/gonogo/ontology#` to resolve to the
  documentation. That needs a pull request to the public `perma-id/w3id.org` repository, which is an
  outward-facing step. I did not open one. Until it exists, the namespace is an identifier and not a working
  link, and the reference documentation is in the repository.
- **A check of the whole graph by HermiT.** HermiT checks the ontology, the schemes, and the sample world. The
  build checks every individual in the real graph for disjointness, and SHACL checks its shape. A full
  description-logic check of 46,000 triples was not needed to find any of the errors above.
- **Field-of-use mapping for real notices.** Only 24 of 92 notices state a field. The graph records the others
  as unstated. Gate 2 adds the language-model proposal and the steward approval.

### Open questions for you

1. **The research from yesterday.** You mentioned research that should shape how the ontology work is
   presented. That session is not in this conversation, and I have no notes of it. If you paste the key
   points or give me a file path, I will check the guide and the visuals against them. Until then, the guide
   follows the PRD's modeling decisions and the W3C specifications.
2. **w3id.org and GitHub Pages.** Should I open the w3id.org pull request and enable GitHub Pages for the
   reference documentation? Both are public changes outside this repository.
3. **Vercel.** The public demo needs a Vercel account and a link between it and this repository. I plan to
   deploy the static views after Gate 2, and the snapshot mode in Gate 3. Say if you want the Gate 1 views
   deployed sooner.
4. **Gate 2 approval.** Gate 2 builds rules R1 to R7, the combiner, entity resolution, the request screen,
   the verdict card, the steward approval, and the rerun that explains what changed.

### Gate 2 preview

Gate 2 adds the seven rule functions as parameterized SPARQL templates plus Python, the decision combiner with
its versioned precedence file, the deterministic entity resolver with a 100-pair labeled set, the request
parser, and the local API. The UI gains the request screen, the verdict card with every finding and its source
clause, the steward queue, and the rerun view. The 44 injected cases become the regression suite.

## Gate 0: scaffold, ingestion, and synthetic data

**State:** complete and waiting for approval. Gate 1 has not started.
**Date:** 2026-10-24

### Deliverables

| Deliverable | Where | State |
|---|---|---|
| Repository scaffold with uv, Python 3.12, ruff, mypy, and pytest | `pyproject.toml`, `uv.lock`, one folder per area of the spec layout | Done |
| Docker compose with Fuseki and Neo4j | `docker-compose.yml` (Fuseki 5.1.0 with a `gonogo` dataset, Neo4j 5.26 Community) | Done; both containers start healthy |
| NASA Patents ingestion | `ingest/nasa_patents.py` | Done |
| NASA T2 portal ingestion | `ingest/t2_portal.py` | Done; the spec endpoint returns 404, so the module uses the fallback |
| Federal Register ingestion | `ingest/federal_register.py` | Done |
| USPTO legal status ingestion | `ingest/uspto.py` | Done; added on your instruction after a spot check. Needs `USPTO_API_KEY` in `.env`. |
| NTRS ingestion | `ingest/ntrs.py` | Done |
| Scope selection | `ingest/scope.py`, `data/scope/` | Done; 300 patents at three centers, 41 notices, in three passes |
| Synthetic generator | `synth/`, `data/synthetic/` | Done; 120 agreements as PDF and text, 44 injected cases |
| Data sources document with record counts | `docs/data-sources.md` | Done; a test regenerates and compares the counts |
| AWS settings, region guard, and model discovery | `config/aws.yaml`, `gonogo/aws.py`, `gonogo/preflight.py` | Done; read-only preflight passed |
| Cost controls for Gate 3 | `infra/` (CDK stub with deploy flags off), `scripts/teardown.sh` | Written; nothing is deployed |
| CI | `.github/workflows/ci.yml` | Written; it runs ruff, mypy, and the offline tests. It has not run on GitHub because the repository is not pushed. |

### Test results

| Suite | Command | Result |
|---|---|---|
| Lint and format | `uv run ruff check .` and `uv run ruff format --check .` | Pass |
| Types | `uv run mypy gonogo ingest synth` (strict) | Pass, 20 files |
| Offline unit tests | `uv run pytest` | 82 passed |
| Docker | `uv run pytest -m docker` | 2 passed (Fuseki insert and select, Neo4j Bolt) |
| Network | `uv run pytest -m network` | 6 passed (one live call per source, the T2 404 check, and the USPTO lapse check) |
| AWS | `uv run pytest -m aws` | 1 passed (read-only STS and Bedrock calls) |

Two further checks ran by hand:

- **Idempotency.** `python -m ingest all` ran twice in a row. The second run made 0 network calls, and every
  file under `data/processed/` and `data/scope/` came out byte-identical.
- **Determinism.** `python -m synth --seed 42` ran twice and produced identical SHA-256 hashes for every
  file, PDFs included.

### What the data showed

1. **The NASA dataset overstates how many patents are alive.** This is the main finding. Of the 263
   candidate patents that the NASA dataset calls in force on 2026-11-01 and that USPTO has a record for,
   USPTO shows **181 (69 percent) lapsed for unpaid maintenance fees**. Without the USPTO module, R1 would
   return PASS on each of them and the system could issue a GO on a dead patent. The first one I checked,
   US 8,077,103, lapsed on 2019-12-13 but the NASA dataset lists it as in force until 2027.
2. **The spec's patents JSON file is truncated.** It holds exactly 1,000 rows. The catalog's CSV export
   of the same dataset holds 1,393 rows, and GoNoGo uses the CSV.
3. **The NASA Patents dataset is about ten years old.** Its highest patent number is 8,679,642, which the
   USPTO issued in 2014, even though the catalog says the dataset was modified in May 2025. Only 33 percent
   of the 92 notices matched a patent in it. The spec's own example, US 9,297,368, is not in it.
4. **The "Application" status in the NASA dataset is stale.** The dataset lists 260 of the 724 candidate
   patents as applications, and USPTO shows that 208 of them have since been granted. Scope now counts a
   patent as issued when USPTO shows a grant.
5. **T2 closes part of the notice gap.** You approved adding the T2 patents at the three centers that
   notices name. The match rate rose from 33 to 52 percent, and in-scope notices rose from 23 to 41. 28
   in-scope patents have no USPTO record, mostly T2 provisional-only case numbers and old Kennedy filings.
6. **Five patents lapsed and were later reinstated** after USPTO accepted a late fee. The record keeps the
   lapse period, because third parties may hold intervening rights for acts during it. This gives the
   bitemporal model real retroactive changes, and one injected case tests it.
7. **96 candidate patents have a real co-assignee besides NASA**, such as the National Institute of
   Aerospace and Purdue Research Foundation. 53 candidates carry a terminal disclaimer, which can shorten
   their term below the date GoNoGo computes. The record flags both.
8. **Notices rarely state a field of use.** Only 24 of 92 notices state one. 53 say only "The fields of
   use may be limited." Since 2021, 52 notices offer "an exclusive, co-exclusive, or partially exclusive"
   license without choosing one. GoNoGo records both cases explicitly and does not guess.
9. **Two notices signal joint ownership** through "undivided interest in the jointly-owned inventions".
   The generator gives the matching in-scope patents a co-owner record.

### Repository

The repository is public at https://github.com/abh2050/gonogo. The first commit contains 329 files. Git
ignores `.env` and the 416 MB raw cache under `data/raw/`; `python -m ingest all` rebuilds the cache. The
commit uses your GitHub noreply address. `docs/prd.md` omits section 2 of the PRD, per your instruction.

### Decisions and deviations

These are the decisions you made on 2026-10-24, plus the choices I made during the build.

| Topic | Decision | Made by |
|---|---|---|
| Name and namespace | GoNoGo, `https://w3id.org/gonogo/ontology#` | You |
| Verdict precedence | GoNoGo spec: FAIL → NO GO, then PENDING → HOLD, REVIEW → COUNSEL, UNKNOWN → NO DATA, all PASS → GO | You |
| R1 derived expiry | GoNoGo spec: filing date plus 20 years, labeled derived, may produce PASS. With USPTO, the derived date uses the earliest non-provisional parent, the term adjustment, and the lapse history. | You |
| Other rule detail | PRD: the NOT_APPLICABLE status, R2 hierarchy overlap in both directions, R2 REVIEW on another party's proposed grant, the R3 cap with UNKNOWN, R4 REVIEW without a notice, complete or incomplete ownership records | You |
| USPTO source | First skipped, then added on 2026-10-24 after the spot check. R1 reads the USPTO state first and falls back to the NASA date only when USPTO has no record. | You |
| Patent master | NASA dataset plus T2 patents that notices name | You |
| T2 endpoint | The spec endpoint returns 404. The module uses `/api/api/patent/{query}` and the portal detail pages. | Me, as the spec allowed |
| Patents source of record | The full CSV export, because the spec's JSON file is truncated | Me |
| Fictional licensees | Agreements seeded from real notices copy the notice terms but name fictional licensees, so the public repository makes no false claims about real companies | Me |
| Partially exclusive versus exclusive | The spec places this conflict in R3. The adopted PRD rules place it in R2. The injected case records both (`spec_rule: R3`). | Me, following your PRD choice |
| Claude model selection | The newest `us.` profile in the family named in `config/aws.yaml`, set to Sonnet. On 2026-10-24 this resolves to `us.anthropic.claude-sonnet-5-5`. | Me |
| `boto3[crt]` | Added, because the `aws login` credential provider needs it | Me |
| USPTO key handling | The key sits in the git-ignored `.env` and travels as a header that the cache never stores. A test checks this. | Me |
| Scope fill order | Patents USPTO shows in force first, then patents the NASA dataset calls in force, then the rest | Me |
| Generator and real facts | The generator takes live test patents only from patents USPTO shows in force, and lists real USPTO co-assignees as co-owners instead of writing a contradicting record | Me |

### Region changes

No change was needed in Gate 0. No template, tutorial, or library default in this gate named another
region. `config/aws.yaml`, `gonogo/aws.py`, and `scripts/teardown.sh` all name us-east-2. The region guard
in `gonogo/aws.py` rejects every other region, including us-east-1 and us-west-2. A unit test fails if any
file outside this log and the guard names either denied region.

### Cost

- **AWS:** $0. The only AWS calls were two read-only API calls.
- **USPTO:** free. The module made about 1,400 calls against a weekly limit of 1.2 million.
- **Model calls:** none. I wrote the synthetic templates, licensee names, clause text, and hand labels in
  the session.

### Open questions for you

1. **Rotate the USPTO key.** The key was pasted into this chat, so it sits in the session transcript. The
   file `.env` holds it and git ignores that file. Regenerate the key at data.uspto.gov after Gate 0, and
   update `.env`.
2. **Real-notice rule cases.** The injected cases use real facts only for R1. Rule cases built on real
   notices need the field-of-use mapping from Gate 2, because most notices state no field. I plan to add
   them to the Gate 2 regression set.

### Gate 1 preview

Gate 1 covers the OWL 2 ontology, the SKOS field and territory schemes (seeded from
`synth/templates/fields.yaml` and `territories.yaml`), the SHACL 1.1 shapes, 15 competency questions with
SPARQL tests, ROBOT with HermiT in CI, pyLODE documentation, ADR 0001 on upper ontology alignment, owlrl
materialization, and the RDF load into the local Fuseki.
