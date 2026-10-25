"""Repository paths shared by every module."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config"
DATA = ROOT / "data"
RAW = DATA / "raw"
PROCESSED = DATA / "processed"
SCOPE = DATA / "scope"
SYNTHETIC = DATA / "synthetic"
DOCS = ROOT / "docs"
ONTOLOGY = ROOT / "ontology"
SHAPES = ROOT / "shapes"
BUILD = ROOT / "build"
# The frozen graphs that the public demo serves. Committed, because the Vercel function cannot run the build.
SNAPSHOT = ROOT / "api" / "snapshot"
