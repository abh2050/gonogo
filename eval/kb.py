"""Load the corpus into the benchmark's Knowledge Base, and look up the stack's outputs.

    uv run python -m eval.kb            # upload data/eval/corpus/ and run an ingestion job

The stack is gonogo-eval (infra/stacks.py, EvalStack). Uploading skips files whose content has not changed, and the
ingestion job embeds only what changed, so a second run is cheap.
"""

from __future__ import annotations

import hashlib
import time
from concurrent.futures import ThreadPoolExecutor
from functools import cache
from typing import Any

from eval.corpus import OUT as CORPUS
from gonogo import aws


@cache
def outputs() -> dict[str, str]:
    cf = aws.session().client("cloudformation")
    stack = cf.describe_stacks(StackName="gonogo-eval")["Stacks"][0]
    return {o["OutputKey"]: o["OutputValue"] for o in stack.get("Outputs", [])}


def upload() -> int:
    s3 = aws.session().client("s3")
    bucket = outputs()["CorpusBucket"]
    have: dict[str, str] = {}
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket):
        for o in page.get("Contents", []):
            have[o["Key"]] = o["ETag"].strip('"')
    files = sorted(CORPUS.iterdir())

    def put(path: Any) -> int:
        body = path.read_bytes()
        if have.get(path.name) == hashlib.md5(body).hexdigest():  # noqa: S324 - S3's ETag for a single-part upload
            return 0
        s3.put_object(Bucket=bucket, Key=path.name, Body=body)
        return 1

    with ThreadPoolExecutor(max_workers=16) as pool:
        sent = sum(pool.map(put, files))
    stale = set(have) - {f.name for f in files}
    for key in sorted(stale):
        s3.delete_object(Bucket=bucket, Key=key)
    return sent


def ingest() -> dict[str, Any]:
    agent = aws.session().client("bedrock-agent")
    kb, ds = outputs()["KnowledgeBaseId"], outputs()["DataSourceId"]
    job = agent.start_ingestion_job(knowledgeBaseId=kb, dataSourceId=ds)["ingestionJob"]
    while job["status"] in ("STARTING", "IN_PROGRESS"):
        time.sleep(10)
        job = agent.get_ingestion_job(knowledgeBaseId=kb, dataSourceId=ds, ingestionJobId=job["ingestionJobId"])[
            "ingestionJob"
        ]
    return {"status": job["status"], **job.get("statistics", {}), "failures": job.get("failureReasons", [])[:5]}


if __name__ == "__main__":
    print("uploaded", upload(), "changed files")
    print(ingest())
