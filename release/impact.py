"""The impact report: what a proposed bundle changes, compared with the bundle that is live.

Both trees are built and evaluated by the same script, in their own directory, so each uses its own ontology,
rules, templates, and combiner policy. The report lists every request whose verdict changes, every finding that
changes, and for each change the changed files that the rule reads. Those files are candidates for the cause, and
the report says so: it does not claim proof.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from release import bundle

SCRIPT = r"""
import json, sys
from pathlib import Path
from kg import build, materialize
from kg.store import Store
from kg.ns import GRAPH_ROYALTY
from rules.engine import evaluate
from rules.model import Request

root = Path(".")
graphs = build.build_graphs()
materialize.apply(graphs)
store = Store({k: v for k, v in graphs.items() if k != GRAPH_ROYALTY})
requests = {}
for line in (root / "data/synthetic/requests.jsonl").read_text().splitlines():
    r = json.loads(line)
    requests[r["request_id"]] = Request(
        patent_key=r["patent_key"], exclusivity=r["exclusivity"], field=r["field_concept"], territory=r["territory"],
        start=r["start"], end=r["end"], licensee_name=r["text"].split(" wants")[0],
        licensee_ids=("https://w3id.org/gonogo/id/licensee/" + r["licensee_id"],),
        licensee_country=r["licensee_country"],
    )
cases = json.loads((root / "data/synthetic/injected_conflicts.json").read_text())["cases"]
out = {"decisions": {}, "expected": {}}
for c in cases:
    key = c["case_id"]
    try:
        d = evaluate(store, requests[c["request_id"]], cutoff=c["recording_cutoff"], as_of=c["as_of"])
        out["decisions"][key] = {
            "request_id": c["request_id"], "type": c["type"], "verdict": d.verdict, "signature": d.signature,
            "findings": {f["rule"]: {"status": f["status"], "summary": f["summary"]} for f in d.findings},
        }
    except Exception as e:
        out["decisions"][key] = {
            "request_id": c["request_id"], "type": c["type"], "verdict": "ERROR", "error": str(e)[:200],
        }
    out["expected"][key] = c["expected_verdict"]
json.dump(out, sys.stdout)
"""

# Which bundle files can change a rule's finding. A change to any other file cannot be the cause.
SHARED = ["rules/engine.py", "rules/context.py", "rules/common.py", "ontology/gonogo.ttl", "shapes/*"]
RULE_FILES = {
    "R1": ["rules/r1_legal_status.py", "rules/templates/r1_*"],
    "R2": [
        "rules/r2_exclusivity.py",
        "rules/templates/r2_*",
        "ontology/schemes/fields.ttl",
        "ontology/schemes/territories.ttl",
        "ontology/schemes/exclusivity.ttl",
    ],
    "R3": [
        "rules/r3_cap.py",
        "rules/r2_exclusivity.py",
        "rules/templates/r2_*",
        "rules/templates/clauses.rq",
        "ontology/schemes/fields.ttl",
        "ontology/schemes/territories.ttl",
    ],
    "R4": ["rules/r4_notice.py", "rules/templates/r4_*", "rules/templates/licensee_identity.rq"],
    "R5": ["rules/r5_export.py", "rules/templates/r5_*", "ontology/schemes/territories.ttl"],
    "R6": ["rules/r6_consent.py", "rules/templates/r6_*"],
    "R7": ["rules/r7_statutory.py"],
}
COMBINER = ["config/precedence.yaml", "rules/policy.py"]


def evaluate_tree(root: Path) -> dict[str, Any]:
    env = {**os.environ, "PYTHONPATH": str(root), "PYTHONDONTWRITEBYTECODE": "1"}
    out = subprocess.run([sys.executable, "-c", SCRIPT], cwd=root, env=env, capture_output=True, text=True, check=False)
    if out.returncode != 0:
        raise RuntimeError(f"Evaluating {root} failed:\n{out.stderr[-1500:]}")
    return dict(json.loads(out.stdout))


def _matches(path: str, patterns: list[str]) -> bool:
    return any(re.fullmatch(p.replace(".", r"\.").replace("*", ".*"), path) for p in patterns)


def causes(rule: str | None, touched: list[str]) -> list[str]:
    """Changed files that this rule, or the combiner when `rule` is None, depends on."""
    deps = COMBINER if rule is None else RULE_FILES.get(rule, []) + SHARED
    return [f for f in touched if _matches(f, deps)]


def report(base_root: Path, new_root: Path) -> dict[str, Any]:
    base_m, new_m = bundle.manifest(base_root), bundle.manifest(new_root)
    diff = bundle.changed(base_m, new_m)
    touched = bundle.touched(diff)
    before, after = evaluate_tree(base_root), evaluate_tree(new_root)
    verdicts, findings = [], []
    for case, b in sorted(before["decisions"].items()):
        a = after["decisions"].get(case)
        if a is None:
            continue
        if a["verdict"] != b["verdict"]:
            verdicts.append(
                {
                    "case": case,
                    "type": b["type"],
                    "from": b["verdict"],
                    "to": a["verdict"],
                    "cause_candidates": sorted(
                        set(sum((causes(r, touched) for r in RULE_FILES), causes(None, touched)))
                    ),
                }
            )
        for rule in sorted(set(b.get("findings", {})) | set(a.get("findings", {}))):
            fb, fa = b.get("findings", {}).get(rule), a.get("findings", {}).get(rule)
            if fb != fa:
                findings.append(
                    {
                        "case": case,
                        "rule": rule,
                        "from": (fb or {}).get("status"),
                        "to": (fa or {}).get("status"),
                        "summary_changed": (fb or {}).get("summary") != (fa or {}).get("summary"),
                        "cause_candidates": causes(rule, touched),
                    }
                )
    unexpected = [c for c, d in after["decisions"].items() if d["verdict"] != after["expected"][c]]
    out = {
        "base": {"version": base_m["version"], "digest": base_m["digest"]},
        "proposed": {"version": new_m["version"], "digest": new_m["digest"]},
        "changed_files": diff,
        "cases_evaluated": len(after["decisions"]),
        "verdicts_changed": verdicts,
        "findings_changed": findings,
        "gate": {
            "regression_passed": not unexpected,
            "cases_not_matching_their_expected_verdict": unexpected,
            "note": "The proposed tree's graph built, validated against SHACL, and materialized without error.",
        },
    }
    out["digest"] = digest(out)
    return out


def digest(rep: dict[str, Any]) -> str:
    body = {k: v for k, v in rep.items() if k != "digest"}
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()


def markdown(rep: dict[str, Any]) -> str:
    lines = [
        f"## Impact report {rep['base']['version']} → {rep['proposed']['version']}",
        "",
        f"Digest `{rep['digest'][:16]}`. {rep['cases_evaluated']} cases evaluated against both bundles.",
        "",
        f"**Changed files:** {', '.join(bundle.touched(rep['changed_files'])) or 'none'}",
        f"**Verdicts changed:** {len(rep['verdicts_changed'])}. **Findings changed:** {len(rep['findings_changed'])}.",
        f"**Regression gate:** {'passed' if rep['gate']['regression_passed'] else 'FAILED'}.",
        "",
    ]
    if rep["verdicts_changed"]:
        lines += ["| Case | Type | Verdict | Files that could have caused it |", "|---|---|---|---|"]
        lines += [
            f"| {v['case']} | {v['type']} | {v['from']} → {v['to']} | {', '.join(v['cause_candidates']) or '—'} |"
            for v in rep["verdicts_changed"]
        ]
    return "\n".join(lines) + "\n"
