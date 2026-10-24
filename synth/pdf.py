"""Render a synthetic agreement as a PDF with one paragraph per clause.

reportlab runs in invariant mode, so the same agreement always produces the same bytes.
The clause spans in agreements.jsonl index the .txt file written next to each PDF; the PDF
carries the same clause text for Textract to read in Gate 3.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from reportlab import rl_config
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

rl_config.invariant = 1

_styles = getSampleStyleSheet()
TITLE = _styles["Title"]
BODY = ParagraphStyle("body", parent=_styles["BodyText"], fontSize=10.5, leading=14)
NOTICE = ParagraphStyle("notice", parent=BODY, textColor=colors.HexColor("#B00020"), fontName="Helvetica-Bold")


def render(agreement: dict[str, Any], path: Path) -> None:
    doc = SimpleDocTemplate(
        str(path),
        pagesize=letter,
        title=agreement["agreement_id"],
        author="GoNoGo synthetic generator",
        subject="Synthetic patent license agreement",
        creator="GoNoGo",
        invariant=1,
    )
    story: list[Any] = []
    for clause in agreement["clauses"]:
        style = {"title": TITLE, "notice": NOTICE}.get(clause["kind"], BODY)
        story.append(Paragraph(escape(clause["text"]), style))
        story.append(Spacer(1, 8))
    doc.build(story)
