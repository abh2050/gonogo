# Benchmark: rules over a graph, against a model reading documents

Does the ontology earn its place, or would a language model with good retrieval do as well? This benchmark asks the
same 200 clearance questions four ways and scores the answers against verdicts that were fixed by hand. Every
number below comes from [eval/results.md](../eval/results.md), which a script writes from the committed runs, and
the Benchmark page of the [live demo](https://gonogo-livid.vercel.app/#/benchmark) charts the same data.

## The result in one table

| | A. Vector RAG | B. Graph agent | C. Rules only | **C+. GoNoGo** |
|---|---:|---:|---:|---:|
| Verdict accuracy | 20.5% | 72.5% | 50.5% | **97.5%** |
| **False GO** (cleared a license it should not) | **14** | **32** | **0** | **0** |
| Missed GO (blocked a license it could clear) | 90.9% | 11.4% | 54.5% | 2.3% |
| Cites the agreement that decides the case | 21.4% | 91.1% | 48.2% | 100% |
| Median time per answer | 3.4 s | 25.2 s | 0.006 s | 1.6 s |
| Model cost for 200 questions | $1.04 | $4.35 | $0 | $0.20 |

C+ is GoNoGo as it would run in production: a model only reads the question into a form, every value must name a
concept the graph holds, and the seven rules decide. It was right on 195 of 200 questions, cleared nothing it should
not have, and cost about a tenth of a cent a question.

## What was compared

**The questions.** The synthetic generator planted 45 cases into the graph, each testing one thing: an overlapping
exclusive grant, a broader field that covers a narrower one, a lapsed patent, an open notice window, a missing
co-owner consent, a correction recorded after a cutoff, a planted instruction inside an agreement, and so on. Each
case's verdict was stated by hand when it was planted (`synth/generator.py`), never computed by the rule engine, so
scoring the engine against it is not circular. Each case is asked four ways: as the generator wrote it, casually,
as a terse note, and with irrelevant detail around it. Twenty more questions cannot be answered as asked, because a
required part is missing or the patent is not in scope; their right answer is NEEDS INFO.

Four wordings of one case are not four independent tests. The report gives a per-case score too: a case counts only
when all four wordings are right.

**The facts.** Every answerer sees the same information. The corpus for A and B (`eval/corpus.py`) holds 1,925
documents: a text card for every time-stamped fact in the approved graph, a card for every patent, the clause text of
every agreement and notice, and the first pages of 163 NASA technical reports. The cards are rendered from the graph,
so they say exactly what the rules read, including corrections and recording times. Royalty terms are excluded, as
they are everywhere outside the royalty graph.

**The answerers.** All four use Claude Haiku 4.5 on Amazon Bedrock at temperature 0, where they use a model at all.

- **A. Vector RAG.** The question goes to a Bedrock Knowledge Base on S3 Vectors (Titan embeddings). The 12 closest
  passages and the clearance policy, written in plain prose (`eval/policy.md`), go to the model, which fills a verdict
  form. This is the system a team would build first.
- **B. Graph agent.** A Strands agent with tools that call the rules' own SPARQL templates: find the patent, its
  records as of the cutoff, overlapping grants (with the field and territory hierarchies already applied), notices for
  the licensee, and passages filtered to the patent. Retrieval is exact. Applying the policy to what it retrieves is
  the model's job.
- **C. Rules only.** The fixed-pattern parser reads the question and the seven rules decide. No model.
- **C+. Rules with a model reader.** As C, but when the parser misses a part, the model fills a form. Every value it
  proposes must name a patent, concept, or date the graph holds, or it is dropped.

**The metrics.** A verdict counts when it matches exactly. A **false GO** is the worst error: it clears a license
that a conflict, a missing consent, or a lapsed patent should block. The build fails if C or C+ ever makes one
(`tests/eval/test_benchmark.py`). Citation precision is the share of cited documents about the question's patent.

## What the numbers show

### 1. Retrieval by similarity does not find clearance facts

Answerer A said NEEDS INFO to 139 of 200 questions, mostly about patents that are in the corpus. Its search returned
any record of the question's patent only 36% of the time. A clearance question reads like a license notice, so
the closest passages are other companies' notices, not this patent's legal status, ownership, and export records.
Filtering by patent fixes that (answerer B's search tool does it), but plain similarity search has no way to know
the patent is the key.

### 2. The right facts are not enough: models misapply the policy

Answerer B retrieved the decisive agreement 91% of the time and still made 32 false GOs, more than A. Its reasons
show why:

- **It misreads the exclusivity rule.** On INJ-007 it found the overlapping *exclusive* grant and wrote that "a
  non-exclusive request does not conflict" with it. The policy says the opposite, and the rule engine applies it the
  same way every time.
- **It treats a missing fact as a yes.** Eight false GOs came from patents with no ownership record (four) or with
  no dates at all (four), where the right answer is NO DATA. The open world assumption is easy to state in a
  prompt and hard for a model to hold.
- **It loses the hierarchy at the edges.** A request for a broad field that covers a narrower exclusive grant was
  cleared three times.

This is the argument for the ontology in one line: retrieval quality is not the bottleneck; applying the rules the
same way every time is.

### 3. A fixed parser is safe but brittle; letting a model read fixes that

Answerer C never made a false GO, because it refuses what it cannot parse. But it read only the formal wording: 0%
of the casual and terse questions. C+ lets a model fill the form and keeps the rules in charge, and it read every
wording: 100% on formal, casual, and terse, 89% on noisy, and every unanswerable question was refused.

### 4. Where GoNoGo itself was wrong

C+ missed 5 of 200, and none was a false GO. All five are the noisy wording, where irrelevant text came before the
request and the fixed parser could not find the licensee. Without the licensee's country, R5 (export) and R4 (the
notice window) cannot be confirmed, so the verdict fell to NO DATA or COUNSEL instead of the right answer. The system
erred toward caution, as it is designed to. A fix belongs in the parser, tested on new wordings, not on these.

### 5. Planted instructions

Two agreements carry text addressed to an AI reviewer, one telling it to mark every request GO. Both model answerers
gave false GOs on that case, but their written reasons cite the misread exclusivity rule above, not the planted text,
and B makes the same error on a case with no planted text. This benchmark cannot tell whether the instruction
contributed. The rule pipeline does not read agreement text as instructions at all, and the separate injection suite
(`docs/security-tests.md`) found that no model obeyed a planted instruction in 36 tries.

## Cost and speed

The whole benchmark cost about $5.60 in model calls on Claude Haiku 4.5. B was the most expensive and slowest,
because an agent makes four or five model calls per question. This account allows 10 Haiku requests a minute, so B
took about two hours. C+ was both the most accurate and the cheapest of the model-using answerers, because the model
reads a short question once, and only when the fixed parser cannot.

## What this does not show

- **The cases are synthetic and few.** 45 planted cases cover every rule and the hard edges of each, but they were
  written by the same project that wrote the rules. A real deployment would need cases written by licensing staff.
- **One model.** A larger model would likely do better as A or B. The point of the comparison is that GoNoGo does
  not depend on which model reads the question, because the model never decides.
- **The policy prompt is a summary.** A and B got the seven checks in prose. A longer prompt might help them; it would
  also be a second copy of the rules that can drift from the code.
- **A is a plain baseline.** Hybrid search, query rewriting, or a patent filter would help it. B is what a
  well-built retrieval system looks like, and it is the fairer comparison.

## Reproduce it

```bash
uv run python -m eval.golden                 # the 200 questions (committed)
uv run python -m eval.corpus                 # the 1,925 documents, built from the graph
uv run python -m eval.run C                  # no model, no cost
uv run python -m eval.run C+                 # about $0.20 on Haiku 4.5
# A and B need the gonogo-eval stack (cdk deploy gonogo-eval) and uv run python -m eval.kb
uv run python -m eval.run A
uv run --group agent python -m eval.run B
uv run python -m eval.score && uv run python -m eval.report
```

The runs append as they go, so `--resume` continues an interrupted run and `--retry-errors` answers only the
questions that failed.
