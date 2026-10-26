"""The golden question set: eval/golden.jsonl.

    uv run python -m eval.golden

Every planted case in data/synthetic/injected_conflicts.json becomes four questions with the same meaning and the
same expected verdict, worded four ways:

- formal: the request exactly as the generator wrote it,
- casual: the way a colleague might ask in chat,
- terse: a shorthand note,
- noisy: the formal request with irrelevant detail around it, and the patent named by its title.

The expected verdict comes from how the case was planted (stated by hand in synth/generator.py), never from the rule
engine, so scoring the rule engine against it is not circular. Each question also carries the evidence a good answer
should cite: the documents planted for the case, and every document about its patent.

Twenty questions cannot be answered as asked: a part of the request is missing, or the patent is not one NASA lists
in scope. Their expected answer is NEEDS INFO, and a GO on any of them counts as a false GO.

Four wordings of one case are not four independent tests. eval/results.md reports results per question and per case.
"""

from __future__ import annotations

import csv
import json
import re
from typing import Any

from gonogo.paths import ROOT

OUT = ROOT / "eval" / "golden.jsonl"
SYN = ROOT / "data" / "synthetic"
NEEDS_INFO = "NEEDS INFO"
REQUEST = re.compile(
    r"^(?P<lic>.+?) wants an? (?P<excl>[a-z -]+?) license to (?:NASA case (?P<key>\S+)|US Patent (?P<num>[\d,]+)) "
    r"for (?P<field>.+?) in (?P<terr>.+?) from (?P<start>[A-Z][a-z]+ \d{1,2}, \d{4}) "
    r"to (?P<end>[A-Z][a-z]+ \d{1,2}, \d{4})\.$"
)
NOISE = (
    "Background: their team met our tech transfer office at a conference last spring, and they also asked about "
    "pricing and a possible joint press release. "
)
# Case numbers in the same format as real ones that are not in scope, for the unanswerable questions.
UNKNOWN_CASES = ["LAR-99901-1", "GSC-99902-1", "LEW-99903-1", "ARC-99904-1", "KSC-99905-1", "MSC-99906-1",
                 "LAR-99907-2"]  # fmt: skip


def article(word: str) -> str:
    return "an" if word[0] in "aeiou" else "a"


def when(case: dict[str, Any], default_cutoff: str) -> str:
    """The question states its dates when they differ from the defaults, so every answerer sees them."""
    if case["recording_cutoff"] != default_cutoff:
        return f" Answer as of {case['as_of']}, using only records entered before {case['recording_cutoff'][:10]}."
    return ""


def phrasings(m: re.Match[str], title: str, key: str, extra: str) -> dict[str, str]:
    g = m.groupdict()
    ref = f"NASA case {g['key']}" if g["key"] else f"US Patent {g['num']}"
    a = article(g["excl"])
    formal = m.string + extra
    return {
        "formal": formal,
        "casual": (
            f"Hi, quick one. {g['lic']} is asking whether they can get {a} {g['excl']} license on {ref}. They want "
            f"it for {g['field']}, in {g['terr']}, starting {g['start']} and running to {g['end']}. Are we clear "
            f"to do that?{extra}"
        ),
        "terse": (
            f"{g['excl'].capitalize()} license, {ref}, to {g['lic'].rstrip('.')}. Field: {g['field']}. "
            f"Territory: {g['terr']}. Term: {g['start']} to {g['end']}.{extra}"
        ),
        "noisy": (
            f'{NOISE}{g["lic"]} wants {a} {g["excl"]} license to the patent titled "{title}" (NASA case {key}) '
            f"for {g['field']} in {g['terr']} from {g['start']} to {g['end']}. They mentioned they would like an "
            f"answer before the end of the quarter.{extra}"
        ),
    }


def unanswerable(base: list[re.Match[str]]) -> list[dict[str, Any]]:
    """Twenty questions that leave out a required part, or name a patent that is not in scope."""
    out: list[dict[str, Any]] = []
    for m in base[:7]:
        g = m.groupdict()
        ref = f"NASA case {g['key']}" if g["key"] else f"US Patent {g['num']}"
        text = f"{g['lic']} wants {article(g['excl'])} {g['excl']} license to {ref} in {g['terr']} "
        out.append({"why": "no field of use", "text": text + f"from {g['start']} to {g['end']}."})
    for i, m in enumerate(base[7:14]):
        g = m.groupdict()
        text = f"{g['lic']} wants {article(g['excl'])} {g['excl']} license to NASA case {UNKNOWN_CASES[i]} "
        out.append({"why": "patent not in scope", "text": text + f"for {g['field']} in {g['terr']} from {g['start']} "
                    f"to {g['end']}."})  # fmt: skip
    for m in base[14:20]:
        g = m.groupdict()
        ref = f"NASA case {g['key']}" if g["key"] else f"US Patent {g['num']}"
        out.append({"why": "no license type or term", "text": f"Can {g['lic']} license {ref} for {g['field']} in "
                    f"{g['terr']}?"})  # fmt: skip
    return out


def build() -> list[dict[str, Any]]:
    injected = json.loads((SYN / "injected_conflicts.json").read_text())
    requests = {r["request_id"]: r for r in map(json.loads, (SYN / "requests.jsonl").read_text().splitlines())}
    with (ROOT / "data" / "scope" / "patents_in_scope.csv").open() as f:
        titles = {r["patent_key"]: r["title"] for r in csv.DictReader(f)}
    rows: list[dict[str, Any]] = []
    matches: list[re.Match[str]] = []
    for case in injected["cases"]:
        req = requests[case["request_id"]]
        m = REQUEST.match(req["text"])
        if not m:
            raise ValueError(f"{case['request_id']} does not follow the request template: {req['text']}")
        matches.append(m)
        evidence = sorted(
            set(case.get("conflicting_agreements", []))
            | set(case.get("related_agreements", []))
            | set(case.get("related_notices", []))
        )
        for style, text in phrasings(m, titles[case["patent_key"]], case["patent_key"], when(case, injected[
            "default_recording_cutoff"])).items():  # fmt: skip
            rows.append(
                {
                    "qid": f"{case['case_id']}-{style}",
                    "case_id": case["case_id"],
                    "case_type": case["type"],
                    "style": style,
                    "text": text,
                    "patent_key": case["patent_key"],
                    "as_of": case["as_of"],
                    "recording_cutoff": case["recording_cutoff"],
                    "expected_verdict": case["expected_verdict"],
                    "expected_statuses": case["expected_statuses"],
                    "decisive_evidence": sorted(case.get("conflicting_agreements", [])),
                    "planted_evidence": evidence,
                }
            )
    seen: set[str] = set()
    distinct = [m for m in matches if not (m.string in seen or seen.add(m.string))]  # type: ignore[func-returns-value]
    for i, q in enumerate(unanswerable(distinct)):
        rows.append(
            {
                "qid": f"UNA-{i + 1:03}",
                "case_id": f"UNA-{i + 1:03}",
                "case_type": q["why"],
                "style": "unanswerable",
                "text": q["text"],
                "patent_key": None,
                "as_of": injected["as_of"],
                "recording_cutoff": injected["default_recording_cutoff"],
                "expected_verdict": NEEDS_INFO,
                "expected_statuses": {},
                "decisive_evidence": [],
                "planted_evidence": [],
            }
        )
    return rows


if __name__ == "__main__":
    rows = build()
    OUT.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    print(f"wrote {OUT.relative_to(ROOT)}: {len(rows)} questions")
