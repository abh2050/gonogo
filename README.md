# GoNoGo

GoNoGo answers patent license clearance questions for NASA's technology transfer office. A licensing
manager asks whether a company can license a patent for a field of use and a territory. GoNoGo returns
GO, NO GO, HOLD, COUNSEL, or NO DATA, and it shows the rule that decided, the evidence, and the source
clause behind each fact.

A deterministic rule engine decides every verdict from a W3C knowledge graph. A language model parses
requests, proposes facts from legal text, and writes explanations, but it never decides a verdict and it
never writes the queries that decide one.

> **Status:** Gate 1 of 4. The ontology, the SKOS vocabularies, the SHACL shapes, the competency questions,
> and the knowledge graph load are complete, and so are the visualizations. The rules, the request screen,
> and the verdict card arrive in Gate 2. The full README, with the business story, the architecture, and the
> benchmark, arrives in Gate 4. See [docs/status.md](docs/status.md).

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
through the bitemporal model.

```bash
cd ui && npm install && npm run dev
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
