"""The release workflow: the bundle, the impact report, and counsel's approval."""

from __future__ import annotations

import functools
import json
import shutil
import sys
from pathlib import Path
from typing import Any

import pytest

from authz.cedar import Principal
from gonogo.paths import ROOT
from release import __main__ as cli
from release import approvals, bundle, impact

SKIP_TOP = {
    ".git",
    ".venv",
    "node_modules",
    "build",
    "ui",
    "infra",
    "docs",
    "tests",
    "scripts",
    "api",
    "agent",
    "synth",
    "ingest",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    "release",
    "service",
    "eval",
    "mappings",
}


def copy_tree(dst: Path) -> Path:
    def ignore(directory: str, names: list[str]) -> list[str]:
        rel = Path(directory).relative_to(ROOT)
        if rel == Path("."):
            return [n for n in names if n in SKIP_TOP or n.startswith(".")]
        if rel == Path("data"):
            return [n for n in names if n == "raw"]
        return [n for n in names if n in {"__pycache__"}]

    shutil.copytree(ROOT, dst, ignore=ignore)
    (dst / "mappings").mkdir()
    shutil.copy(ROOT / "mappings" / "gonogo.r2rml.ttl", dst / "mappings")
    return dst


# ---- The bundle ----------------------------------------------------------------------------------


def tiny_root(tmp: Path, text: str = "a") -> Path:
    (tmp / "config").mkdir(parents=True, exist_ok=True)
    (tmp / "config" / "release.yaml").write_text('ontology_release: "9.9.9"\n')
    (tmp / "config" / "precedence.yaml").write_text(text)
    (tmp / "ontology").mkdir(exist_ok=True)
    (tmp / "ontology" / "gonogo.ttl").write_text("# ontology\n")
    return tmp


def test_the_manifest_is_the_same_twice_and_changes_with_any_file(tmp_path: Path) -> None:
    root = tiny_root(tmp_path)
    first = bundle.manifest(root)
    assert bundle.manifest(root) == first and first["version"] == "9.9.9"
    (root / "config" / "precedence.yaml").write_text("b")
    second = bundle.manifest(root)
    assert second["digest"] != first["digest"]
    assert bundle.changed(first, second) == {"added": [], "removed": [], "modified": ["config/precedence.yaml"]}


def test_the_real_bundle_holds_the_files_that_decide() -> None:
    names = set(bundle.manifest(ROOT)["files"])
    for must in (
        "ontology/gonogo.ttl",
        "ontology/schemes/fields.ttl",
        "shapes/gonogo-shapes.ttl",
        "rules/templates/r2_executed_overlap.rq",
        "rules/r2_exclusivity.py",
        "config/precedence.yaml",
        "mappings/gonogo.r2rml.ttl",
    ):
        assert must in names, must


def test_a_rule_depends_on_its_own_files_and_the_combiner_on_the_policy() -> None:
    touched = ["ontology/schemes/fields.ttl", "rules/r7_statutory.py", "config/precedence.yaml", "docs/x.md"]
    assert impact.causes("R2", touched) == ["ontology/schemes/fields.ttl"]
    assert impact.causes("R7", touched) == ["rules/r7_statutory.py"]
    assert impact.causes(None, touched) == ["config/precedence.yaml"]
    assert impact.causes("R5", ["rules/r6_consent.py"]) == []


# ---- The impact report ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def trees(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    base = copy_tree(tmp_path_factory.mktemp("base") / "t")
    harmless = copy_tree(tmp_path_factory.mktemp("harmless") / "t")
    template = harmless / "rules" / "templates" / "r5_export.rq"
    template.write_text("# A comment that changes the file and no result.\n" + template.read_text())
    stricter = copy_tree(tmp_path_factory.mktemp("stricter") / "t")
    policy = stricter / "config" / "precedence.yaml"
    policy.write_text(policy.read_text().replace("verdict: COUNSEL", "verdict: NO GO"))
    return {"base": base, "harmless": harmless, "stricter": stricter}


