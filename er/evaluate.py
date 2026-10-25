"""Measure the resolver against the 100 hand-labeled name pairs: python -m er.evaluate [--write]

The thresholds were chosen on the development pairs. The test pairs were not used to choose anything, so the
test numbers are the ones to report. Two views of the same decisions:

  auto      the pair counts as "same" only when the resolver says match
  proposed  the pair counts as "same" when the resolver says match or ambiguous, because both reach a person
            or a link
"""

from __future__ import annotations

import json
from collections import Counter
from typing import Any

from er.resolver import compare
from gonogo.paths import DOCS, ROOT

PAIRS = ROOT / "er" / "labeled_pairs.jsonl"


def load() -> list[dict[str, Any]]:
    return [json.loads(line) for line in PAIRS.read_text().splitlines() if line.strip()]


def predictions(rows: list[dict[str, Any]]) -> list[tuple[dict[str, Any], str]]:
    return [(r, compare(r["a"], r["b"], r["address_a"], r["address_b"]).status) for r in rows]


def metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    preds = predictions(rows)

    def prf(positive: set[str]) -> dict[str, float | int]:
        tp = sum(1 for r, s in preds if s in positive and r["label"] == "same")
        fp = sum(1 for r, s in preds if s in positive and r["label"] == "different")
        fn = sum(1 for r, s in preds if s not in positive and r["label"] == "same")
        precision = tp / (tp + fp) if tp + fp else 1.0
        recall = tp / (tp + fn) if tp + fn else 1.0
        return {"tp": tp, "fp": fp, "fn": fn, "precision": round(precision, 3), "recall": round(recall, 3)}

    return {
        "pairs": len(rows),
        "same": sum(1 for r in rows if r["label"] == "same"),
        "different": sum(1 for r in rows if r["label"] == "different"),
        "outcomes": dict(Counter(s for _, s in preds)),
        "auto": prf({"match"}),
        "proposed": prf({"match", "ambiguous"}),
        "queue_size": sum(1 for _, s in preds if s == "ambiguous"),
        "errors": [
            {"id": r["id"], "a": r["a"], "b": r["b"], "label": r["label"], "predicted": s}
            for r, s in preds
            if (s == "match") != (r["label"] == "same")
        ],
    }


def report() -> dict[str, dict[str, Any]]:
    rows = load()
    official = [r for r in rows if r["split"] != "holdout"]
    splits = {s: metrics([r for r in rows if r["split"] == s]) for s in ("dev", "test", "holdout")}
    return splits | {"all": metrics(official)}


def markdown(rep: dict[str, dict[str, Any]]) -> str:
    def line(split: str, view: str) -> str:
        m = rep[split][view]
        return (
            f"| {split} | {view} | {rep[split]['pairs']} | {m['precision']:.2f} | {m['recall']:.2f} | "
            f"{m['tp']} | {m['fp']} | {m['fn']} |"
        )

    rows = [line(s, v) for s in ("dev", "test", "holdout", "all") for v in ("auto", "proposed")]
    return "\n".join(
        [
            "| Split | Decision counted as same | Pairs | Precision | Recall | TP | FP | FN |",
            "|---|---|---:|---:|---:|---:|---:|---:|",
            *rows,
        ]
    )


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true", help="write results to docs/entity-resolution-results.json")
    args = parser.parse_args()
    rep = report()
    print(markdown(rep))
    print("\nholdout pairs that the resolver did not match:")
    for e in rep["holdout"]["errors"]:
        print(f"  {e['id']} [{e['label']} -> {e['predicted']}] {e['a']!r} | {e['b']!r}")
    if args.write:
        (DOCS / "entity-resolution-results.json").write_text(json.dumps(rep, indent=2) + "\n")


if __name__ == "__main__":
    main()
