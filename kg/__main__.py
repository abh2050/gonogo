"""Build, validate, and load the knowledge graph.

python -m kg build        build the graphs, materialize inference, validate, write build/kg/*.ttl
python -m kg load         load build/kg/*.ttl into the local Fuseki dataset
python -m kg all          build, then load
"""

from __future__ import annotations

import argparse
import json
import sys
import time

from kg import build, load, materialize, validate
from kg.ns import GRAPH_APPROVED, GRAPH_CANDIDATE, GRAPH_RELEASE, GRAPH_ROYALTY


def cmd_build(skip_validation: bool = False) -> int:
    t = time.time()
    graphs = build.build_graphs()
    raw = {name: len(g) for name, g in graphs.items()}
    added = materialize.apply(graphs)
    print(f"built in {time.time() - t:.1f}s")
    for name in (GRAPH_RELEASE, GRAPH_APPROVED, GRAPH_CANDIDATE, GRAPH_ROYALTY):
        print(f"  {name}: {raw[name]:,} asserted + {added[name]:,} inferred = {len(graphs[name]):,}")
    load.write_files(graphs)
    if skip_validation:
        return 0
    reports = validate.validate_all(graphs)
    ok = True
    for r in reports:
        print(
            f"  SHACL {r['name']}: {'conforms' if r['conforms'] else 'DOES NOT CONFORM'} ({r['violations']} violations)"
        )
        ok = ok and r["conforms"]
        if not r["conforms"]:
            print(r["text"][:4000])
    (load.OUT_DIR / "shacl-report.json").write_text(json.dumps(reports, indent=2, default=str))
    return 0 if ok else 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["build", "load", "all"])
    parser.add_argument("--no-validate", action="store_true")
    parser.add_argument("--fuseki", default="http://localhost:3030/gonogo")
    args = parser.parse_args()
    code = 0
    if args.command in ("build", "all"):
        code = cmd_build(args.no_validate)
    if code == 0 and args.command in ("load", "all"):
        load.load_all(args.fuseki)
    sys.exit(code)


if __name__ == "__main__":
    main()