@pytest.fixture(autouse=True, scope="module")
def cache_evaluations() -> Any:
    original = impact.evaluate_tree
    cached = functools.cache(lambda path: original(Path(path)))
    impact.evaluate_tree = lambda root: cached(str(root))  # type: ignore[assignment]
    yield
    impact.evaluate_tree = original


def test_a_change_that_moves_no_result_reports_no_change_and_passes_the_gate(trees: dict[str, Path]) -> None:
    rep = impact.report(trees["base"], trees["harmless"])
    assert rep["changed_files"]["modified"] == ["rules/templates/r5_export.rq"]
    assert rep["verdicts_changed"] == [] and rep["findings_changed"] == []
    assert rep["gate"]["regression_passed"] and rep["cases_evaluated"] == 45


def test_a_stricter_combiner_changes_every_counsel_verdict_and_the_report_says_which_file(
    trees: dict[str, Path],
) -> None:
    rep = impact.report(trees["base"], trees["stricter"])
    assert rep["changed_files"]["modified"] == ["config/precedence.yaml"]
    moved = rep["verdicts_changed"]
    assert moved and all(v["from"] == "COUNSEL" and v["to"] == "NO GO" for v in moved)
    assert all(v["cause_candidates"] == ["config/precedence.yaml"] for v in moved)
    assert rep["findings_changed"] == [], "the rules found the same things; only the combiner moved"
    assert not rep["gate"]["regression_passed"], "the recorded expectations say COUNSEL, so the gate stops it"
    assert {v["case"] for v in moved} <= set(rep["gate"]["cases_not_matching_their_expected_verdict"])


def test_the_report_digest_changes_when_the_report_is_edited(trees: dict[str, Path]) -> None:
    rep = impact.report(trees["base"], trees["harmless"])
    assert impact.digest(rep) == rep["digest"]
    rep["verdicts_changed"] = [{"case": "INJ-001"}]
    assert impact.digest(rep) != rep["digest"]


def test_the_markdown_names_the_changed_files_and_the_gate(trees: dict[str, Path]) -> None:
    text = impact.markdown(impact.report(trees["base"], trees["stricter"]))
    assert "config/precedence.yaml" in text and "FAILED" in text and "COUNSEL → NO GO" in text


# ---- Approval and publication --------------------------------------------------------------------


def fake_report(passed: bool = True) -> dict[str, Any]:
    rep: dict[str, Any] = {
        "base": {"version": "0.1.0", "digest": "a"},
        "proposed": {"version": "0.2.0", "digest": "b"},
        "changed_files": {"added": [], "removed": [], "modified": ["config/precedence.yaml"]},
        "cases_evaluated": 45,
        "verdicts_changed": [],
        "findings_changed": [],
        "gate": {"regression_passed": passed, "cases_not_matching_their_expected_verdict": []},
    }
    rep["digest"] = impact.digest(rep)
    return rep


@pytest.fixture
def workdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(approvals, "ROOT", tmp_path)
    return tmp_path


OWEN, COY, DEE = Principal("owen", "ontology_owner"), Principal("cy", "counsel"), Principal("dee", "counsel")


def test_the_proposer_cannot_approve_their_own_impact_report(workdir: Path) -> None:
    with pytest.raises(approvals.ReleaseRefusedError, match="You proposed this release"):
        approvals.approve("0.2.0", fake_report(), OWEN, "Looks right.", proposer="owen")


def test_a_release_waits_for_counsel_and_then_publishes(workdir: Path) -> None:
    rep, manifest = fake_report(), {"digest": "bundle"}
    approvals.approve(
        "0.2.0", rep, OWEN, "I checked it.", proposer="pat"
    )  # an owner other than the proposer may approve
    with pytest.raises(approvals.ReleaseRefusedError, match="Counsel has not approved"):
        approvals.publish("0.2.0", rep, OWEN, manifest)
    approvals.approve("0.2.0", rep, COY, "Counsel agrees.", proposer="pat")
    out = approvals.publish("0.2.0", rep, OWEN, manifest)
    assert out["bundle_digest"] == "bundle" and [a["role"] for a in out["approvals"]] == ["ontology_owner", "counsel"]
    assert (workdir / "release" / "published" / "0.2.0.json").exists()


