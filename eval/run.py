"""Run one answerer over the golden set and write eval/runs/<answerer>.jsonl.

    uv run python -m eval.run C                 # the rule pipeline, no model calls
    uv run python -m eval.run A --limit 10      # a sample first, to measure tokens before a full run
    uv run python -m eval.run B --resume        # skip questions already answered

A run appends as it goes, so an interrupted run can resume without paying twice for the same question.
"""

from __future__ import annotations

import argparse
import json
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from eval.answer import Answer, RuleAnswerer
from gonogo.paths import ROOT

GOLDEN = ROOT / "eval" / "golden.jsonl"
RUNS = ROOT / "eval" / "runs"


def golden() -> list[dict[str, Any]]:
    return [json.loads(line) for line in GOLDEN.read_text().splitlines() if line.strip()]


def answerer(name: str) -> Callable[[dict[str, Any]], Answer]:
    if name == "C":
        return RuleAnswerer()
    if name == "C+":
        from eval.answer import ModelParsedRuleAnswerer

        return ModelParsedRuleAnswerer()
    if name == "A":
        from eval.rag import VectorAnswerer

        return VectorAnswerer()
    if name == "B":
        from eval.graph_agent import GraphAnswerer

        return GraphAnswerer()
    raise SystemExit(f"Unknown answerer {name}; use A, B, C, or C+.")


def patiently(run: Callable[[dict[str, Any]], Answer], q: dict[str, Any], tries: int = 6) -> Answer:
    """Bedrock throttles this account's Haiku quota under a steady stream of calls. Wait and try again, longer
    each time, before recording the question as an error."""
    for attempt in range(tries):
        try:
            return run(q)
        except Exception as e:
            if "Throttling" not in type(e).__name__ or attempt == tries - 1:
                raise
            time.sleep(15 * (attempt + 1))
    raise AssertionError("unreachable")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("answerer", choices=["A", "B", "C", "C+"])
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--workers", type=int, default=1, help="questions to answer at the same time")
    ap.add_argument("--only", help="a file of question ids, one per line; run just those")
    ap.add_argument("--retry-errors", action="store_true", help="answer again only the questions that errored")
    args = ap.parse_args()
    RUNS.mkdir(parents=True, exist_ok=True)
    out = RUNS / f"{args.answerer}.jsonl"
    done = set()
    if args.retry_errors and out.exists():
        kept = [
            line for line in out.read_text().splitlines() if line.strip() and json.loads(line)["verdict"] != "ERROR"
        ]
        out.write_text("".join(line + "\n" for line in kept))
        args.resume = True
    if args.resume and out.exists():
        done = {json.loads(line)["qid"] for line in out.read_text().splitlines() if line.strip()}
    elif out.exists():
        out.unlink()
    questions = [q for q in golden() if q["qid"] not in done]
    if args.only:
        wanted = set(Path(args.only).read_text().split())
        questions = [q for q in questions if q["qid"] in wanted]
    if args.limit:
        questions = questions[: args.limit]
    run = answerer(args.answerer)
    tokens_in = tokens_out = 0
    lock = threading.Lock()

    def one(q: dict[str, Any]) -> Answer:
        try:
            return patiently(run, q)
        except Exception as e:  # one failure is a result to report, not a reason to stop the run
            return Answer(q["qid"], args.answerer, "ERROR", error=f"{type(e).__name__}: {e}"[:500])

    with out.open("a") as f, ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(one, q): q for q in questions}
        for i, future in enumerate(as_completed(futures), 1):
            q, a = futures[future], future.result()
            with lock:
                f.write(json.dumps(a.to_dict()) + "\n")
                f.flush()
                tokens_in += a.tokens_in
                tokens_out += a.tokens_out
                mark = "ok " if a.verdict == q["expected_verdict"] else "   "
                print(f"{i:3}/{len(questions)} {mark}{q['qid']:28} want {q['expected_verdict']:10} got {a.verdict}",
                      flush=True)  # fmt: skip
    print(f"tokens in {tokens_in:,}, out {tokens_out:,}")


if __name__ == "__main__":
    main()
