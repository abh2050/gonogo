"""The request parser: every value is a known concept, a patent in the graph, or a date, and nothing is guessed."""

from __future__ import annotations

from typing import Any

import pytest

from agent.model_parser import check, parse_with_fallback
from agent.parser import Vocabulary, parse, to_iso
from kg.actions import apply_event
from kg.store import Store
from rules.engine import evaluate_now
from rules.model import exclusivity_slug
from tests.rules.helpers import jsonl

GENH2 = (
    "Can GenH2 Corporation get an exclusive license to US Patent 10,431,355 for energy generation "
    "in the USA for five years starting March 1, 2027?"
)


@pytest.fixture(scope="module")
def vocab(kg_graphs: Any) -> Vocabulary:
    return Vocabulary.from_store(Store.from_build())


@pytest.mark.parametrize("row", jsonl("requests.jsonl"), ids=lambda r: r["request_id"])
def test_every_synthetic_request_parses_to_its_recorded_values(row: dict[str, Any], vocab: Vocabulary) -> None:
    p = parse(row["text"], vocab)
    assert p.complete and p.missing == []
    got = {k: v.value for k, v in p.found.items()}
    assert got["patent_key"] == row["patent_key"]
    assert got["exclusivity"] == exclusivity_slug(row["exclusivity"])
    assert (got["field"], got["territory"]) == (row["field_concept"], row["territory"])
    assert (got["start"], got["end"]) == (row["start"], row["end"])
    assert p.licensee and p.licensee["status"] == "match"
    assert p.licensee["ids"][0].endswith("/" + row["licensee_id"])


def test_spans_point_at_the_words_that_were_read(vocab: Vocabulary) -> None:
    p = parse(GENH2, vocab)
    for found in p.found.values():
        start, end = found.span
        assert GENH2[start:end] == found.text
    assert p.found["patent_key"].value == "US10431355"
    assert p.found["territory"].text == "USA" and p.found["territory"].value == "US"


def test_a_term_in_years_ends_the_day_before_the_anniversary(vocab: Vocabulary) -> None:
    p = parse(GENH2, vocab)
    assert (p.found["start"].value, p.found["end"].value) == ("2027-03-01", "2032-02-29")
    assert p.found["end"].how == "computed"


def test_missing_parts_are_listed_and_never_guessed(vocab: Vocabulary) -> None:
    p = parse("Acme Robotics wants a co-exclusive license to LAR-99999-1 worldwide", vocab)
    assert not p.complete
    assert set(p.missing) == {"patent_key", "field", "start", "end"}
    assert any("LAR-99999-1" in n for n in p.notes)
    assert p.licensee and p.licensee["status"] == "none"
    with pytest.raises(ValueError, match="missing"):
        p.to_request()


def test_the_licensee_name_is_not_read_as_a_field_or_territory(vocab: Vocabulary) -> None:
    p = parse("Orbital Lens Works, Inc. wants a non-exclusive license to LEW-17915-1 in Canada", vocab)
    assert "field" in p.missing, "'Lens' in the company name must not become the field 'Lenses and mirrors'"
    assert p.found["territory"].value == "CA"


def test_two_spellings_stay_ambiguous_until_a_steward_links_them(store: Store) -> None:
    fresh = store.fork()
    before = parse(GENH2, Vocabulary.from_store(fresh))
    assert before.licensee and before.licensee["status"] == "ambiguous" and before.licensee["ids"] == []
    a, b = (c["iri"] for c in before.licensee["candidates"][:2])
    apply_event(
        fresh,
        {"action": "link_identity", "steward": "Demo Steward", "reason": "Same address.", "params": {"a": a, "b": b}},
    )
    after = parse(GENH2, Vocabulary.from_store(fresh))
    assert after.licensee and after.licensee["status"] == "match" and set(after.licensee["ids"]) == {a, b}
    decision = evaluate_now(fresh, after.to_request())
    assert decision.statuses()["R4"] == "PASS", "the linked notice to GenH2 closed in 2022"


@pytest.mark.parametrize(
    ("raw", "iso"),
    [("January 1, 2027", "2027-01-01"), ("Sept 30 2028", "2028-09-30"), ("2029-02-28", "2029-02-28")],
)
def test_dates(raw: str, iso: str) -> None:
    assert to_iso(raw) == iso


class FakeBedrock:
    def __init__(self, answer: dict[str, Any]) -> None:
        self.answer = answer
        self.calls = 0

    def converse(self, **kw: Any) -> dict[str, Any]:
        self.calls += 1
        assert kw["toolConfig"]["toolChoice"] == {"tool": {"name": "clearance_request"}}
        return {"output": {"message": {"content": [{"toolUse": {"input": self.answer}}]}}}


def test_the_model_is_asked_only_for_missing_parts_and_its_answers_are_checked(vocab: Vocabulary) -> None:
    text = "Acme Robotics would like exclusive rights to LEW-17915-1 for laser work across the US, mid 2027 to 2030"
    fake = FakeBedrock(
        {
            "licensee": "Acme Robotics",
            "patent": "LEW-17915-1",
            "field_of_use": "lasers",
            "territory": "Atlantis",  # not a concept: dropped
            "start": "2027-06-01",
            "end": "not a date",  # dropped
            "exclusivity": "exclusive",
        }
    )
    p = parse_with_fallback(text, vocab, client=fake, model_id="test-model")
    assert fake.calls == 1
    assert p.found["field"].value == "lasers" and p.found["field"].how == "model"
    assert p.found["territory"].how == "rule", "the rule parser's answer is kept"
    assert p.found["start"].value == "2027-06-01"
    assert "end" in p.missing
    assert p.parser.endswith("model:test-model")


def test_a_complete_parse_never_calls_the_model(vocab: Vocabulary) -> None:
    fake = FakeBedrock({})
    parse_with_fallback(jsonl("requests.jsonl")[0]["text"], vocab, client=fake, model_id="m")
    assert fake.calls == 0


def test_check_refuses_unknown_patents_and_concepts(vocab: Vocabulary) -> None:
    kept = check({"patent": "XYZ-1", "field_of_use": "time travel", "exclusivity": "sole"}, vocab, "anything")
    assert kept == {}