def test_counsel_cannot_publish_and_a_failed_gate_blocks_publication(workdir: Path) -> None:
    rep = fake_report()
    approvals.approve("0.2.0", rep, COY, "Counsel agrees.", proposer="pat")
    with pytest.raises(approvals.ReleaseRefusedError):
        approvals.publish("0.2.0", rep, DEE, {"digest": "x"})
    failing = fake_report(passed=False)
    approvals.approve("0.3.0", failing, COY, "Counsel agrees.", proposer="pat")
    with pytest.raises(approvals.ReleaseRefusedError, match="regression gate did not pass"):
        approvals.publish("0.3.0", failing, OWEN, {"digest": "x"})


def test_an_approval_belongs_to_one_report_and_a_changed_report_needs_a_new_one(workdir: Path) -> None:
    old = fake_report()
    approvals.approve("0.2.0", old, COY, "Counsel agrees.", proposer="pat")
    changed = {**old, "verdicts_changed": [{"case": "INJ-002"}]}
    changed["digest"] = impact.digest(changed)
    assert approvals.counsel_approved(approvals.load("0.2.0"), old["digest"])
    assert not approvals.counsel_approved(approvals.load("0.2.0"), changed["digest"])
    with pytest.raises(approvals.ReleaseRefusedError, match="Counsel has not approved"):
        approvals.publish("0.2.0", changed, OWEN, {"digest": "x"})


def test_roles_that_may_not_approve_are_refused(workdir: Path) -> None:
    for role in ("licensing_manager", "steward", "finance_analyst", "auditor"):
        with pytest.raises(approvals.ReleaseRefusedError):
            approvals.approve("0.2.0", fake_report(), Principal("x", role), "Sure.", proposer="pat")


# ---- The pull request gate -----------------------------------------------------------------------


def run_check(monkeypatch: pytest.MonkeyPatch, root: Path) -> int:
    monkeypatch.setattr(cli, "ROOT", root)
    monkeypatch.setattr(sys, "argv", ["release", "check"])
    return cli.main()


def test_the_gate_fails_without_counsel_and_passes_with_it(workdir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tiny_root(workdir / "tree")
    manifest = bundle.manifest(root)
    rep = fake_report()
    rep["proposed"] = {"version": "9.9.9", "digest": manifest["digest"]}
    rep["digest"] = impact.digest(rep)
    (root / "release" / "impact").mkdir(parents=True)
    (root / "release" / "impact" / "9.9.9.json").write_text(json.dumps(rep))
    monkeypatch.setattr(approvals, "ROOT", root)
    assert run_check(monkeypatch, root) == 1
    approvals.approve("9.9.9", rep, COY, "Counsel agrees.", proposer="pat")
    assert run_check(monkeypatch, root) == 0


def test_the_gate_rejects_a_bundle_that_changed_after_the_report(
    workdir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tiny_root(workdir / "tree")
    rep = fake_report()
    rep["proposed"] = {"version": "9.9.9", "digest": bundle.manifest(root)["digest"]}
    rep["digest"] = impact.digest(rep)
    (root / "release" / "impact").mkdir(parents=True)
    (root / "release" / "impact" / "9.9.9.json").write_text(json.dumps(rep))
    (root / "config" / "precedence.yaml").write_text("changed after the report")
    assert run_check(monkeypatch, root) == 1


def test_the_gate_rejects_an_edited_report(workdir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tiny_root(workdir / "tree")
    rep = fake_report()
    rep["gate"]["regression_passed"] = True
    (root / "release" / "impact").mkdir(parents=True)
    (root / "release" / "impact" / "9.9.9.json").write_text(json.dumps({**rep, "cases_evaluated": 1}))
    assert run_check(monkeypatch, root) == 1
