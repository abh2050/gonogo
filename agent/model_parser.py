"""An optional model parser for requests the deterministic parser cannot read.

The model fills a fixed tool schema. Its answer is not trusted: every value must be a concept in a GoNoGo
scheme, a patent the graph holds, or an ISO date, and anything else is dropped and listed as missing. The
model never sees the graph and never writes a query. Set GONOGO_MODEL_PARSER=1 to use it; the public demo
and the tests do not.
"""

from __future__ import annotations

import os
import re
from datetime import date
from typing import Any

from agent.parser import FIELDS, Found, Parse, Vocabulary, parse, resolve_licensee
from rules.model import EXCLUSIVITY_TYPES

TOOL = {
    "toolSpec": {
        "name": "clearance_request",
        "description": "The parts of a patent license clearance request, copied from the user's words.",
        "inputSchema": {
            "json": {
                "type": "object",
                "properties": {
                    "licensee": {"type": "string", "description": "The company asking for the license"},
                    "patent": {"type": "string", "description": "A NASA case number or a US patent number"},
                    "exclusivity": {"type": "string", "enum": list(EXCLUSIVITY_TYPES)},
                    "field_of_use": {"type": "string", "description": "The field of use, in the user's words"},
                    "territory": {"type": "string", "description": "The country or region, in the user's words"},
                    "start": {"type": "string", "description": "Start date, YYYY-MM-DD"},
                    "end": {"type": "string", "description": "End date, YYYY-MM-DD"},
                },
            }
        },
    }
}
SYSTEM = (
    "Copy the parts of a license request into the tool. Leave out any part the user did not state. "
    "Do not infer dates, fields, or territories that are not in the text."
)


def enabled() -> bool:
    return os.environ.get("GONOGO_MODEL_PARSER") == "1"


def ask_model(text: str, client: Any, model_id: str) -> dict[str, Any]:
    response = client.converse(
        modelId=model_id,
        system=[{"text": SYSTEM}],
        messages=[{"role": "user", "content": [{"text": text}]}],
        toolConfig={"tools": [TOOL], "toolChoice": {"tool": {"name": "clearance_request"}}},
        inferenceConfig={"maxTokens": 400, "temperature": 0},
    )
    for block in response["output"]["message"]["content"]:
        if "toolUse" in block:
            return dict(block["toolUse"]["input"])
    return {}


def _iso(value: Any) -> str | None:
    try:
        return date.fromisoformat(str(value)).isoformat()
    except ValueError:
        return None


def check(proposal: dict[str, Any], vocab: Vocabulary, text: str) -> dict[str, Found]:
    """Keep only the proposed values that name something GoNoGo knows. Spans point at the user's words."""

    def span(raw: str) -> tuple[int, int]:
        i = text.lower().find(raw.lower())
        return (i, i + len(raw)) if i >= 0 else (-1, -1)

    out: dict[str, Found] = {}
    raw = str(proposal.get("patent", "")).strip()
    key = vocab.cases.get(raw.upper()) or vocab.patent_numbers.get(re.sub(r"\D", "", raw))
    if raw and key:
        out["patent_key"] = Found(key, span(raw), raw, raw, how="model")
    if (ex := proposal.get("exclusivity")) in EXCLUSIVITY_TYPES:
        out["exclusivity"] = Found(str(ex), span(str(ex).replace("-", " ")), str(ex), str(ex), how="model")
    for name, table, k in (("field_of_use", vocab.fields, "field"), ("territory", vocab.territories, "territory")):
        words = str(proposal.get(name, "")).strip().lower()
        if words in table:
            slug, label = table[words]
            out[k] = Found(slug, span(words), words, label, how="model")
    for k in ("start", "end"):
        if iso := _iso(proposal.get(k)):
            out[k] = Found(iso, (-1, -1), iso, how="model")
    if (lic := str(proposal.get("licensee", "")).strip()) and span(lic)[0] >= 0:
        out["licensee"] = Found(lic, span(lic), lic, how="model")
    return out


def parse_with_fallback(text: str, vocab: Vocabulary, client: Any = None, model_id: str | None = None) -> Parse:
    """Parse deterministically. If parts are missing and the model parser is on, ask the model for those parts."""
    result = parse(text, vocab)
    if result.complete or client is None or model_id is None:
        return result
    proposed = check(ask_model(text, client, model_id), vocab, text)
    for k in result.missing:
        if k in proposed:
            result.found[k] = proposed[k]
    if result.licensee is None:
        resolve_licensee(result, vocab)
    result.missing = [k for k in FIELDS if k not in result.found]
    result.parser = f"deterministic-v1+model:{model_id}"
    return result
