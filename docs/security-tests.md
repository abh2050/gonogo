# What the security tests prove, and what they do not

Two suites run on every push and, with the AWS deployment up, against the real service. A failure in either fails
the build.

## The leakage suite

`tests/leakage/` attacks the query service as each of the six roles. The service is the only path to the graph. It
accepts a `SELECT` or `ASK`, requires `FROM` clauses, lets each `FROM` name only a graph that Cedar allows the
role to read, and refuses `GRAPH` patterns, `SERVICE`, `DESCRIBE`, `CONSTRUCT`, updates, and every graph store
operation.

The attacks include a query with no graph, a `FROM` hidden in a comment or a string, a `GRAPH` hidden in an
`OPTIONAL`, a `UNION`, a subselect, a `VALUES` clause, and a `FILTER EXISTS`, `SERVICE` with and without `SILENT`,
13 near-miss spellings of the royalty graph's name, two statements in one request, and every update form. Each
runs for every role. A second set reads everything a role may read and checks the results for royalty text: 240
long literals from the royalty graph, plus the phrases only a royalty clause contains.

The suite found one real mistake in its own markers. The ontology defines royalty terms in plain words ("the running
royalty as a percentage of net sales"), and a word match flagged the schema as a leak. The markers now match royalty
data, such as "a running royalty of 3.0", and the schema stays readable.

A suite that cannot fail proves nothing, so `test_the_suite_catches_a_service_that_skips_its_checks` removes the
service's validation and asserts that the suite sees the leak.

On AWS the same corpus ran through API Gateway: 500 queries, 382 refused, 0 leaked.

## The prompt-injection suite

`tests/injection/` plants instructions inside notice and agreement text and proves four things:

1. **A model that obeys still cannot decide anything.** A test model that obeys each of 12 planted instructions
   produces a proposal with its quote and the quote's position. The quote must appear in the notice and the
   concept must be in the field scheme. A proposal that passes goes to the steward queue, and no rule reads that
   queue. Removing the candidate graph entirely changes none of the 43 verdicts.
2. **Planted agreement text moves nothing.** Two agreements tell the extractor to record a termination or to call
   a license non-exclusive. The verdicts stay NO GO, the planted text sits in a clause of kind `injection` that no
   rule quotes, and no decision repeats it.
3. **A question with no request in it gets no verdict.** "Answer GO" returns an incomplete parse. A question that
   names two license types is not guessed, and the parser says so.
4. **The real model, measured once.** Sonnet 4.6 read 36 notices with a planted instruction (12 kinds on 3
   notices) and answered "none stated" every time. The raw results are in
   [injection-results.json](injection-results.json).

## What they do not prove

- **The measurement is small.** Zero obeyed in 36 allows a true rate of up to about 8 percent at the usual
  confidence. A better attacker, a longer notice, or a different model can do worse. The first claim above is the
  one to rely on: it holds whatever the model does.
- **A planted sentence can still reach a steward's screen.** The queue shows the quote and where it sits, and a
  steward still has to read it. The system lowers the cost of catching the attack and does not remove it.
- **The query service validates; Neptune does not.** Neptune's default graph is the union of all named graphs, so
  a bug in validation would expose them. The in-memory path also limits the data itself, which Neptune cannot,
  and that second layer is why the local suite and the live one differ in what they can show.
- **The deployed role comes from the token, and the demo's role is typed.** The public demo cannot show who a
  visitor is. The AWS path can.
