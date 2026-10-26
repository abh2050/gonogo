"""Make one short abstract clip with the Higgsfield API and save it under docs/media/.

    uv run python scripts/higgsfield_clip.py intro "<prompt>"

The key comes from HF_CREDENTIALS in .env (key id and secret joined by a colon), and the call runs here on the server
side, because the secret must never reach a browser. One call, one clip, one charge against the prepaid balance.
The prompt asks for no text, because generated lettering comes out garbled. Real labels are laid on afterwards.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
BASE = "https://api.higgsfield.ai"
MODEL = "/minimax/hailuo-2.3/standard/text-to-video"


def load_key() -> str:
    for line in (ROOT / ".env").read_text().splitlines():
        if line.startswith("HF_CREDENTIALS="):
            return line.split("=", 1)[1].strip()
    return os.environ["HF_CREDENTIALS"]


def main() -> None:
    name, prompt = sys.argv[1], sys.argv[2]
    headers = {"Authorization": f"Key {load_key()}", "Content-Type": "application/json"}
    with httpx.Client(base_url=BASE, headers=headers, timeout=60) as c:
        r = c.post(MODEL, json={"prompt": prompt, "duration": 6})
        print("submit", r.status_code, r.text[:300].replace(load_key(), "<key>"))
        r.raise_for_status()
        request_id = r.json()["request_id"]
        for wait in [4, 6, 8, 10, 15, 15, 20, 20, 30, 30, 30, 30]:
            time.sleep(wait)
            status = c.get(f"/requests/{request_id}/status").json()
            print("status", status.get("status"))
            if status.get("status") in {"completed", "failed", "nsfw", "canceled"}:
                break
        if status.get("status") != "completed":
            raise SystemExit(f"Not completed: {status}")
        video = status["video"]["url"] if "video" in status else status["videos"][0]["url"]
        out = ROOT / "docs" / "media" / f"{name}.mp4"
        out.write_bytes(httpx.get(video, timeout=120, follow_redirects=True).content)
        print(f"wrote {out.relative_to(ROOT)} ({out.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
