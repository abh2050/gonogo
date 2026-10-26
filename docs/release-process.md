# Releasing a change to what GoNoGo decides

A one-line edit to a rule template can turn a GO into a NO GO for a request that someone already answered. The
release process exists so that nobody ships such an edit without seeing exactly which answers move, and so that
patent counsel, not the author, signs off on the move.

## What counts as a release

Any change to a file that can change a verdict. `release/bundle.py` lists them: the ontology, the SKOS schemes,
the SHACL shapes, the SPARQL rule templates, the rule code, the combiner policy, and the R2RML mapping. Their
SHA-256 hashes make a manifest, and the manifest has one digest that changes when any file does.

## The four steps

1. **Propose.** The author changes the files and runs `uv run python -m release impact --base origin/main`.
   The command checks out the base branch as a separate tree, builds the knowledge graph from each tree with its
   own ontology and rules, and evaluates the 45 injected cases in both. It writes `release/impact/<version>.json`.
2. **Read the impact report.** It lists every case whose verdict moves, every rule finding that changes, and for
   each change the files that could have caused it. "Could have" is deliberate: the report attributes a finding to
   the files its rule reads (`release/impact.py` holds the table), and it does not claim to prove the cause.
   The report also runs the regression gate. A case whose verdict no longer matches the recorded expectation fails it.
3. **Counsel approves.** `python -m release approve --as <name> --role counsel --reason "..." --proposer <author>`
   records the approval in `release/approvals/<version>.json`, bound to the report's digest. Cedar decides: an
   owner or counsel may approve, nobody approves a release they proposed, and an edited report invalidates every
   approval of the old one.
4. **Publish.** `python -m release publish --as <owner> --role ontology_owner` writes
   `release/published/<version>.json` with the bundle digest and both approvers. Cedar permits it only when the
   regression gate passed and counsel approved this exact report.

## What CI enforces

[.github/workflows/release.yml](../.github/workflows/release.yml) runs on every pull request that touches a bundle
file. It checks the ontology for consistency with HermiT, reruns the rule, authorization, leakage, and injection
suites, rebuilds the impact report from the base branch, and posts it on the pull request. It then runs
`python -m release check --recompute`, which fails when any of these is true:

- the committed report differs from the one CI just rebuilt, so the author changed something after reporting;
- the bundle changed after the report was made;
- the regression gate failed;
- counsel has not approved this report's digest.

## What the tests show

`tests/release/test_release.py` builds two real trees, one with a stricter combiner policy, and checks that the
report finds every moved verdict and names `config/precedence.yaml` for each. A comment-only change to a
template reports nothing and passes the gate. The approval tests cover the proposer, the missing counsel, the
failed gate, and the edited report.

## What this does not do

- **Identity is a name and a role that the pull request records.** A real deployment takes both from a signed-in
  user, as the AWS API does with Cognito, or from the reviewer of a GitHub pull request. With one maintainer on
  this repository, the process shows the mechanism and does not provide two real people.
- **Cause attribution is a candidate list.** Two changed files that both feed one rule cannot be told apart by
  this report. An ablation that applies each change alone would separate them and costs one evaluation per file.
- **The report covers 45 cases.** A verdict that moves for a request outside them does not appear.
