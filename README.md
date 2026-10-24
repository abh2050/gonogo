# GoNoGo

GoNoGo answers patent license clearance questions for NASA's technology transfer office. A licensing
manager asks whether a company can license a patent for a field of use and a territory. GoNoGo returns
GO, NO GO, HOLD, COUNSEL, or NO DATA, and it shows the rule that decided, the evidence, and the source
clause behind each fact.

A deterministic rule engine decides every verdict from a W3C knowledge graph. A language model parses
requests, proposes facts from legal text, and writes explanations, but it never decides a verdict and it
never writes the queries that decide one.

> **Status:** Gate 0 of 4. The repository holds the scaffold, the data ingestion modules, and the synthetic
> data generator. The full README, with the business story, architecture, and benchmark, arrives in Gate 4.
> See [docs/status.md](docs/status.md).

## Data

GoNoGo uses real public data from five NASA and federal sources, including USPTO legal status, and labels every synthetic fact as
synthetic. [docs/data-sources.md](docs/data-sources.md) lists each source, the endpoint that worked, and
the record counts.

NASA does not publish executed license agreements, ownership records, or export classifications. The
generator in `synth/` creates them with a fixed seed. Every synthetic agreement names a fictional licensee
and carries the line "SYNTHETIC DOCUMENT" on its first page.

## Run it locally

```bash
uv sync
cp .env.example .env             # add USPTO_API_KEY from data.uspto.gov > My ODP
uv run python -m ingest all      # fetches and caches public data under data/raw/
uv run python -m synth --seed 42 # writes data/synthetic/
docker compose up -d --wait      # Fuseki on :3030, Neo4j on :7474 and :7687
uv run pytest                    # offline suite
uv run pytest -m docker          # needs the compose services
uv run pytest -m network         # live calls to the public sources
```

Local work costs nothing. AWS resources arrive in Gate 3 behind deploy flags, and `scripts/teardown.sh`
removes them after each session.
