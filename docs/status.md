# Status

## Gate 4: the benchmark, the Neo4j comparison, ingestion, and the README

**State:** complete. The ingestion workflow ran live on AWS, and everything is torn down.
**Date:** 2026-10-26
**Live demo:** https://gonogo-livid.vercel.app/#/benchmark

Gate 4 answers the question the project exists to answer: does the ontology earn its place? On 200 clearance
questions scored against hand-stated verdicts, GoNoGo was right 97.5% of the time and never cleared a license it
should not have. A graph agent with the same facts was right 72.5% of the time and cleared 32 it should not have; a
vector RAG baseline was right 20.5% of the time. The Neo4j comparison, the agreement ingestion workflow, seven draw.io
AWS diagrams, and the final README are done. The ingestion workflow also ran live on AWS: an agreement PDF went through Textract, extraction,
SHACL, a steward's approval, and the write to Neptune, and one booked request moved from GO to NO GO.

### Deliverables

| Deliverable | Where | State |
|---|---|---|
| Golden question set | `eval/golden.py`, `eval/golden.jsonl` | Done. 45 planted cases × 4 wordings + 20 unanswerable. Verdicts come from the planted cases, never the engine. |
| Document corpus | `eval/corpus.py` | Done. 1,925 documents rendered from the graph and the source texts; royalty terms excluded. |
| Answerer A, vector RAG | `eval/rag.py`, `gonogo-eval` stack (Bedrock Knowledge Base on S3 Vectors) | Done. 200 questions. |
| Answerer B, graph agent | `eval/graph_agent.py`, `eval/graph_tools.py` (Strands, the rules' SPARQL templates as tools) | Done. 200 questions, run locally. |
| Answerers C and C+ | `eval/answer.py` | Done. C+ is the deployed pipeline with the optional model reader on. |
| Results and report | `eval/results.md`, `docs/benchmark.md`, the Benchmark page | Done. CI fails on any false GO by C or C+ and on drift between runs and report. |
| Neo4j comparison and ADR 0003 | `pgraph/`, `docs/adr/0003-rdf-versus-property-graph.md` | Done. Same grants on 1,435 of 1,435 requests; a CI test repeats it. |
| Ingestion workflow | `service/ingest.py`, the ingestion block of `ApiStack`, `docs/ingestion.md`, `docs/ingestion-run.json` | Done. Tested locally, then run live on AWS with both sample agreements. |
| AWS diagrams | `docs/architecture/` (seven draw.io views) | Done. |
| README, final form | `README.md`, `docs/media-rights.md` | Done: the business story, the verdict flow, the architecture, the benchmark table, and what carries over to media rights. |

### Test results

- Offline suite: 1,111 passed, 1 skipped (`uv run pytest`).
- Docker: the Neo4j agreement test and the Ontop tests pass (5 passed).
- CI: green on all five jobs for the last pushed commit.
- The ingestion extractor reads 101 of the 120 synthetic agreements exactly and refuses the other 19 for a person;
  it reads none wrong. A test requires that.

### What the work found

1. **Models misapply the policy to the right facts.** The graph agent retrieved the decisive agreement 91% of the
   time and still made 32 false GOs: it read "an exclusive grant blocks any overlapping request" as not blocking a
   non-exclusive one, and it treated a missing ownership record or missing dates as a yes.
2. **Similarity search misses clearance facts.** The vector baseline found any record of the question's patent only
   36% of the time and answered NEEDS INFO to 139 of 200 questions.
3. **The fixed parser is safe and brittle.** Rules only (C) never erred toward GO but read 0% of casual or terse
   wordings. Letting a model fill the form (C+) fixed that and kept the false-GO count at zero.
4. **GoNoGo's own five misses** are all the noisy wording, where the parser could not find the licensee. Each fell to
   NO DATA or COUNSEL, never GO.
5. **Two engine bugs.** Approving a fact did not store the inferences the build materializes, so a newly approved
   grant was invisible to R2; approvals now store them. And rdflib's SPARQL parser raced when two API threads parsed
   their first query together; a lock fixed it, with a test that fails without it.
6. **A property graph fails quietly.** The first Neo4j load used the wrong scheme IRIs, and every R2 query returned
   nothing with only a warning. RDF would have failed the shape checks. ADR 0003 records this.

### Decisions and deviations

- **Answerer A's corpus** holds every fact as text, not only NTRS passages as the spec says, so A sees the same
  information as the other answerers and the comparison measures method, not missing data.
- **Haiku 4.5 for every model call**, as you chose. The account allows 10 Haiku requests a minute; an increase must be
  requested through AWS Support, so the agent run took about two hours.
- **ADR 0003, not 0002.** The build plan called the property graph ADR 0002; separation of duties took that number.
- **The Strands agent runs in process, not on Fargate.** The VPC has no NAT or interface endpoints, so a Fargate task
  there could not reach Bedrock without adding paid networking and breaking that design rule.
- **The ingestion extractor uses fixed patterns, not a model.** It refuses free-text fields of use for a person to map.

### AWS spend

| Item | Spend |
|---|---|
| Benchmark model calls (Haiku 4.5, from the runs' token counts) | $5.59: A $1.04, B $4.35, C+ $0.20 |
| Smoke tests, the stopped sample runs, and quota retries | under $1, estimated |
| Titan embeddings for 1,925 documents (about a million tokens) | about $0.02 |
| S3 Vectors and the corpus bucket | cents |
| **Gate 4 total** | **about $7**, estimated |

Cost Explorer had not posted 2026-10-26 when this was written. `uv run python -m scripts.aws_spend 2026-10-26
2026-10-28` gives the measured figure the next day. The budget stays at $10 a month, as you chose.

### What is still deployed

- `gonogo-eval` (the Knowledge Base, S3 Vectors, and the corpus bucket): about a cent a day of storage. It goes when
  you approve the teardown at the end of the gate.
- `gonogo-budget` and two KMS keys pending deletion, as after Gate 3.

### Open questions for you

1. **Run the ingestion workflow on AWS?** It needs gonogo-core and gonogo-api with Neptune for about an hour (about
   $1 to $2), then a full teardown. It would add a live execution record and Step Functions screenshots.
2. **Tear down `gonogo-eval` now,** or keep it while you look at the Benchmark page?
3. **The overview video** describes the loader as Neptune's only writer, which the ingestion step changed. Rebuild the
   video with the corrected line and the new diagrams?

## Gate 3: the two-person rule, the AWS deployment, the leakage and injection suites, Ontop, and releases

**State:** complete and waiting for approval. Gate 4 has not started.
**Date:** 2026-10-25
**Live demo:** https://gonogo-livid.vercel.app/#/steward

Gate 3 is done, with two gaps you should weigh before approving Gate 4. First, no Snowflake account was available,
so the writeback ran against SQLite and Ontop ran against PostgreSQL. Second, I did not build the Fargate agent,
the Textract and Step Functions ingestion path, or the Guardrails layer, because your Gate 3 scope did not list
them. Everything else in your scope is built and was checked, and the AWS stack is torn down. The deployment cost
under $2 by my estimate and about $0.68 of Bedrock calls; see "AWS spend" for what is measured and what is not.

### Deliverables

| Deliverable | Where | State |
|---|---|---|
| Field-of-use extraction for the 68 notices | `agent/field_extractor.py`, `data/processed/field_proposals.jsonl` | Done. 65 notices name no field, 3 got a proposal, and 2 of those enter the steward queue (the third notice has no grant node). Each proposal carries the model ID, the prompt version, and the notice's own words. |
| The two-person rule | `authz/`, `kg/actions.py`, `kg/governance.py`, [ADR 0002](adr/0002-separation-of-duties.md) | Done. A conflicting approval, or one that would move a verdict from COUNSEL or NO GO to GO, waits for counsel. Nobody approves what they proposed. |
| The decoy in the injected suite | INJ-045 in `data/synthetic/injected_conflicts.json` | Done. It passes only when the approval cannot produce GO without a second approver. |
| Cedar for every role and every action | `authz/policies/gonogo.cedar` (21 policies), `authz/gonogo.cedarschema.json` | Done. Six roles, 21 actions, validated against a schema. |
| Leakage suite, every role | `tests/leakage/` | Done. 338 offline attacks, and 500 queries through the deployed gateway. |
| Prompt-injection suite | `tests/injection/`, `agent/injection.py` | Done. 41 offline tests, and 36 live calls to the model. |
| CDK in Python | `infra/` | Done. Three stacks, 18 template assertions, deployed and checked. |
| Query service with a graph allowlist | `service/query.py`, `service/handler.py` | Done. |
| Snowflake writeback and R2RML mapping with Ontop | `mappings/`, `service/snowflake.py` | Built and tested, not live. See above. |
| Release workflow with impact report and counsel approval | `release/`, `.github/workflows/release.yml`, [docs/release-process.md](release-process.md) | Done. |
| Teardown and the budget alarm | `scripts/teardown.py`, `infra/stacks.py` | Done. |
| The demo still runs without AWS | `vercel.json`, `api/` | Done. Checked after the push. |

### Test results

| Suite | Command | Result |
|---|---|---|
| Lint, format, types | `ruff check`, `ruff format --check`, `mypy` (strict, 82 files) | Pass |
| Offline | `uv run pytest` | 1,079 passed |
| Fuseki, Ontop, and the endpoint store | `uv run pytest -m docker` | 50 passed, including all 88 decisions equal over HTTP and an Ontop finance query |
| HermiT | `uv run pytest -m robot` | 6 passed |
| AWS, against the deployment | `uv run python infra/evidence.py` | 11 of 11 checks passed ([aws-evidence.json](aws-evidence.json)) |
| UI | `npm run build` | Pass |

### What the work found

1. **A wrong approval is now held, and the test proves it.** Approving the decoy as one steward leaves the
   verdict at COUNSEL, adds no fact, and waits. A second steward and the first approver are both refused. A different
   counsel approves, and the verdict becomes GO. The same sequence passed on AWS with five real Cognito users.
2. **Writing the model-proposal test found a bug in my own shape.** The new shape for a field-of-use assignment
   demanded that its generating activity be an `Extraction`. That holds for the candidate and not for the approved
   copy, which an approval action generates, so SHACL rejected every approval. Approving one on the real data
   now moves R2 from REVIEW to PASS for an unrelated field, and a test covers it.
3. **The disjointness check caught a modeling error.** My first draft gave an assignment the property
   `gng:fieldOfUse`, whose domain is `gng:Grant`, and the build refused to load an individual that was both. The
   assignment has its own property now (MD14).
4. **The model rarely names a field, and what it names is weak.** Of 68 notices, 65 say only that fields "may be
   limited". The 3 proposals quote the description of an invention ("Aerogel/Polymer Composite Materials") and not
   a stated field of use. The queue shows the quote so a steward can decide, and I would not approve them without
   reading the notice.
5. **The real model ignored all 36 planted instructions.** That is small: it allows a true rate near 8 percent.
   The claim to rely on is the code-level one, that a proposal can only reach a queue that no rule reads.
6. **Listing a Claude model does not mean the account may call it.** Sonnet 5.5 is listed and denied. Discovery
   now probes, and today picks Sonnet 4.6.
7. **A decision on Neptune is the same decision.** All 43 signatures match, and so do 45 injected cases at their own
   cutoffs on Fuseki. The query templates needed no change.
8. **A teardown can leave things behind without saying so.** The first run failed on a bucket without Object Lock,
   and the report missed a KMS key because it looked for a description the key never had. Both are fixed and tested.
9. **A data question surfaced through the mapping.** One company is spelled "La Mesa, CA" in one notice and "La Mesa,
   California" in another. The graph keeps both and a table column holds one. The test states this exception.
10. **A parser weakness surfaced through the injection tests.** A question naming two license types was resolved
    silently by taking the first. It now reports the ambiguity and asks.

### Decisions and deviations

| Topic | Decision | Made by |
|---|---|---|
| Field-of-use extraction | Built first, as you asked. The model may answer "none stated", and code checks the concept and the verbatim quote. | You, with my design |
| Model | `us.anthropic.claude-sonnet-4-6`, because it is the newest Sonnet this account can call | Me |
| Budget | $10, as you set it. It counts the eight AWS services that only GoNoGo uses, because this account cannot use cost tags and another project's spend already passes $10. Bedrock is outside it. | Me |
| Budget email | The alerts go to the address on your Claude account. I put it in the deployed stack and not in the repository. | Me, tell me if you want another |
| Role per user | A Cognito user must belong to exactly one role group, so no one can play both parts of a two-person rule | Me |
| Verified Permissions vs. local Cedar | The Lambdas evaluate the policies in process, and Verified Permissions holds the same text, checked equal on 126 questions. This avoids interface endpoints and their cost. | Me |
| Release approvals | Recorded in the repository, bound to the report's digest, and decided by Cedar. A single maintainer cannot supply two people. | Me |
| CI | Added an Ontop job and the endpoint-store test to the Fuseki job, and a release workflow for pull requests | Me |
| `scripts/teardown.sh` | Replaced by `scripts/teardown.py`, which can empty an Object Lock bucket | Me |

### AWS spend

- **Bedrock, estimated:** about $0.68, from token counts at $3 and $15 per million tokens, which is the list price I
  assumed and did not look up. Field-of-use extraction used 129,848 input and 3,433 output tokens across 71 calls (68
  plus 3 retries). The injection measurement used 69,597 and 1,800 across 36 calls. The model probes cost a few tokens.
- **Infrastructure, estimated:** under $2. The Neptune cluster ran about 80 minutes at 1 NCU, and the other
  services cost cents.
- **Measured:** not yet. Cost Explorer returned nothing for 2026-10-25 when I asked. Run
  `uv run python scripts/aws_spend.py 2026-10-25 2026-10-27` tomorrow for the real figure.

### What the teardown left behind

| Resource | Why |
|---|---|
| The `gonogo-budget` stack and the `gonogo-monthly` budget | Free, and kept on purpose |
| One KMS key, pending deletion until 2026-11-01 | KMS enforces a seven-day wait. It is not billed while it waits. |

Nothing that bills remains ([aws-teardown.json](aws-teardown.json)). Three other KMS keys that wait for deletion
belong to a different project in the account, and I did not touch them.

### Not done, and why

- **Live Snowflake.** No account. [mappings/README.md](../mappings/README.md) says what is and is not proven.
- **The Fargate agent, ingestion workflow, and Guardrails.** Not in your scope list. [docs/aws.md](aws.md) lists
  every gap.
- **Ontop on Fargate.** It ran in Docker.
- **Deploying from CI.** Deploys come from a laptop. A GitHub OIDC role is not set up.
- **The release gate with two real people.** One maintainer uses the mechanism and cannot show it.

### Open questions for you

1. **Snowflake.** Do you have an account or a trial I can use? With one, I would run the DDL, the writeback, and Ontop
   against it, and move the "not live" caveat.
2. **The agent and the ingestion path.** Should Gate 4 include the Strands agent on Fargate and the Step Functions
   approval workflow, or does the benchmark come first?
3. **The budget address.** Is the Claude account's address the right place for budget alerts?
4. **Gate 4 approval.** Gate 4 covers the GraphRAG benchmark, ADR 0003 on RDF versus a property graph, the
   results file, and the README.

### Gate 4 preview

The benchmark compares the rule engine with retrieval-augmented answers over the same questions, measures what the
model adds, runs the same graph in Neo4j, and writes `eval/results.md`. ADR 0003 records the RDF versus property
graph decision. The README then gets its final form, with the numbers.

## Gate 2: rules, verdicts, entity resolution, the steward loop, and the live demo

**State:** approved.
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
release workflow. Each deployment session ends with `scripts/teardown.py`.

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
