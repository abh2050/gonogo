# mappings

The contract between the relational tables that Snowflake holds and the ontology.

| File | What it is |
|---|---|
| `tables.py` | One specification of three tables (`patent_master`, `licensee`, `verdict_log`) that produces DDL for Snowflake, PostgreSQL, and SQLite, and reads patent and licensee rows from the built graph |
| `gonogo.r2rml.ttl` | The R2RML mapping that turns those tables into `gng:Patent`, `gng:Licensee`, and `gng:Decision` individuals, with the same IRIs the graph uses |
| `../service/snowflake.py` | The verdict writeback: one idempotent, atomic batch per call |

## What is proven

- **The mapping reproduces the graph.** Ontop materializes the mapping over PostgreSQL, and its triples equal the graph's
  for every column the mapping covers (1,853 triples, none extra). `tests/integration/test_ontop.py` runs it.
- **One exception, found by the test.** A company that two notices spell "La Mesa, CA" and "La Mesa, California" has
  two addresses in the graph and one column in the table, so one triple is absent from Ontop's output. The table
  takes the first in sorted order, and the test accepts a missing triple only for a multi-valued property.
- **A NULL column produces no triple.** An unstated patent number stays unstated.
- **A finance question is SPARQL.** The same test counts verdicts through Ontop's virtual graph over `verdict_log`
  and compares the counts with Python's.
- **The writeback is idempotent and atomic.** Writing twice leaves one row, a changed decision replaces its row, and
  a failure part way writes nothing (`tests/service/test_writeback.py`).

## What is not proven

- **A live Snowflake account.** None was available. The writeback uses `?` placeholders, which the Snowflake
  connector accepts with `paramstyle = "qmark"`, and the tests run it on SQLite. The Snowflake DDL is checked as
  text. Unquoted lowercase names should work on Snowflake, which folds them to upper case, but that has not been run.
- **Ontop on Fargate.** Ontop ran in Docker. The CDK stack does not define the service.
- **The nightly unload to Parquet in S3.** The PRD's path from Snowflake into the graph is not built. The graph is
  built from the public sources and the synthetic generator.
