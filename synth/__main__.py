"""Run the synthetic generator: python -m synth --seed 42"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from gonogo.paths import SYNTHETIC
from synth.generator import generate


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", type=Path, default=SYNTHETIC)
    parser.add_argument("--no-pdf", action="store_true", help="skip PDF rendering")
    args = parser.parse_args()
    manifest = generate(seed=args.seed, out=args.out, pdfs=not args.no_pdf)
    print(json.dumps(manifest["counts"], indent=2))


if __name__ == "__main__":
    main()
