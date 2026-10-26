"""The benchmark's guards: the golden set matches the planted cases, the corpus holds nothing confidential, and the
rule pipeline never says GO when it should not. The last test is the gate in the build plan: a false GO by answerer
C or C+ fails the build."""

from __future__ import annotations

import json
from collections import Counter
from typing import Any

import pytest

from eval import corpus
from eval.golden import NEEDS_INFO, build
from eval.run import RUNS, golden
from eval.score import score
from gonogo.paths import ROOT

INJECTED = json.loads((ROOT / "data" / "synthetic" / "injected_conflicts.json").read_text())


def test_the_golden_file_is_what_the_generator_writes() -> None:
    assert [json.loads(line) for line in (ROOT / "eval" / "golden.jsonl").read_text().splitlines()] == build()


def test_every_planted_case_is_asked_four_ways_with_the_hand_stated_verdict() -> None:
    qs = golden()
    by_case: dict[str, list[dict[str, Any]]] = {}
    for q in qs:
        by_case.setdefault(q["case_id"], []).append(q)
    for case in INJECTED["cases"]:
        asked = by_case[case["case_id"]]
        assert sorted(q["style"] for q in asked) == ["casual", "formal", "noisy", "terse"], case["case_id"]
        assert {q["expected_verdict"] for q in asked} == {case["expected_verdict"]}


def test_unanswerable_questions_expect_needs_info_and_name_no_patent_record() -> None:
    una = [q for q in golden() if q["style"] == "unanswerable"]
    assert len(una) == 20
    assert {q["expected_verdict"] for q in una} == {NEEDS_INFO}
    assert all(q["patent_key"] is None and q["planted_evidence"] == [] for q in una)


def test_question_ids_are_unique() -> None:
    ids = [q["qid"] for q in golden()]
    assert len(ids) == len(set(ids)) == 200


def test_the_expected_verdicts_never_come_from_the_rule_engine() -> None:
    """They come from the planted cases, which were stated by hand. A change in the engine must not edit them."""
    verdicts = Counter(c["expected_verdict"] for c in INJECTED["cases"])
    qs = Counter(q["expected_verdict"] for q in golden() if q["style"] != "unanswerable")
    assert {k: v * 4 for k, v in verdicts.items()} == dict(qs)


def test_a_clause_in_the_corpus_is_never_a_royalty_clause(store: Any) -> None:
    """The corpus is built from the approved and release graphs, and royalty text lives only in the royalty graph."""
    from kg.ns import GRAPH_APPROVED

    g = store.base[GRAPH_APPROVED]
    assert not any("running royalty" in str(o) or "minimum annual royalty" in str(o) for _, _, o in g)


@pytest.mark.skipif(not (ROOT / "data" / "eval" / "corpus").exists(), reason="run python -m eval.corpus first")
def test_the_built_corpus_has_no_royalty_text_and_a_metadata_file_per_document() -> None:
    folder = corpus.OUT
    texts = sorted(folder.glob("*.txt"))
    assert texts
    for t in texts:
        assert (folder / f"{t.name}.metadata.json").exists(), t.name
        body = t.read_text()
        assert "running royalty" not in body and "minimum annual royalty" not in body, t.name


def committed(name: str) -> list[dict[str, Any]]:
    return [json.loads(line) for line in (RUNS / f"{name}.jsonl").read_text().splitlines() if line.strip()]


@pytest.mark.parametrize("name", ["C", "C+"])
def test_the_rule_pipeline_never_makes_a_false_go(name: str) -> None:
    from eval.score import doc_patents

    qs = {q["qid"]: q for q in golden()}
    answers = committed(name)
    assert len(answers) == len(qs)
    result = score(answers, qs, doc_patents())
    assert result["false_go"] == [], f"answerer {name} cleared a license that should not be granted"
    assert result["errors"] == 0


def test_answerer_c_reproduces_its_committed_answers() -> None:
    """The rules are deterministic, so a rerun gives the same verdicts as the committed run."""
    from eval.answer import RuleAnswerer

    run = RuleAnswerer()
    qs = {q["qid"]: q for q in golden()}
    saved = {a["qid"]: a for a in committed("C")}
    sample = sorted(qs)[::7]
    for qid in sample:
        assert run(qs[qid]).verdict == saved[qid]["verdict"], qid
