import json
from pathlib import Path

import httpx
import respx

from ingest.common import Fetcher, write_jsonl


@respx.mock
def test_second_fetch_reads_cache_without_network(tmp_path: Path) -> None:
    route = respx.get("https://example.test/data").mock(return_value=httpx.Response(200, json={"a": 1}))
    f1 = Fetcher("demo", raw_root=tmp_path)
    env1 = f1.fetch("https://example.test/data", params={"q": "x"})
    f2 = Fetcher("demo", raw_root=tmp_path)
    env2 = f2.fetch("https://example.test/data", params={"q": "x"})
    assert route.call_count == 1
    assert f1.network_calls == 1 and f2.network_calls == 0
    assert env1 == env2
    assert env1["body"] == {"a": 1}
    assert {"retrieved_at", "url", "params", "status"} <= set(env1)


@respx.mock
def test_refresh_fetches_again(tmp_path: Path) -> None:
    route = respx.get("https://example.test/data").mock(return_value=httpx.Response(200, text="plain"))
    Fetcher("demo", raw_root=tmp_path).fetch("https://example.test/data")
    Fetcher("demo", raw_root=tmp_path, refresh=True).fetch("https://example.test/data")
    assert route.call_count == 2


@respx.mock
def test_binary_body_is_stored_next_to_envelope(tmp_path: Path) -> None:
    respx.get("https://example.test/a.pdf").mock(return_value=httpx.Response(200, content=b"%PDF-1.4"))
    env = Fetcher("demo", raw_root=tmp_path).fetch("https://example.test/a.pdf", binary=True)
    assert (tmp_path / "demo" / env["body_file"]).read_bytes() == b"%PDF-1.4"


def test_write_jsonl_is_byte_stable(tmp_path: Path) -> None:
    recs = [{"b": 2, "a": 1}]
    p1 = write_jsonl("x", recs, root=tmp_path).read_bytes()
    p2 = write_jsonl("x", recs, root=tmp_path).read_bytes()
    assert p1 == p2 == (json.dumps({"a": 1, "b": 2}) + "\n").encode()
