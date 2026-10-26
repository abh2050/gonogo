"""Command line for the release workflow.

python -m release manifest                          the current bundle and its digest
python -m release impact --base <git ref>           build and compare; writes release/impact/<version>.json
python -m release approve --as NAME --role ROLE --reason "..." --proposer NAME
python -m release check --base <git ref>            the pull request gate: fails unless counsel approved
python -m release publish --as NAME --role ontology_owner
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from authz import cedar
from release import approvals, bundle, impact

ROOT = Path(__file__).resolve().parent.parent


def impact_path(version: str) -> Path:
    return ROOT / "release" / "impact" / f"{version}.json"


def base_tree(ref: str, into: Path) -> Path:
    """Check out `ref` as a separate tree, so the live bundle and the proposed one never share a file."""
    subprocess.run(["git", "worktree", "add", "--detach", str(into), ref], cwd=ROOT, check=True, capture_output=True)
    return into


def build_report(ref: str) -> dict:  # type: ignore[type-arg]
    with tempfile.TemporaryDirectory() as tmp:
        tree = base_tree(ref, Path(tmp) / "base")
        try:
            # data/processed and data/synthetic are committed, so the base tree needs nothing else.
            return impact.report(tree, ROOT)
        finally:
            subprocess.run(["git", "worktree", "remove", "--force", str(tree)], cwd=ROOT, capture_output=True)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=["manifest", "impact", "approve", "check", "publish"])
    p.add_argument("--base", default="origin/main")
    p.add_argument("--recompute", action="store_true", help="check: rebuild the report from --base and compare digests")
    p.add_argument("--as", dest="name")
    p.add_argument("--role")
    p.add_argument("--reason", default="")
    p.add_argument("--proposer", default="")
    args = p.parse_args()
    m = bundle.manifest(ROOT)
    version = m["version"]

    if args.command == "manifest":
        print(json.dumps({k: m[k] for k in ("version", "digest")} | {"files": len(m["files"])}, indent=2))
        return 0
    if args.command == "impact":
        rep = build_report(args.base)
        impact_path(version).parent.mkdir(parents=True, exist_ok=True)
        impact_path(version).write_text(json.dumps(rep, indent=2, sort_keys=True) + "\n")
        print(impact.markdown(rep))
        return 0 if rep["gate"]["regression_passed"] else 1
    rep = json.loads(impact_path(version).read_text())
    if impact.digest(rep) != rep["digest"]:
        print("The impact report was edited after it was made.", file=sys.stderr)
        return 1
    if args.command == "approve":
        who = cedar.Principal(args.name or "", args.role or "")
        record = approvals.approve(version, rep, who, args.reason, args.proposer)
        print(f"{who.name} ({who.role}) approved report {rep['digest'][:12]}; {len(record['approvals'])} approval(s).")
        return 0
    if args.command == "publish":
        who = cedar.Principal(args.name or "", args.role or "")
        out = approvals.publish(version, rep, who, m)
        print(f"Published {out['version']} (bundle {out['bundle_digest'][:12]}).")
        return 0
    # check: the pull request gate
    if args.base and args.recompute:
        fresh = build_report(args.base)
        if fresh["digest"] != rep["digest"]:
            print(
                "The committed impact report is stale: rebuilding it from the base branch gives a different digest.",
                file=sys.stderr,
            )
            return 1
    if rep["proposed"]["digest"] != m["digest"]:
        print(
            "The bundle changed after the impact report was made. Run `python -m release impact` again.",
            file=sys.stderr,
        )
        return 1
    if not rep["gate"]["regression_passed"]:
        print("The regression gate failed.", file=sys.stderr)
        return 1
    if not rep["changed_files"]["added"] + rep["changed_files"]["removed"] + rep["changed_files"]["modified"]:
        print("No bundle file changed.")
        return 0
    if not approvals.counsel_approved(approvals.load(version), rep["digest"]):
        print(f"Counsel has not approved impact report {rep['digest'][:12]} for release {version}.", file=sys.stderr)
        return 1
    print("Counsel approved the impact report.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
