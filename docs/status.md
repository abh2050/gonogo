# Status

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
