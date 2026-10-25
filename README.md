# GoNoGo

GoNoGo answers one question for NASA's technology transfer office: can this company license this patent,
for this field of use, in this territory, for this term? It answers GO, NO GO, HOLD, COUNSEL, or NO DATA, and
it shows the rule that decided, the facts that rule read, and the clause each fact came from.

Seven deterministic rules decide every verdict by querying a W3C knowledge graph through fixed SPARQL
templates. A missing fact gives NO DATA, never GO, and a proposed fact counts only after a person approves it.
A language model may help parse a request, but it never decides a verdict and never writes a query that
decides one; the public demo runs without one.

**Try it:** [gonogo-livid.vercel.app](https://gonogo-livid.vercel.app/#/ask). Pick "No export classification
yet", approve the proposed classification on the Steward page, and the verdict moves from NO DATA to GO, with
R5 named as the rule that changed. [docs/rules.md](docs/rules.md) walks through that example.

> **Status:** Gate 2 of 4 is complete: the rules, the combiner, entity resolution, the steward loop, and the
> live demo. Gate 3 deploys to AWS, and Gate 4 adds the benchmark. See [docs/status.md](docs/status.md).

## The ontology, in four places

| Read | What it gives you |
|---|---|
| [docs/ontology-guide.md](docs/ontology-guide.md) | The model on one page, each ontology construct with the test that proves it, and one real patent followed through the graph |
| [docs/modeling-decisions.md](docs/modeling-decisions.md) | Thirteen modeling decisions, each with the problem, the choice, the reason, the cost, and the evidence |
| [ontology/competency_questions.md](ontology/competency_questions.md) | Fifteen competency questions, each an executable SPARQL template with hand-worked answers |
| [docs/adr/0001-upper-ontology-alignment.md](docs/adr/0001-upper-ontology-alignment.md) | Why GoNoGo reuses PROV-O, SKOS, Dublin Core, and schema.org, and imports neither BFO, CCO, nor FIBO |

The machine-readable files live in [ontology/](ontology/) (OWL 2 and SKOS) and [shapes/](shapes/) (SHACL).
Generated reference documentation is in [docs/ontology/](docs/ontology/).

## See it

The [ui/](ui/) folder holds a React app that draws the ontology as a graph, shows how a grant for a broader
field covers the narrower ones, charts what the real data showed, and lets you drag a recording cutoff
through the bitemporal model. Its Ask, Steward, and History views call the API in [api/](api/), which runs
the real rule engine over a snapshot of the graph.

```bash
uv run uvicorn api.index:app --port 8000   # the API
cd ui && npm install && npm run dev         # the app, with /api forwarded to port 8000
```

[docs/public-demo.md](docs/public-demo.md) explains how the interactive demo keeps working after the AWS
stack is torn down.

## Data

GoNoGo uses real public data from five NASA and federal sources, including USPTO legal status, and labels
every synthetic fact as synthetic. [docs/data-sources.md](docs/data-sources.md) lists each source, the
endpoint that worked, and the record counts.

NASA does not publish executed license agreements, ownership records, or export classifications. The
generator in `synth/` creates them with a fixed seed. Every synthetic agreement names a fictional licensee
and carries the line "SYNTHETIC DOCUMENT" on its first page. In the graph, every synthetic fact carries
`prov:wasGeneratedBy` the generator run.

## Run it locally

```bash
uv sync
cp .env.example .env             # add USPTO_API_KEY from data.uspto.gov > My ODP
uv run python -m ingest all      # fetches and caches public data under data/raw/
uv run python -m synth --seed 42 # writes data/synthetic/
docker compose up -d --wait      # Fuseki on :3030, Neo4j on :7474 and :7687
uv run python -m kg all          # build the graph, materialize inference, run SHACL, load into Fuseki
uv run pytest                    # offline suite: shapes, competency questions, graph build
uv run pytest -m docker          # competency questions on a real Fuseki server
uv run pytest -m robot           # HermiT consistency checks (needs Java)
uv run pytest -m network         # live calls to the public sources
```

Local work costs nothing. AWS resources arrive in Gate 3 behind deploy flags, and `scripts/teardown.sh`
removes them after each session.
