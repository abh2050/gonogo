"""Make the spoken line for every step in docs/media/narration.json, and write each line's length.

    uv run python scripts/narrate.py            # ElevenLabs; needs ELEVENLABS_API_KEY in the environment or .env
    uv run python scripts/narrate.py --estimate # silent placeholders sized by word count, to test the timing

Audio goes to docs/media/audio/ (not committed). A line is made again only when its text, voice, or model changes.
docs/media/narration-timing.json holds {step key: seconds}, each line's length plus a short pause. The recorded walks
read it to decide how long to hold a step, so the picture is timed to the voice and not the other way round.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MEDIA = ROOT / "docs" / "media"
AUDIO = MEDIA / "audio"
PAUSE = 0.6  # seconds of quiet after each line
VOICE = os.environ.get("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")
MODEL = os.environ.get("ELEVENLABS_MODEL", "eleven_multilingual_v2")


def api_key() -> str:
    key = os.environ.get("ELEVENLABS_API_KEY", "")
    env = ROOT / ".env"
    if not key and env.exists():
        for line in env.read_text().splitlines():
            if line.startswith("ELEVENLABS_API_KEY="):
                key = line.split("=", 1)[1].strip()
    if not key:
        raise SystemExit("Set ELEVENLABS_API_KEY in the environment or in .env, or pass --estimate.")
    return key


def seconds(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(out.stdout.strip())


def speak(text: str, dest: Path, key: str) -> None:
    body = json.dumps(
        {"text": text, "model_id": MODEL, "voice_settings": {"stability": 0.55, "similarity_boost": 0.75}}
    )
    req = urllib.request.Request(
        f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE}?output_format=mp3_44100_128",
        data=body.encode(),
        headers={"xi-api-key": key, "Content-Type": "application/json", "Accept": "audio/mpeg"},
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        dest.write_bytes(r.read())


def silence(text: str, dest: Path) -> None:
    length = max(1.2, len(text.split()) / 2.6)  # about 156 words a minute
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono", "-t", f"{length:.2f}"]
        + ["-q:a", "9", str(dest)],
        check=True,
    )


def main(estimate: bool) -> None:
    lines = json.loads((MEDIA / "narration.json").read_text())
    AUDIO.mkdir(parents=True, exist_ok=True)
    key = "" if estimate else api_key()
    timing: dict[str, float] = {}
    made = 0
    for line in lines:
        tag = "est" if estimate else f"{VOICE}-{MODEL}"
        name = hashlib.sha1(f"{tag}|{line['text']}".encode()).hexdigest()[:16]
        dest = AUDIO / f"{name}.mp3"
        if not dest.exists():
            silence(line["text"], dest) if estimate else speak(line["text"], dest, key)
            made += 1
        timing[line["key"]] = round(seconds(dest) + PAUSE, 3)
    tag = "est" if estimate else f"{VOICE}-{MODEL}"
    (AUDIO / "index.json").write_text(json.dumps(index(lines, tag), indent=1))
    (MEDIA / "narration-timing.json").write_text(json.dumps(timing, indent=1))
    print(f"{len(lines)} lines ({made} made), {sum(timing.values()):.0f} s of narration")


def index(lines: list[dict[str, str]], tag: str) -> dict[str, str]:
    """Which audio file belongs to which step key."""
    return {line["key"]: hashlib.sha1(f"{tag}|{line['text']}".encode()).hexdigest()[:16] + ".mp3" for line in lines}


if __name__ == "__main__":
    main("--estimate" in sys.argv)
