"""Answerer A: vector retrieval-augmented generation, and the parts it shares with answerer B.

The question goes to the Knowledge Base (gonogo-eval) as a search query. The top passages, each tagged with its
document id, go to the model with the clearance policy (eval/policy.md), and the model fills a fixed verdict form.
Nothing checks the model's reasoning: this is the baseline that a team would build first.
"""

from __future__ import annotations

import time
from typing import Any

from eval.answer import HAIKU, VERDICTS, Answer, Metered, bedrock
from eval.kb import outputs
from gonogo import aws
from gonogo.paths import ROOT

POLICY = (ROOT / "eval" / "policy.md").read_text()
TOP_K = 12
VERDICT_TOOL = {
    "toolSpec": {
        "name": "verdict",
        "description": "The clearance verdict, the document ids it rests on, and a short reason.",
        "inputSchema": {
            "json": {
                "type": "object",
                "properties": {
                    "verdict": {"type": "string", "enum": list(VERDICTS)},
                    "citations": {"type": "array", "items": {"type": "string"}},
                    "reason": {"type": "string"},
                },
                "required": ["verdict", "citations", "reason"],
            }
        },
    }
}


def retrieve(client: Any, text: str, k: int = TOP_K, patent: str | None = None) -> list[dict[str, Any]]:
    """The top passages for a query, each as {doc_id, kind, patents, text}. With a patent, only its documents."""
    config: dict[str, Any] = {"numberOfResults": k}
    if patent:
        config["filter"] = {"listContains": {"key": "patents", "value": patent}}
    out = client.retrieve(
        knowledgeBaseId=outputs()["KnowledgeBaseId"],
        retrievalQuery={"text": text[:1000]},
        retrievalConfiguration={"vectorSearchConfiguration": config},
    )
    passages = []
    for r in out["retrievalResults"]:
        meta = r.get("metadata", {})
        passages.append(
            {
                "doc_id": str(meta.get("doc_id", "")),
                "kind": str(meta.get("doc_kind", "")),
                "patents": meta.get("patents", []),
                "text": r["content"]["text"],
            }
        )
    return passages


def render(passages: list[dict[str, Any]]) -> str:
    return "\n\n".join(f'<document id="{p["doc_id"]}" kind="{p["kind"]}">\n{p["text"]}\n</document>' for p in passages)


def read_verdict(response: dict[str, Any]) -> dict[str, Any]:
    for block in response["output"]["message"]["content"]:
        if "toolUse" in block:
            return dict(block["toolUse"]["input"])
    return {"verdict": "ERROR", "citations": [], "reason": "the model returned no verdict"}


class VectorAnswerer:
    name = "A"

    def __init__(self, model_id: str = HAIKU) -> None:
        self.model_id = model_id
        self.client = bedrock()
        self.search = aws.session().client("bedrock-agent-runtime")

    def __call__(self, q: dict[str, Any]) -> Answer:
        meter = Metered(self.client)
        t0 = time.perf_counter()
        passages = retrieve(self.search, q["text"])
        response = meter.converse(
            modelId=self.model_id,
            system=[{"text": POLICY}],
            messages=[
                {
                    "role": "user",
                    "content": [{"text": f"{render(passages)}\n\nQuestion: {q['text']}"}],
                }
            ],
            toolConfig={"tools": [VERDICT_TOOL], "toolChoice": {"tool": {"name": "verdict"}}},
            inferenceConfig={"maxTokens": 800, "temperature": 0},
        )
        v = read_verdict(response)
        return Answer(
            q["qid"],
            self.name,
            v.get("verdict", "ERROR") if v.get("verdict") in VERDICTS else "ERROR",
            citations=sorted({str(c) for c in v.get("citations", [])}),
            reason=str(v.get("reason", ""))[:600],
            latency_s=time.perf_counter() - t0,
            tokens_in=meter.tokens_in,
            tokens_out=meter.tokens_out,
            model_calls=meter.calls,
            retrieved=sorted({p["doc_id"] for p in passages}),
        )
