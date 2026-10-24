"""ROBOT and HermiT checks. Run with: uv run pytest -m robot (needs Java 11 or later and network once)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from gonogo.paths import BUILD, ONTOLOGY, ROOT

pytestmark = pytest.mark.robot

INPUTS = [
    ONTOLOGY / "gonogo.ttl",
    ONTOLOGY / "imports" / "external-terms.ttl",
    *sorted((ONTOLOGY / "schemes").glob("*.ttl")),
    ONTOLOGY / "reference" / "centers.ttl",
]
SAMPLE = ROOT / "tests" / "cq" / "data" / "sample-approved.ttl"
BAD = sorted((ROOT / "tests" / "ontology" / "inconsistent").glob("*.ttl"))


def robot(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([str(ROOT / "scripts" / "robot.sh"), *args], capture_output=True, text=True, check=False)


@pytest.fixture(scope="module")
def merged() -> Path:
    if shutil.which("java") is None:
        pytest.skip("Java is not installed")
    BUILD.mkdir(exist_ok=True)
    out = BUILD / "merged.ttl"
    args = ["merge"]
    for path in INPUTS:
        args += ["--input", str(path)]
    result = robot(*args, "--output", str(out))
    assert result.returncode == 0, result.stderr
    return out


def test_the_ontology_and_schemes_are_consistent_with_no_unsatisfiable_class(merged: Path) -> None:
    result = robot(
        "reason",
        "--reasoner",
        "HermiT",
        "--input",
        str(merged),
        "--equivalent-classes-allowed",
        "all",
        "--dump-unsatisfiable",
        str(BUILD / "unsatisfiable.ttl"),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert not (BUILD / "unsatisfiable.ttl").exists()


def test_the_sample_world_is_consistent_with_the_ontology(merged: Path) -> None:
    both = BUILD / "merged-with-sample.ttl"
    assert robot("merge", "--input", str(merged), "--input", str(SAMPLE), "--output", str(both)).returncode == 0
    result = robot("reason", "--reasoner", "HermiT", "--input", str(both))
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("bad", BAD, ids=lambda p: p.stem)
def test_hermit_rejects_each_inconsistent_dataset(merged: Path, bad: Path) -> None:
    combined = BUILD / f"bad-{bad.stem}.ttl"
    assert robot("merge", "--input", str(merged), "--input", str(bad), "--output", str(combined)).returncode == 0
    result = robot("reason", "--reasoner", "HermiT", "--input", str(combined))
    assert result.returncode != 0
    assert "inconsistent" in (result.stdout + result.stderr).lower()


def test_there_are_three_inconsistent_datasets() -> None:
    assert len(BAD) == 3
