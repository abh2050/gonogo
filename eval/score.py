"""Score every answerer's run against the golden set and write eval/results.json.

    uv run python -m eval.score

Metrics, for each answerer:

- accuracy: the verdict matches the expected one exactly.
- false GO rate: of the questions whose answer is not GO, the share answered GO. A false GO is the worst failure:
  it clears a license that should not be granted. Any false GO by answerer C fails the build (tests/eval).
- missed GO rate: of the questions whose answer is GO, the share answered with anything else. This costs time,
  not rights.
- citation precision: of the documents an answer cites, the share that are about the question's patent or were
  planted for its case.
- decisive recall: for cases decided by a conflicting agreement, the share of answers that cite that agreement.
- per-case accuracy: a case counts only when all four wordings of it get the right verdict.
- latency and model cost.
"""

from __future__ import annotations

import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from eval.run import RUNS, golden
from gonogo.paths import ROOT

OUT = ROOT / "eval" / "results.json"
NAMES_ORDER = ["A", "B", "C", "C+"]
# Claude Haiku 4.5 on Bedrock, US dollars per million tokens (on-demand, us-east-2, October 2026).
PRICE_IN, PRICE_OUT = 1.0, 5.0


def doc_patents() -> dict[str, set[str]]:
    from eval.corpus import patent_map

    return {doc: set(patents) for doc, patents in patent_map().items()}


FAMILIES = {
    "r1": "R1 patent in force",
    "r2": "R2 overlapping grants",
    "r3": "R3 co-exclusive cap",
    "r4": "R4 notice window",
    "r5": "R5 export control",
    "r6": "R6 co-owner consent",
    "temporal": "Terms in time",
    "retroactive": "Corrections",
    "combiner": "Combiner order",
}


def family(q: dict[str, Any]) -> str:
    """The group a question belongs to, for the per-family accuracy chart."""
    if q["style"] == "unanswerable":
        return "Unanswerable"
    t = q["case_type"]
    if t.startswith("prompt_injection") or t.startswith("decoy"):
        return "Planted instructions"
    if t in ("baseline_go", "exclusive_never_go", "steward_rerun", "demo_blocked_with_secondary"):
        return "Baselines and steward loop"
    return FAMILIES.get(t.split("_")[0], "Other")


def tail(doc: str) -> str:
    return doc.rstrip("/").rsplit("/", 1)[-1]


def pct(n: float, d: float) -> float | None:
    return round(100 * n / d, 1) if d else None


def score(answers: list[dict[str, Any]], qs: dict[str, dict[str, Any]], patents: dict[str, set[str]]) -> dict[str, Any]:
    right = [a for a in answers if a["verdict"] == qs[a["qid"]]["expected_verdict"]]
    not_go = [a for a in answers if qs[a["qid"]]["expected_verdict"] != "GO"]
    is_go = [a for a in answers if qs[a["qid"]]["expected_verdict"] == "GO"]
    precision: list[float] = []
    decisive_hits = decisive_total = 0
    for a in answers:
        q = qs[a["qid"]]
        cited = set(a["citations"])
        if q["patent_key"] and cited:
            planted = set(q["planted_evidence"])
            ok = [c for c in cited if q["patent_key"] in patents.get(c, set()) or tail(c) in planted]
            precision.append(len(ok) / len(cited))
        if q["decisive_evidence"]:
            decisive_total += 1
            decisive_hits += any(tail(c) in q["decisive_evidence"] for c in cited)
    by_case: dict[str, list[bool]] = defaultdict(list)
    for a in answers:
        by_case[qs[a["qid"]]["case_id"]].append(a["verdict"] == qs[a["qid"]]["expected_verdict"])
    by_style: dict[str, list[bool]] = defaultdict(list)
    for a in answers:
        by_style[qs[a["qid"]]["style"]].append(a["verdict"] == qs[a["qid"]]["expected_verdict"])
    by_family: dict[str, list[bool]] = defaultdict(list)
    for a in answers:
        by_family[family(qs[a["qid"]])].append(a["verdict"] == qs[a["qid"]]["expected_verdict"])
    searched = [a for a in answers if a["answerer"] == "A" and qs[a["qid"]]["patent_key"]]
    hits = sum(any(qs[a["qid"]]["patent_key"] in patents.get(d, set()) for d in a["retrieved"]) for a in searched)
    lat = [a["latency_s"] for a in answers if a["verdict"] != "ERROR"]
    t_in = sum(a["tokens_in"] for a in answers)
    t_out = sum(a["tokens_out"] for a in answers)
    confusion = Counter((qs[a["qid"]]["expected_verdict"], a["verdict"]) for a in answers)
    return {
        "questions": len(answers),
        "accuracy": pct(len(right), len(answers)),
        "false_go": [a["qid"] for a in not_go if a["verdict"] == "GO"],
        "false_go_rate": pct(sum(a["verdict"] == "GO" for a in not_go), len(not_go)),
        "missed_go_rate": pct(sum(a["verdict"] != "GO" for a in is_go), len(is_go)),
        "citation_precision": round(100 * statistics.mean(precision), 1) if precision else None,
        "decisive_recall": pct(decisive_hits, decisive_total),
        "cases": len(by_case),
        "case_accuracy": pct(sum(all(v) for v in by_case.values()), len(by_case)),
        "accuracy_by_style": {s: pct(sum(v), len(v)) for s, v in sorted(by_style.items())},
        "accuracy_by_family": {f: [sum(v), len(v)] for f, v in sorted(by_family.items())},
        "retrieval_hit_rate": pct(hits, len(searched)) if searched else None,
        "errors": sum(a["verdict"] == "ERROR" for a in answers),
        "latency_p50_s": round(statistics.median(lat), 3) if lat else None,
        "latency_p95_s": round(sorted(lat)[int(0.95 * (len(lat) - 1))], 3) if lat else None,
        "model_calls": sum(a.get("model_calls", 0) for a in answers),
        "tokens_in": t_in,
        "tokens_out": t_out,
        "model_cost_usd": round(t_in / 1e6 * PRICE_IN + t_out / 1e6 * PRICE_OUT, 4),
        "confusion": {f"{e} -> {g}": n for (e, g), n in sorted(confusion.items())},
    }


def main() -> dict[str, Any]:
    qs = {q["qid"]: q for q in golden()}
    patents = doc_patents()
    out: dict[str, Any] = {}
    for run in sorted(RUNS.glob("*.jsonl")):
        answers = [json.loads(line) for line in run.read_text().splitlines() if line.strip()]
        out[run.stem] = score(answers, qs, patents)
    OUT.write_text(json.dumps(out, indent=1) + "\n")
    pgraph = ROOT / "pgraph" / "results.json"
    page = {
        "answerers": out,
        "golden": {
            "questions": len(qs),
            "cases": len({q["case_id"] for q in qs.values()}),
            "verdicts": dict(Counter(q["expected_verdict"] for q in qs.values())),
        },
        "pgraph": json.loads(pgraph.read_text()) if pgraph.exists() else None,
    }
    (ROOT / "ui" / "public" / "data" / "benchmark.json").write_text(json.dumps(page, indent=1) + "\n")
    return out


if __name__ == "__main__":
    for name, s in main().items():
        print(name, {k: v for k, v in s.items() if k not in ("confusion", "false_go")}, "false GO:", s["false_go"])
    print("wrote", Path(OUT).relative_to(ROOT))
