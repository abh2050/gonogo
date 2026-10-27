"""Join the intro, the five walks, and an outro into docs/media/gonogo-overview.mp4, with each spoken line placed at
the moment its step appears.

    uv run python scripts/narrate.py                       # the spoken lines and their lengths
    (record the walks: ontology_gif, provenance_walk, architecture_walk, diagram_walk)
    uvx --with playwright python scripts/assemble_video.py

Every walk writes <name>.marks.json: the second at which each step began. A line is delayed to its step's mark, and
each segment's audio is padded to the segment's exact length, so nothing drifts when the segments are joined. The
script prints each line's start, length, and hold, and fails if a line runs past the start of the next step.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
MEDIA = ROOT / "docs" / "media"
AUDIO = MEDIA / "audio"
LEAD = 0.15  # the picture changes just before the voice starts
W, H = 1280, 720
# (segment, video, background colour for padding)
SEGMENTS = [
    ("intro", None, "0x000814"),
    ("ontology-walk", MEDIA / "ontology-walk.mp4", "0xf7f6f2"),
    ("provenance-walk", MEDIA / "provenance-walk.mp4", "0xf7f6f2"),
    ("architecture-walk", MEDIA / "architecture-walk.mp4", "0xf7f6f2"),
    ("diagram-walk", MEDIA / "diagram-walk.mp4", "0xffffff"),
    ("benchmark-walk", MEDIA / "benchmark-walk.mp4", "0xf7f6f2"),
    ("outro", None, "0x0f1722"),
]
CARD = """<body style="margin:0;width:{w}px;height:{h}px;background:{bg};display:flex;flex-direction:column;
justify-content:center;align-items:center;font-family:Helvetica,Arial,sans-serif;color:#fff">
<div style="font-size:84px;font-weight:700;letter-spacing:2px;text-shadow:0 2px 24px #000">{big}</div>
<div style="font-size:30px;margin-top:18px;max-width:1000px;text-align:center;text-shadow:0 2px 16px #000;
opacity:.92">{small}</div></body>"""


def ff(*args: str) -> None:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], check=True)


def seconds(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(out.stdout.strip())


def cards(tmp: Path) -> tuple[Path, Path]:
    title, outro = tmp / "title.png", tmp / "outro.png"
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome")
        page = b.new_page(viewport={"width": W, "height": H})
        page.set_content(
            CARD.format(w=W, h=H, bg="transparent", big="GoNoGo", small="An ontology decides. The model only reads.")
        )
        page.screenshot(path=str(title), omit_background=True)
        page.set_content(
            CARD.format(
                w=W,
                h=H,
                bg="#0f1722",
                big="Every verdict has a source",
                small="Seven rules · one knowledge graph · full provenance<br>github.com/abh2050/gonogo",
            )
        )
        page.screenshot(path=str(outro))
        b.close()
    return title, outro


def picture(name: str, video: Path | None, bg: str, length: float, tmp: Path, title: Path, outro: Path) -> Path:
    """The segment's video at 1280x720 and 30 fps, held on its last frame until `length` if it is shorter."""
    out = tmp / f"{name}-v.mp4"
    fit = f"scale=-2:{H},pad={W}:{H}:(ow-iw)/2:0:color={bg},setsar=1,fps=30"
    if name == "intro":  # slowed to fit the line, so the graph keeps moving instead of freezing
        slow = max(1.0, length / seconds(MEDIA / "graph-intro.mp4"))
        ff(
            "-i", str(MEDIA / "graph-intro.mp4"), "-i", str(title), "-filter_complex",
            f"[0:v]setpts={slow:.4f}*PTS,scale={W}:{H},setsar=1,fps=30[a];[a][1:v]overlay=0:0:enable='gte(t,1.2)',"
            f"tpad=stop_mode=clone:stop_duration={length},trim=0:{length},format=yuv420p",
            "-an", str(out),
        )  # fmt: skip
    elif name == "outro":
        ff("-loop", "1", "-t", f"{length}", "-i", str(outro), "-vf", "fps=30,format=yuv420p", str(out))
    else:
        assert video is not None
        ff(
            "-i", str(video), "-vf",
            f"{fit},tpad=stop_mode=clone:stop_duration={length},trim=0:{length},format=yuv420p", "-an", str(out),
        )  # fmt: skip
    return out


def main() -> None:
    files = json.loads((AUDIO / "index.json").read_text())
    timing = json.loads((MEDIA / "narration-timing.json").read_text())
    tmp = Path(tempfile.mkdtemp())
    title, outro = cards(tmp)
    parts: list[Path] = []
    srt: list[str] = []
    lines = {x["key"]: x["text"] for x in json.loads((MEDIA / "narration.json").read_text())}
    clock = 0.0
    for name, video, bg in SEGMENTS:
        marks = {name: 0.4} if video is None else json.loads((MEDIA / f"{name}.marks.json").read_text())
        keys = sorted(marks, key=marks.get)  # type: ignore[arg-type]
        end = max(marks[k] + timing[k] for k in keys) + 0.3
        length = max(end, seconds(video) if video else 0.0)
        for i, k in enumerate(keys):
            spoken = seconds(AUDIO / files[k])
            nxt = marks[keys[i + 1]] if i + 1 < len(keys) else length
            start = marks[k] + LEAD
            print(f"{name:18} {k:34} at {clock + start:7.2f}s  line {spoken:5.2f}s  room {nxt - start:5.2f}s")
            if start + spoken > nxt + 0.05:
                raise SystemExit(f"The line for {k} runs past the next step by {start + spoken - nxt:.2f}s")
            srt.append(f"{len(srt) + 1}\n{stamp(clock + start)} --> {stamp(clock + start + spoken)}\n{lines[k]}\n")
        pic = picture(name, video, bg, length, tmp, title, outro)
        inputs: list[str] = []
        chains: list[str] = []
        for i, k in enumerate(keys):
            ms = int((marks[k] + LEAD) * 1000)
            inputs += ["-i", str(AUDIO / files[k])]
            chains.append(f"[{i + 1}:a]aresample=48000,aformat=channel_layouts=stereo,adelay={ms}|{ms}[a{i}]")
        mix = "".join(f"[a{i}]" for i in range(len(keys)))
        graph = ";".join(chains) + f";{mix}amix=inputs={len(keys)}:normalize=0,apad=whole_dur={length},"
        graph += f"atrim=0:{length}[aout]"
        seg = tmp / f"{name}.mp4"
        ff("-i", str(pic), *inputs, "-filter_complex", graph, "-map", "0:v", "-map", "[aout]",
           "-c:v", "libx264", "-crf", "24", "-c:a", "aac", "-b:a", "160k", "-t", f"{length}", str(seg))  # fmt: skip
        parts.append(seg)
        clock += length
    n = len(parts)
    ins = [a for p in parts for a in ("-i", str(p))]
    joined = "".join(f"[{i}:v][{i}:a]" for i in range(n)) + f"concat=n={n}:v=1:a=1[v][a]"
    out = MEDIA / "gonogo-overview.mp4"
    ff(*ins, "-filter_complex", joined, "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-crf", "24",
       "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(out))  # fmt: skip
    (MEDIA / "gonogo-overview.srt").write_text("\n".join(srt))
    print(f"wrote {out.relative_to(ROOT)}: {seconds(out):.1f}s (segments add up to {clock:.1f}s)")


def stamp(t: float) -> str:
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h):02}:{int(m):02}:{int(s):02},{int(round((s % 1) * 1000)):03}"


if __name__ == "__main__":
    main()
