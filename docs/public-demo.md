# The public demo

The AWS stack costs money while it runs, so the build deploys it, records evidence, and tears it down
(`scripts/teardown.sh`). A public demo must outlive that stack. This document explains how the demo keeps
working with no AWS account behind it.

## What a visitor can do

| Gate | Interactive features | Needs AWS |
|---|---|---|
| 1 | Explore the ontology graph, the field and territory hierarchies, the data findings, and the time model | No |
| 2 | Ask a clearance question, read the verdict card with every finding and source clause, approve a fact as a steward, and see the rerun explain what changed | No (runs on a laptop) |
| 3 | The same features on AWS, behind Cognito and Verified Permissions, for the security and leakage evidence | Yes, then torn down |
| 3 | The same features on Vercel in snapshot mode | No |
| 4 | The retrieval benchmark and the property graph comparison, as charts | No |

## Snapshot mode

Snapshot mode runs the real rule engine, not a copy of it written in another language.

1. **A frozen graph.** The build exports the release, approved, and candidate graphs as Turtle files into the
   Vercel deployment. The royalty graph never ships to the demo.
2. **A Python function.** A Vercel function loads the frozen graph with rdflib once per cold start, expands
   the same SPARQL templates from `kg/templates.py`, runs rules R1 to R7, and applies the same combiner policy
   as the AWS path. The function holds no state.
3. **The browser holds the session.** When a visitor approves a candidate fact as a steward, the browser keeps
   the approved fact and sends it with every later request. The function merges it into the in-memory graph,
   reruns the request, and returns the verdict with a diff against the previous one. A reload starts a fresh
   session.
4. **The same tests.** The 44 injected cases and the 15 competency questions run against the function in CI, so
   snapshot mode cannot drift from the engine that the AWS path uses.

If a Python function proves too slow on a cold start, the fallback is to run the engine in the browser with
Pyodide. The rule code stays the same.

## The language model in snapshot mode

A public demo must not spend money on every visit, and it must not let a visitor steer a model.

- **Parsing a question.** The request screen offers a structured form and a set of example questions. A
  deterministic parser handles the examples. Free-text parsing with Claude on Bedrock runs only on the AWS
  path, and the evaluation reports its accuracy against hand labels.
- **Explanations.** Snapshot mode shows the structured findings and the recorded explanations for the example
  cases. Each recorded explanation passed the citation checker when it was made.
- **Labeling.** The demo says which parts are recorded and which parts run live.

## What stays out of the demo

- The royalty graph and the agreement full text (modeling decision MD11).
- Any credential. The USPTO key and AWS profile are build-time inputs only.

## Cost

Vercel's free tier hosts the static app and one low-traffic function. The AWS stack stays behind its deploy
flags and a $50 budget alarm, and the teardown script verifies that nothing billable remains.
