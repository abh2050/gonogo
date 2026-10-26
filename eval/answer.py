"""What every answerer returns, and answerer C: the GoNoGo rule pipeline.

An answer is a verdict, the documents it cites, and what it cost. The verdict is one of GO, NO GO, HOLD, COUNSEL,
NO DATA, or NEEDS INFO (the question leaves out something an answer needs). Citations are corpus document ids
(eval/corpus.py), so the three answerers are scored the same way.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any

from agent.parser import Vocabulary, parse
from eval.corpus import card_id, doc_id
from kg.store import Store
from rules.engine import evaluate

VERDICTS = ("GO", "NO GO", "HOLD", "COUNSEL", "NO DATA", "NEEDS INFO")


@dataclass
class Answer:
    qid: str
    answerer: str
    verdict: str
    citations: list[str] = field(default_factory=list)
    reason: str = ""
    latency_s: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    model_calls: int = 0
    retrieved: list[str] = field(default_factory=list)  # answerer A: the documents the search returned
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def decision_citations(decision: dict[str, Any]) -> list[str]:
    """Every fact a rule read, as its record card, and every document behind a clause it cited."""
    out: list[str] = []
    for finding in decision.get("findings", []):
        for fact in finding.get("facts", []):
            out.append(card_id(fact["iri"]))
        for clause in finding.get("clauses", []):
            if clause.get("document"):
                out.append(doc_id(clause["document"]))
    return sorted(set(out))


class RuleAnswerer:
    """Answerer C. The fixed-pattern parser reads the question, and the seven rules decide. No model is called."""

    name = "C"

    def __init__(self, store: Store | None = None) -> None:
        self.store = store or Store.from_build()
        self.vocab = Vocabulary.from_store(self.store)

    def __call__(self, q: dict[str, Any]) -> Answer:
        t0 = time.perf_counter()
        p = parse(q["text"], self.vocab)
        if not p.complete:
            return Answer(q["qid"], self.name, "NEEDS INFO", reason="missing: " + ", ".join(p.missing),
                          latency_s=time.perf_counter() - t0)  # fmt: skip
        record = evaluate(
            self.store, p.to_request(), cutoff=q["recording_cutoff"], as_of=q["as_of"], user="benchmark"
        ).to_dict()
        decided = [f["rule"] for f in record["findings"] if f.get("status") not in ("PASS", "NOT_APPLICABLE")]
        return Answer(
            q["qid"],
            self.name,
            record["verdict"],
            citations=decision_citations(record),
            reason="rules not passing: " + (", ".join(decided) or "none"),
            latency_s=time.perf_counter() - t0,
        )


HAIKU = "us.anthropic.claude-haiku-4-5-20251001-v1:0"


class Metered:
    """A Bedrock runtime client that counts the tokens of every Converse call made through it."""

    def __init__(self, client: Any) -> None:
        self.client = client
        self.calls = self.tokens_in = self.tokens_out = 0

    def converse(self, **kw: Any) -> dict[str, Any]:
        out: dict[str, Any] = self.client.converse(**kw)
        self.calls += 1
        self.tokens_in += out["usage"]["inputTokens"]
        self.tokens_out += out["usage"]["outputTokens"]
        return out


def bedrock() -> Any:
    from botocore.config import Config

    from gonogo import aws

    return aws.session().client(
        "bedrock-runtime", config=Config(read_timeout=300, retries={"max_attempts": 8, "mode": "adaptive"})
    )


class ModelParsedRuleAnswerer(RuleAnswerer):
    """Answerer C+. The same rules, but when the fixed parser misses a part, the model parser reads the question.
    The model only fills a form; every value must name a concept, patent, or date the graph holds, and the rules
    still decide (agent/model_parser.py)."""

    name = "C+"

    def __init__(self, store: Store | None = None, model_id: str = HAIKU) -> None:
        super().__init__(store)
        self.model_id = model_id
        self.client = bedrock()

    def __call__(self, q: dict[str, Any]) -> Answer:
        from agent.model_parser import parse_with_fallback

        meter = Metered(self.client)
        t0 = time.perf_counter()
        p = parse_with_fallback(q["text"], self.vocab, meter, self.model_id)
        if not p.complete:
            return Answer(q["qid"], self.name, "NEEDS INFO", reason="missing: " + ", ".join(p.missing),
                          latency_s=time.perf_counter() - t0, tokens_in=meter.tokens_in,
                          tokens_out=meter.tokens_out, model_calls=meter.calls)  # fmt: skip
        record = evaluate(
            self.store, p.to_request(), cutoff=q["recording_cutoff"], as_of=q["as_of"], user="benchmark"
        ).to_dict()
        decided = [f["rule"] for f in record["findings"] if f.get("status") not in ("PASS", "NOT_APPLICABLE")]
        return Answer(q["qid"], self.name, record["verdict"], citations=decision_citations(record),
                      reason="rules not passing: " + (", ".join(decided) or "none"),
                      latency_s=time.perf_counter() - t0, tokens_in=meter.tokens_in,
                      tokens_out=meter.tokens_out, model_calls=meter.calls)  # fmt: skip
