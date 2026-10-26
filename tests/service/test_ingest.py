"""The ingestion workflow's logic, run locally: extraction from PDF text, the proposal and its SHACL check, the
steward's approval, and the verdicts it changes. The AWS wiring is checked in tests/infra; Textract is replaced
here by the text that pypdf reads from the same PDF."""

from __future__ import annotations

import json
from typing import Any

import pytest
from pypdf import PdfReader

from agent.parser import Vocabulary
from gonogo.paths import ROOT
from kg.actions import ActionRejectedError, apply_event, replay
from kg.ns import GRAPH_APPROVED, GRAPH_CANDIDATE
from kg.store import Store
from rules.book import load_book, to_request
from rules.engine import evaluate
from service.ingest import PIPELINE, ExtractionError, extract, proposal

SAMPLES = ROOT / "data" / "ingest"


def text_of(path: Any) -> str:
    return "\n".join(p.extract_text() for p in PdfReader(str(path)).pages)


@pytest.fixture(scope="module")
def vocab(store: Store) -> Vocabulary:
    return Vocabulary.from_store(store)


def approve(store: Store, record: dict[str, Any], steward: str = "Ann Steward") -> Store:
    base = store.fork()
    proposed = apply_event(base, proposal(record))
    apply_event(base, {"action": "approve_fact", "steward": steward, "reason": "Checked against the signed PDF.",
                       "params": {"candidate": proposed["candidate"]}})  # fmt: skip
    return base


def verdict(store: Store, request_id: str) -> Any:
    row = next(r for r in load_book() if r["request_id"] == request_id)
    return evaluate(store, to_request(row), cutoff="2026-11-02T00:00:00Z", as_of="2026-11-01")


def test_a_clean_agreement_is_read_exactly(vocab: Vocabulary) -> None:
    r = extract(text_of(SAMPLES / "AGR-0901.pdf"), vocab, "s3://inbox/AGR-0901.pdf")
    assert (r["agreement_id"], r["exclusivity"], r["field_concept"], r["territory"]) == (
        "AGR-0901", "exclusive", "optical-communications", "US")  # fmt: skip
    assert r["patent_keys"] == ["LEW-17915-1"]
    assert r["licensee"].endswith("/licensee/LIC-006")
    assert (r["valid_from"], r["valid_to"], r["executed_on"]) == ("2027-01-01", "2036-12-31", "2026-10-20")


def test_the_royalty_article_never_leaves_the_document(vocab: Vocabulary, store: Store) -> None:
    r = extract(text_of(SAMPLES / "AGR-0901.pdf"), vocab, "s3://inbox/AGR-0901.pdf")
    assert "royalty" not in {c["kind"] for c in r["clauses"]}
    after = approve(store, r)
    for g in (GRAPH_APPROVED, GRAPH_CANDIDATE):
        assert not any("running royalty" in str(o) for _, _, o in after.overlay[g])


def test_a_planted_instruction_is_kept_as_text_and_changes_nothing(vocab: Vocabulary, store: Store) -> None:
    r = extract(text_of(SAMPLES / "AGR-0902.pdf"), vocab, "s3://inbox/AGR-0902.pdf")
    assert r["exclusivity"] == "non-exclusive" and r["territory"] == "US"
    assert any("SYSTEM INSTRUCTION" in c for c in r["unrecognized_clauses"])
    before = verdict(store, "REQ-0034").verdict
    assert verdict(approve(store, r), "REQ-0034").verdict == before == "GO"


def test_an_approved_exclusive_grant_turns_go_into_no_go_and_r2_names_it(vocab: Vocabulary, store: Store) -> None:
    r = extract(text_of(SAMPLES / "AGR-0901.pdf"), vocab, "s3://inbox/AGR-0901.pdf")
    assert verdict(store, "REQ-0001").verdict == "GO"
    record = verdict(approve(store, r), "REQ-0001").to_dict()
    assert record["verdict"] == "NO GO"
    r2 = next(f for f in record["findings"] if f["rule"] == "R2")
    assert r2["status"] == "FAIL"
    assert any("AGR-0901" in fact["iri"] for fact in r2["facts"])


def test_the_new_grant_supersedes_nothing(vocab: Vocabulary, store: Store) -> None:
    r = extract(text_of(SAMPLES / "AGR-0901.pdf"), vocab, "s3://inbox/AGR-0901.pdf")
    base = store.fork()
    proposed = apply_event(base, proposal(r))
    result = apply_event(base, {"action": "approve_fact", "steward": "Ann Steward", "reason": "Checked.",
                                "params": {"candidate": proposed["candidate"]}})  # fmt: skip
    assert result["superseded"] == []


def test_the_pipeline_cannot_approve_its_own_proposal(vocab: Vocabulary, store: Store) -> None:
    r = extract(text_of(SAMPLES / "AGR-0901.pdf"), vocab, "s3://inbox/AGR-0901.pdf")
    with pytest.raises(ActionRejectedError):
        approve(store, r, steward=PIPELINE)


def test_an_agreement_already_on_record_is_refused(vocab: Vocabulary, store: Store) -> None:
    r = extract(text_of(ROOT / "data" / "synthetic" / "agreements" / "AGR-0012.pdf"), vocab, "s3://inbox/x.pdf")
    with pytest.raises(ActionRejectedError, match="already on record"):
        apply_event(store.fork(), proposal(r))


def test_a_field_that_is_not_a_concept_goes_to_a_person(vocab: Vocabulary) -> None:
    rows = [json.loads(line) for line in (ROOT / "data" / "synthetic" / "agreements.jsonl").read_text().splitlines()]
    free = next(a for a in rows if a["agreement_id"] == "AGR-0024")
    with pytest.raises(ExtractionError, match="field of use"):
        extract(text_of(ROOT / free["pdf_file"]), vocab, "s3://inbox/x.pdf")


def test_extraction_is_never_wrong_on_the_synthetic_agreements(vocab: Vocabulary) -> None:
    """Every agreement is either read exactly as the generator wrote it, or refused for a person to read."""
    fields = ["exclusivity", "field_concept", "territory", "valid_from", "valid_to", "executed_on",
              "sublicense_allowed", "co_exclusive_cap", "licensee_as_written"]  # fmt: skip
    exact = 0
    for line in (ROOT / "data" / "synthetic" / "agreements.jsonl").read_text().splitlines():
        a = json.loads(line)
        try:
            r = extract(text_of(ROOT / a["pdf_file"]), vocab, a["pdf_file"])
        except ExtractionError:
            continue
        assert {f: r[f] for f in fields} == {f: a[f] for f in fields}, a["agreement_id"]
        assert r["patent_keys"] == sorted(a["patent_keys"]), a["agreement_id"]
        assert r["licensee"].endswith("/" + a["licensee_id"]), a["agreement_id"]
        exact += 1
    assert exact >= 100


def test_the_proposal_replays_to_the_same_graph(vocab: Vocabulary, store: Store) -> None:
    r = extract(text_of(SAMPLES / "AGR-0901.pdf"), vocab, "s3://inbox/AGR-0901.pdf")
    events = [proposal(r)]
    a, b = replay(store, events), replay(store, events)
    assert set(a.overlay[GRAPH_CANDIDATE]) == set(b.overlay[GRAPH_CANDIDATE])
