"""Checks on the committed synthetic data and on the generator itself."""

import csv
import json
from pathlib import Path
from typing import Any

import pytest
from pypdf import PdfReader

from gonogo.paths import PROCESSED, SCOPE, SYNTHETIC
from synth.generator import GENERATOR_IRI, generate

PRECEDENCE = [("FAIL", "NO GO"), ("PENDING", "HOLD"), ("REVIEW", "COUNSEL"), ("UNKNOWN", "NO DATA")]
RULES = {"R1", "R2", "R3", "R4", "R5", "R6", "R7"}
STATUSES = {"PASS", "FAIL", "UNKNOWN", "REVIEW", "PENDING", "NOT_APPLICABLE"}


def jsonl(name: str) -> list[dict[str, Any]]:
    return [json.loads(line) for line in (SYNTHETIC / name).read_text().splitlines() if line]


def cases() -> list[dict[str, Any]]:
    return list(json.loads((SYNTHETIC / "injected_conflicts.json").read_text())["cases"])


def gonogo_verdict(statuses: dict[str, str]) -> str:
    for status, verdict in PRECEDENCE:
        if status in statuses.values():
            return verdict
    return "GO"


def test_generator_is_deterministic(tmp_path: Path) -> None:
    a = generate(seed=42, out=tmp_path / "a", pdfs=False)
    b = generate(seed=42, out=tmp_path / "b", pdfs=False)
    assert a["sha256"] == b["sha256"]
    c = generate(seed=7, out=tmp_path / "c", pdfs=False)
    assert c["sha256"]["agreements.jsonl"] != a["sha256"]["agreements.jsonl"]


def test_committed_data_matches_generator(tmp_path: Path) -> None:
    fresh = generate(seed=42, out=tmp_path / "fresh", pdfs=True)
    committed = json.loads((SYNTHETIC / "manifest.json").read_text())
    assert fresh["sha256"] == committed["sha256"]


@pytest.mark.parametrize(
    "name",
    [
        "agreements.jsonl",
        "proposed_grants.jsonl",
        "ownership.jsonl",
        "consents.jsonl",
        "licensees.jsonl",
        "export_classifications.jsonl",
        "filing_dates.jsonl",
        "requests.jsonl",
        "candidate_facts.jsonl",
        "co_owners.jsonl",
    ],
)
def test_every_synthetic_record_is_labeled(name: str) -> None:
    for rec in jsonl(name):
        assert rec["synthetic"] is True and rec["generated_by"] == GENERATOR_IRI


def test_clause_spans_index_the_text_file() -> None:
    for a in jsonl("agreements.jsonl"):
        text = Path(SYNTHETIC.parent.parent / a["text_file"]).read_text()
        for c in a["clauses"]:
            assert text[c["start"] : c["end"]] == c["text"]
        ids = {c["clause_id"] for c in a["clauses"]}
        assert set(a["fact_clauses"].values()) <= ids
        assert "SYNTHETIC DOCUMENT" in text


@pytest.mark.parametrize("agreement_id", ["AGR-0001", "AGR-0020", "AGR-0060", "AGR-0120"])
def test_pdf_text_contains_every_clause(agreement_id: str) -> None:
    a = next(r for r in jsonl("agreements.jsonl") if r["agreement_id"] == agreement_id)
    pdf_text = " ".join(
        " ".join(p.extract_text().split()) for p in PdfReader(SYNTHETIC.parent.parent / a["pdf_file"]).pages
    )
    for c in a["clauses"]:
        assert " ".join(c["text"].split()) in pdf_text


def test_injected_cases_are_consistent() -> None:
    with (SCOPE / "patents_in_scope.csv").open() as f:
        in_scope = {r["patent_key"] for r in csv.DictReader(f)}
    requests = {r["request_id"]: r for r in jsonl("requests.jsonl")}
    agreements = {a["agreement_id"] for a in jsonl("agreements.jsonl")}
    notices = {n["notice_id"] for n in jsonl("proposed_grants.jsonl")}
    for case in cases():
        assert case["patent_key"] in in_scope
        assert requests[case["request_id"]]["patent_key"] == case["patent_key"]
        assert set(case.get("conflicting_agreements", []) + case.get("related_agreements", [])) <= agreements
        assert set(case.get("related_notices", [])) <= notices
        assert set(case["expected_statuses"]) <= RULES
        assert set(case["expected_statuses"].values()) <= STATUSES


def test_hand_written_verdicts_follow_gonogo_precedence() -> None:
    for case in cases():
        statuses = case["expected_statuses"]
        if set(statuses) == RULES:
            assert gonogo_verdict(statuses) == case["expected_verdict"], case["case_id"]
        else:
            # Partial assertions are only allowed when a FAIL alone decides the verdict.
            assert "FAIL" in statuses.values() and case["expected_verdict"] == "NO GO", case["case_id"]
        if "after_approval" in case:
            after = case["after_approval"]
            assert gonogo_verdict(after["expected_statuses"]) == after["expected_verdict"]


def test_every_verdict_and_rule_failure_mode_is_covered() -> None:
    all_cases = cases()
    assert {c["expected_verdict"] for c in all_cases} == {"GO", "NO GO", "HOLD", "COUNSEL", "NO DATA"}
    seen = {(rule, status) for c in all_cases for rule, status in c["expected_statuses"].items()}
    for needed in [
        ("R1", "FAIL"),
        ("R1", "UNKNOWN"),
        ("R2", "FAIL"),
        ("R2", "REVIEW"),
        ("R3", "FAIL"),
        ("R3", "UNKNOWN"),
        ("R4", "PENDING"),
        ("R5", "REVIEW"),
        ("R5", "UNKNOWN"),
        ("R6", "REVIEW"),
        ("R6", "UNKNOWN"),
        ("R7", "REVIEW"),
    ]:
        assert needed in seen, needed


def test_injected_case_patents_have_no_background_agreements() -> None:
    controlled: dict[str, set[str]] = {}
    for case in cases():
        ids = set(case.get("conflicting_agreements", []) + case.get("related_agreements", []))
        controlled.setdefault(case["patent_key"], set()).update(ids)
    for a in jsonl("agreements.jsonl"):
        for key in a["patent_keys"]:
            if key in controlled:
                assert a["agreement_id"] in controlled[key], (key, a["agreement_id"])


def test_fictional_licensees_never_reuse_real_notice_names() -> None:
    real = {
        (n["licensee"] or "").lower()
        for n in map(json.loads, (PROCESSED / "federal_register.jsonl").read_text().splitlines())
    }
    for lic in jsonl("licensees.jsonl"):
        for name in [lic["name"], *lic["variants"]]:
            assert name.lower() not in real
