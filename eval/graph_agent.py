"""Answerer B: a Strands agent that answers from the graph through tools (eval/graph_tools.py).

The agent reads the question, looks up the patent, the concepts, and the licensee, pulls facts through the rules'
own SPARQL templates, and can search passages filtered to the patent. It applies the clearance policy
(eval/policy.md) itself, and ends by calling `final_answer`. This is graph-grounded retrieval: the retrieval is
exact, and the reasoning is the model's.

Run it locally (uv run --group agent python -m eval.run B) or on Fargate (service/agent_server.py); both use this
class.
"""

from __future__ import annotations

import time
from typing import Any

from agent.parser import Vocabulary
from eval.answer import HAIKU, VERDICTS, Answer
from eval.graph_tools import GraphTools
from eval.rag import POLICY
from gonogo import aws
from kg.store import Store

MAX_TURNS = 14
GUIDE = """
How to work:
1. Find the patent with find_patent. If it is not found, answer NEEDS INFO.
2. Find the field and territory concept ids with find_concept, and the licensee with find_licensee.
3. Call patent_records, overlapping_grants, and, for any request that is not non-exclusive, notices_for.
   If the question gives a date for records, pass it as records_before to every call.
4. Use search_documents only when the records leave a question open.
5. Apply the seven checks and the combination order, then call final_answer exactly once.
Cite the record ids that the tools returned (for example grant/executed/AGR-0001 or export/LAR-17240-1).
"""


class GraphAnswerer:
    name = "B"

    def __init__(self, store: Store | None = None, model_id: str = HAIKU) -> None:
        self.store = store or Store.from_build()
        self.tools = GraphTools(self.store, Vocabulary.from_store(self.store),
                                aws.session().client("bedrock-agent-runtime"))  # fmt: skip
        self.model_id = model_id

    def agent(self, answer: dict[str, Any]) -> Any:
        from botocore.config import Config
        from strands import Agent, tool
        from strands.models.bedrock import BedrockModel

        t = self.tools

        @tool
        def find_patent(reference: str) -> dict[str, Any]:
            """Find a patent by NASA case number, US patent number, or title words."""
            return t.find_patent(reference)

        @tool
        def find_concept(kind: str, words: str) -> dict[str, Any]:
            """Find the concept id of a field of use (kind="field") or a territory (kind="territory")."""
            return t.find_concept(kind, words)

        @tool
        def find_licensee(name: str) -> dict[str, Any]:
            """Find the licensee records for a company name, with each record's id and country."""
            return t.find_licensee(name)

        @tool
        def patent_records(patent_key: str, records_before: str = "") -> dict[str, Any]:
            """Legal status, filing date, export classification, ownership, and consent records for a patent."""
            return t.patent_records(patent_key, records_before or None)

        @tool
        def overlapping_grants(
            patent_key: str, field: str, territory: str, start: str, end: str, records_before: str = ""
        ) -> dict[str, Any]:
            """Executed grants and other parties' proposed grants whose field, territory, and term overlap the
            request. field and territory are concept ids; start and end are YYYY-MM-DD."""
            return t.overlapping_grants(patent_key, field, territory, start, end, records_before or None)

        @tool
        def notices_for(patent_key: str, licensee_ids: list[str], records_before: str = "") -> dict[str, Any]:
            """Notices of intent to license the patent to these licensee ids, with each objection deadline."""
            return t.notices_for(patent_key, licensee_ids, records_before or None)

        @tool
        def search_documents(patent_key: str, query: str) -> dict[str, Any]:
            """Passages from documents about one patent."""
            return t.search_documents(patent_key, query)

        @tool
        def final_answer(verdict: str, citations: list[str], reason: str) -> str:
            """Record the verdict (GO, NO GO, HOLD, COUNSEL, NO DATA, or NEEDS INFO), the record ids it rests on,
            and a short reason. Call this once, at the end."""
            answer.update(verdict=verdict, citations=citations, reason=reason)
            return "Recorded."

        model = BedrockModel(
            model_id=self.model_id,
            boto_session=aws.session(),
            boto_client_config=Config(read_timeout=300, retries={"max_attempts": 8, "mode": "adaptive"}),
            temperature=0,
            max_tokens=1200,
        )
        return Agent(
            model=model,
            system_prompt=POLICY + GUIDE,
            tools=[
                find_patent,
                find_concept,
                find_licensee,
                patent_records,
                overlapping_grants,
                notices_for,
                search_documents,
                final_answer,
            ],  # fmt: skip
            callback_handler=None,
        )

    def __call__(self, q: dict[str, Any]) -> Answer:
        answer: dict[str, Any] = {}
        t0 = time.perf_counter()
        agent = self.agent(answer)
        result = agent(q["text"])
        usage = result.metrics.accumulated_usage
        verdict = answer.get("verdict", "ERROR")
        return Answer(
            q["qid"],
            self.name,
            verdict if verdict in VERDICTS else "ERROR",
            citations=sorted({str(c) for c in answer.get("citations", [])}),
            reason=str(answer.get("reason", "the agent ended without calling final_answer"))[:600],
            latency_s=time.perf_counter() - t0,
            tokens_in=int(usage.get("inputTokens", 0)),
            tokens_out=int(usage.get("outputTokens", 0)),
            model_calls=int(result.metrics.cycle_count),
        )
