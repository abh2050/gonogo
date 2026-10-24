"""Run GoNoGo ingestion: python -m ingest all [--refresh]

Order: patents, Federal Register notices, scope pass 1 (centers), T2 portal, scope pass 2
(adds T2 patents that notices name), USPTO legal status, scope pass 3 (prefers patents USPTO
shows in force), NTRS. Every step reads cached responses under
data/raw/ unless --refresh is passed, so a second run makes no network calls.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from typing import Any

from ingest import federal_register, nasa_patents, ntrs, scope, t2_portal, uspto

STEPS: dict[str, Callable[[bool], dict[str, Any]]] = {
    "patents": lambda refresh: nasa_patents.run(refresh=refresh),
    "federal_register": lambda refresh: federal_register.run(refresh=refresh),
    "scope": lambda refresh: scope.run(),
    "t2": lambda refresh: t2_portal.run(refresh=refresh),
    "uspto": lambda refresh: uspto.run(refresh=refresh),
    "ntrs": lambda refresh: ntrs.run(refresh=refresh),
}
ALL = ["patents", "federal_register", "scope", "t2", "scope", "uspto", "scope", "ntrs"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("step", choices=["all", *STEPS])
    parser.add_argument("--refresh", action="store_true", help="ignore the cache and fetch again")
    args = parser.parse_args()
    steps = ALL if args.step == "all" else [args.step]
    calls = 0
    for step in steps:
        meta = STEPS[step](args.refresh)
        calls += int(meta.get("network_calls", 0))
        summary = {k: v for k, v in meta.items() if not isinstance(v, list | dict)}
        print(f"[{step}] " + json.dumps(summary, sort_keys=True))
    print(f"[done] network_calls={calls}")


if __name__ == "__main__":
    main()
