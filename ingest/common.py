"""Shared HTTP cache for every ingestion module.

fetch() stores each response under data/raw/<source>/ in an envelope that records the
retrieval timestamp. A second call with the same request reads the cache and makes no
network call, so every ingestion module is idempotent unless --refresh is passed.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from gonogo.paths import PROCESSED, RAW

USER_AGENT = "GoNoGo/0.1 (portfolio research; https://github.com/abh2050/gonogo)"
POLITE_DELAY_S = 0.25


class Fetcher:
    def __init__(
        self, source: str, refresh: bool = False, raw_root: Path = RAW, headers: dict[str, str] | None = None
    ) -> None:
        """headers are sent with every request but never cached, so API keys stay out of data/raw/."""
        self.source = source
        self.headers = headers or {}
        self.refresh = refresh
        self.dir = raw_root / source
        self.dir.mkdir(parents=True, exist_ok=True)
        self.network_calls = 0
        self._client: httpx.Client | None = None

    @property
    def client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(
                headers={"User-Agent": USER_AGENT, **self.headers}, timeout=60.0, follow_redirects=True
            )
        return self._client

    def cache_path(self, method: str, url: str, params: dict[str, Any] | None, body: Any) -> Path:
        key = json.dumps([method, url, params or {}, body], sort_keys=True)
        return self.dir / f"{hashlib.sha1(key.encode()).hexdigest()}.json"

    def fetch(
        self,
        url: str,
        params: dict[str, Any] | list[tuple[str, str]] | None = None,
        method: str = "GET",
        json_body: Any = None,
        binary: bool = False,
        allow_status: Iterable[int] = (),
    ) -> dict[str, Any]:
        """Return the cached envelope for the request, fetching it when absent.

        The envelope holds retrieved_at, url, params, status, and body. Binary bodies are
        written next to the envelope and the envelope stores their file name.
        """
        norm_params = dict(params) if isinstance(params, dict) else None
        param_key: Any = norm_params if norm_params is not None else [list(p) for p in params or []]
        path = self.cache_path(method, url, param_key, json_body)
        if path.exists() and not self.refresh:
            return dict(json.loads(path.read_text()))

        resp = self._request(method, url, params, json_body)
        if resp.status_code >= 400 and resp.status_code not in set(allow_status):
            resp.raise_for_status()
        envelope: dict[str, Any] = {
            "retrieved_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "url": str(resp.request.url),
            "method": method,
            "params": param_key,
            "request_body": json_body,
            "status": resp.status_code,
            "content_type": resp.headers.get("content-type", ""),
        }
        if binary:
            blob = path.with_suffix(".bin")
            blob.write_bytes(resp.content)
            envelope["body_file"] = blob.name
        else:
            text = resp.text
            try:
                envelope["body"] = json.loads(text)
            except ValueError:
                envelope["body"] = text
        path.write_text(json.dumps(envelope, indent=1, sort_keys=True))
        return envelope

    @retry(
        retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=1, max=20),
        reraise=True,
    )
    def _request(self, method: str, url: str, params: Any, json_body: Any) -> httpx.Response:
        time.sleep(POLITE_DELAY_S)
        self.network_calls += 1
        resp = self.client.request(method, url, params=params, json=json_body)
        if resp.status_code in (429, 500, 502, 503, 504):
            resp.raise_for_status()
        return resp

    def close(self) -> None:
        if self._client is not None:
            self._client.close()


def write_jsonl(name: str, records: Iterable[dict[str, Any]], root: Path = PROCESSED) -> Path:
    """Write records in the order given, with sorted keys, so reruns are byte-identical."""
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{name}.jsonl"
    with path.open("w") as f:
        for rec in records:
            f.write(json.dumps(rec, sort_keys=True, ensure_ascii=False) + "\n")
    return path


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open() as f:
        return [json.loads(line) for line in f if line.strip()]


def write_meta(name: str, meta: dict[str, Any], root: Path = PROCESSED) -> Path:
    """Write run metadata. network_calls describes the run, not the data, so it stays out of the file."""
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{name}.meta.json"
    stable = {k: v for k, v in meta.items() if k != "network_calls"}
    path.write_text(json.dumps(stable, indent=2, sort_keys=True) + "\n")
    return path
