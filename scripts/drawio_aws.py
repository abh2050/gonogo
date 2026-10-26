"""Write docs/architecture/gonogo-aws.drawio: seven pages of AWS diagrams drawn with draw.io's AWS icon set, and a PNG
of each page next to it.

    uv run python scripts/drawio_aws.py

Pages: 1 system overview, 2 request path, 3 ingestion workflow, 4 security and network, 5 data and access,
6 benchmark, 7 stacks and cost. Each is built from code so it can be regenerated when the stacks change; open the
.drawio file in draw.io to edit by hand. The services are the ones infra/stacks.py deploys, and page 5 reads its
role-to-graph grid from the Cedar policies themselves.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from xml.sax.saxutils import quoteattr

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OUT = ROOT / "docs" / "architecture"

INK, MUTED, LINE = "#232F3E", "#545B64", "#879196"
CATEGORY = {"net": "#8C4FFF", "compute": "#ED7100", "store": "#7AA116", "sec": "#DD344C", "db": "#C925D1",
            "app": "#E7157B", "ml": "#01A88D", "mgmt": "#E7157B"}  # fmt: skip
ZONE = {  # fill, stroke
    "edge": ("#F4EFFF", "#8C4FFF"),
    "identity": ("#FDEEEF", "#DD344C"),
    "decide": ("#FFF4E8", "#ED7100"),
    "record": ("#F9EEFB", "#C925D1"),
    "graph": ("#F2F8EA", "#7AA116"),
    "ingest": ("#FDEEF5", "#E7157B"),
    "bench": ("#E8F7F4", "#01A88D"),
    "cost": ("#F2F3F3", "#879196"),
    "people": ("#F2F3F3", "#545B64"),
}


class Page:
    def __init__(self, name: str, width: int, height: int) -> None:
        self.name, self.width, self.height = name, width, height
        self.cells: list[str] = []
        self.n = 0

    def _id(self, prefix: str) -> str:
        self.n += 1
        return f"{prefix}{self.n}"

    def _vertex(self, cid: str, value: str, style: str, x: float, y: float, w: float, h: float) -> str:
        self.cells.append(
            f'<mxCell id="{cid}" value={quoteattr(value)} style={quoteattr(style)} vertex="1" parent="1">'
            f'<mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry"/></mxCell>'
        )
        return cid

    def title(self, text: str, sub: str) -> None:
        self._vertex(self._id("t"), text, f"text;html=1;fontSize=24;fontStyle=1;fontColor={INK};align=left;"
                     "verticalAlign=top;whiteSpace=wrap;", 30, 20, self.width - 60, 36)  # fmt: skip
        self._vertex(self._id("s"), sub, f"text;html=1;fontSize=14;fontColor={MUTED};align=left;verticalAlign=top;"
                     "whiteSpace=wrap;", 30, 58, self.width - 60, 44)  # fmt: skip

    def zone(self, key: str, label: str, x: float, y: float, w: float, h: float, dashed: bool = False) -> str:
        fill, stroke = ZONE[key]
        style = (f"rounded=1;arcSize=4;whiteSpace=wrap;html=1;fillColor={fill};strokeColor={stroke};strokeWidth=1.5;"
                 f"verticalAlign=top;align=left;spacingLeft=12;spacingTop=6;fontSize=14;fontStyle=1;fontColor={stroke};"
                 f"{'dashed=1;' if dashed else ''}")  # fmt: skip
        return self._vertex(self._id("z"), label, style, x, y, w, h)

    def group(self, kind: str, label: str, x: float, y: float, w: float, h: float) -> str:
        """An AWS group frame: cloud, region, vpc, or subnet."""
        icon, color, fill = {
            "cloud": ("group_aws_cloud_alt", INK, "none"),
            "region": ("group_region", "#00A4A6", "none"),
            "vpc": ("group_vpc", "#8C4FFF", "none"),
            "subnet": ("group_security_group", "#147EBA", "#E6F2F8"),
        }[kind]
        style = (f"points=[];outlineConnect=0;gradientColor=none;html=1;whiteSpace=wrap;fontSize=13;fontStyle=1;"
                 f"container=0;collapsible=0;recursiveResize=0;shape=mxgraph.aws4.group;grIcon=mxgraph.aws4.{icon};"
                 f"strokeColor={color};fillColor={fill};verticalAlign=top;align=left;spacingLeft=30;fontColor={color};"
                 f"{'dashed=1;' if kind == 'region' else ''}")  # fmt: skip
        return self._vertex(self._id("g"), label, style, x, y, w, h)

    def icon(self, icon: str, cat: str, label: str, x: float, y: float, where: str = "bottom", size: int = 56) -> str:
        pos = {
            "bottom": "verticalLabelPosition=bottom;verticalAlign=top;align=center;",
            "top": "verticalLabelPosition=top;verticalAlign=bottom;align=center;",
            "right": "labelPosition=right;verticalLabelPosition=middle;verticalAlign=middle;align=left;spacingLeft=6;",
        }[where]
        if icon == "user":  # AWS's "User" is a plain outline figure, not a service square
            style = (f"sketch=0;outlineConnect=0;fontColor={INK};gradientColor=none;fillColor=#232F3D;strokeColor=none;"
                     f"dashed=0;html=1;fontSize=12;aspect=fixed;pointerEvents=1;{pos}shape=mxgraph.aws4.user;")  # fmt: skip
        else:  # the official service icon: a white glyph on the service category's color, as in AWS's icon set
            style = (f"sketch=0;outlineConnect=0;fontColor={INK};gradientColor=none;fillColor={CATEGORY[cat]};"
                     f"strokeColor=#ffffff;dashed=0;html=1;fontSize=12;aspect=fixed;{pos}"
                     f"shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.{icon};")  # fmt: skip
        return self._vertex(self._id("i"), label, style, x, y, size, size)

    def box(self, label: str, x: float, y: float, w: float, h: float, fill: str = "#FFFFFF", stroke: str = LINE,
            size: int = 12, bold: bool = False, align: str = "center", font: str = INK, rounded: bool = True) -> str:  # fmt: skip
        style = (f"rounded={1 if rounded else 0};arcSize=10;whiteSpace=wrap;html=1;fillColor={fill};strokeColor={stroke};"
                 f"fontSize={size};fontColor={font};align={align};verticalAlign=middle;spacing=8;"
                 f"{'fontStyle=1;' if bold else ''}")  # fmt: skip
        return self._vertex(self._id("b"), label, style, x, y, w, h)

    def note(self, html: str, x: float, y: float, w: float, h: float) -> str:
        style = (f"rounded=1;arcSize=4;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#D5DBDB;fontSize=12;"
                 f"fontColor={INK};align=left;verticalAlign=top;spacing=10;")  # fmt: skip
        return self._vertex(self._id("n"), html, style, x, y, w, h)

    def text(self, html: str, x: float, y: float, w: float, h: float, size: int = 12, color: str = MUTED,
             align: str = "left") -> str:  # fmt: skip
        return self._vertex(self._id("x"), html, f"text;html=1;fontSize={size};fontColor={color};align={align};"
                            "verticalAlign=top;whiteSpace=wrap;", x, y, w, h)  # fmt: skip

    def badge(self, n: int, x: float, y: float, color: str = INK) -> str:
        return self._vertex(self._id("k"), str(n), f"ellipse;whiteSpace=wrap;html=1;fillColor={color};strokeColor=#FFFFFF;"
                            "strokeWidth=2;fontColor=#FFFFFF;fontStyle=1;fontSize=12;", x, y, 24, 24)  # fmt: skip

    def diamond(self, label: str, x: float, y: float, w: float = 110, h: float = 70) -> str:
        return self._vertex(self._id("d"), label, f"rhombus;whiteSpace=wrap;html=1;fillColor=#FFF9E6;"
                            f"strokeColor=#C27A05;fontSize=11;fontColor={INK};", x, y, w, h)  # fmt: skip

    def store(self, label: str, x: float, y: float, w: float, h: float, fill: str, stroke: str) -> str:
        return self._vertex(self._id("c"), label, f"shape=cylinder3;whiteSpace=wrap;html=1;boundedLbl=1;size=10;"
                            f"fillColor={fill};strokeColor={stroke};fontSize=12;fontColor={INK};fontStyle=1;",
                            x, y, w, h)  # fmt: skip

    def edge(self, a: str, b: str, label: str = "", *, dashed: bool = False, color: str = MUTED, exit: str = "",
             entry: str = "", width: float = 1.75, points: list[tuple[float, float]] | None = None,
             curved: bool = False) -> None:  # fmt: skip
        anchors = ""
        if exit:
            ex, ey = exit.split(",")
            anchors += f"exitX={ex};exitY={ey};exitDx=0;exitDy=0;"
        if entry:
            nx, ny = entry.split(",")
            anchors += f"entryX={nx};entryY={ny};entryDx=0;entryDy=0;"
        shape = "curved=1;" if curved else "edgeStyle=orthogonalEdgeStyle;rounded=1;"
        style = (f"{shape}html=1;endArrow=block;endFill=1;strokeColor={color};strokeWidth={width};fontSize=11;"
                 f"fontColor={MUTED};labelBackgroundColor=#FFFFFF;{'dashed=1;' if dashed else ''}{anchors}")  # fmt: skip
        pts = ""
        if points:
            pts = '<Array as="points">' + "".join(f'<mxPoint x="{x}" y="{y}"/>' for x, y in points) + "</Array>"
        self.cells.append(
            f'<mxCell id="{self._id("e")}" value={quoteattr(label)} style={quoteattr(style)} edge="1" parent="1" '
            f'source="{a}" target="{b}"><mxGeometry relative="1" as="geometry">{pts}</mxGeometry></mxCell>'
        )

    def line(self, x1: float, y1: float, x2: float, y2: float, label: str = "", *, dashed: bool = False,
             arrow: bool = True, color: str = MUTED, width: float = 1.5, align: str = "center",
             above: bool = False) -> None:  # fmt: skip
        """A free line between two points: lifelines and the messages of a sequence diagram. A label `above` the
        line never hides it, however short the line is."""
        background = "none" if above else "#FFFFFF"
        style = (f"html=1;endArrow={'block' if arrow else 'none'};endFill=1;strokeColor={color};strokeWidth={width};"
                 f"fontSize=11;fontColor={INK};labelBackgroundColor={background};align={align};"
                 f"{'dashed=1;' if dashed else ''}")  # fmt: skip
        offset = '<mxPoint x="0" y="-10" as="offset"/>' if above else ""
        self.cells.append(
            f'<mxCell id="{self._id("l")}" value={quoteattr(label)} style={quoteattr(style)} edge="1" parent="1">'
            f'<mxGeometry relative="1" as="geometry"><mxPoint x="{x1}" y="{y1}" as="sourcePoint"/>'
            f'<mxPoint x="{x2}" y="{y2}" as="targetPoint"/>{offset}</mxGeometry></mxCell>'
        )

    def legend(self, x: float, y: float, items: list[tuple[str, str, bool]]) -> None:
        self.box("", x, y, 250, 30 + 24 * len(items), fill="#FFFFFF", stroke="#D5DBDB")
        self.text("<b>Legend</b>", x + 12, y + 6, 200, 20, color=INK)
        for i, (label, color, dashed) in enumerate(items):
            yy = y + 38 + 24 * i
            self.line(x + 14, yy, x + 64, yy, dashed=dashed, color=color, width=2)
            self.text(label, x + 74, yy - 9, 170, 20, color=INK)

    def xml(self, pid: str) -> str:
        return (
            f'<diagram name={quoteattr(self.name)} id="{pid}"><mxGraphModel dx="{self.width}" dy="{self.height}" '
            f'grid="0" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" '
            f'pageWidth="{self.width}" pageHeight="{self.height}" background="#FFFFFF" math="0" shadow="0"><root>'
            f'<mxCell id="0"/><mxCell id="1" parent="0"/>{"".join(self.cells)}</root></mxGraphModel></diagram>'
        )


# ---- Page 1: system overview -------------------------------------------------------------------------------------


def overview() -> Page:
    p = Page("1. System overview", 1760, 1160)
    p.title("GoNoGo on AWS: the whole system",
            "Region us-east-2, deployed with the AWS CDK in Python. Numbers follow one clearance question from the "
            "browser to a stored, signed decision. Seven rules decide every verdict; no model decides one.")  # fmt: skip
    p.zone("people", "Who", 30, 120, 140, 420)
    person = p.icon("user", "sec", "Licensing manager,<br>steward, counsel,<br>and three more roles", 70, 330)
    p.zone("edge", "Edge", 190, 120, 200, 420)
    site = p.icon("s3", "store", "S3: the app<br>private, OAC only", 262, 200, where="top")
    cf = p.icon("cloudfront", "net", "CloudFront<br>one HTTPS address,<br>strict CSP", 262, 330)
    p.zone("identity", "Identity and policy", 410, 120, 360, 420)
    cog = p.icon("cognito", "sec", "Cognito<br>one role group per user", 470, 200, where="top")
    gw = p.icon("api_gateway", "net", "API Gateway<br>token check, schema<br>validation, 20 req/s", 470, 330)
    avp = p.icon("verified_permissions", "sec", "Verified Permissions<br>21 Cedar policies", 650, 200)
    p.zone("decide", "Decide", 790, 120, 280, 420)
    eng = p.icon("lambda", "compute", "Engine Lambda<br>parser, 7 rules,<br>combiner, steward loop", 902, 330)
    cedar = p.box("Cedar in process<br><i>same policy text</i>", 860, 200, 140, 50, fill="#FFF4E8", stroke="#ED7100")
    p.zone("record", "Record", 1090, 120, 300, 420)
    ddb = p.icon("dynamodb", "db", "DynamoDB<br>one row per decision", 1120, 165, where="right")
    aud = p.icon("s3", "store", "S3 audit<br>Object Lock copy", 1120, 290)
    evb = p.icon("eventbridge", "app", "EventBridge<br>action events", 1120, 435, where="right")
    kms = p.icon("key_management_service", "sec", "KMS key<br>encrypts every store", 1300, 294, size=48)

    p.zone("ingest", "Ingest agreements", 30, 570, 360, 340)
    inbox = p.icon("s3", "store", "S3 inbox<br>agreement PDFs", 60, 690, where="top")
    sfn = p.icon("step_functions", "app", "Step Functions<br>waits for a steward", 190, 690, where="top")
    tex = p.icon("textract", "ml", "Textract", 310, 690, where="top")
    p.group("vpc", "VPC: isolated subnets, no NAT, no internet route", 410, 570, 660, 340)
    qry = p.icon("lambda", "compute", "Query Lambda<br>read-only, graph allowlist", 460, 700)
    nep = p.icon("neptune", "db", "Neptune Serverless<br>RDF, IAM auth, 1-4 NCU", 712, 700)
    load = p.icon("lambda", "compute", "Loader Lambda<br>writes, no API route", 950, 640)
    apply = p.icon("lambda", "compute", "Apply Lambda<br>writes approved grants", 950, 790)
    p.zone("bench", "Benchmark (eval stack)", 1090, 570, 300, 340)
    corpus = p.icon("s3", "store", "S3 corpus", 1110, 620, where="right", size=48)
    kb = p.icon("bedrock", "ml", "Knowledge Base<br>Titan embeddings", 1110, 715, where="right", size=48)
    vec = p.icon("s3", "store", "S3 Vectors index", 1110, 820, where="right", size=48)
    p.icon("bedrock", "ml", "Claude Haiku 4.5<br>benchmark answerers", 1300, 700, size=48)
    p.zone("cost", "Cost guard", 30, 940, 360, 110)
    p.icon("budgets", "mgmt", "AWS Budgets: $10 a month, emails at 50, 80, 100%", 50, 975, where="right", size=48)

    p.edge(person, cf, "HTTPS", color=INK, width=2.25)
    p.edge(cf, site, "app files", exit="0.5,0", entry="0.5,1")
    p.edge(cf, gw, "/api, /decide", color=INK, width=2.25)
    p.edge(gw, cog, "verify token", dashed=True, exit="0.5,0", entry="0.5,1")
    p.edge(gw, eng, "", color=INK, width=2.25)
    p.edge(eng, cedar, "may this role act?", dashed=True, exit="0.5,0", entry="0.5,1")
    p.edge(avp, cedar, "same policies", dashed=True, exit="1,0.5", entry="0,0.5")
    p.edge(eng, ddb, "", color=INK, width=2.25, exit="1,0.3", entry="0,0.5")
    p.edge(eng, aud, "", color=INK, width=2.25, exit="1,0.5", entry="0,0.5")
    p.edge(eng, evb, "", exit="1,0.7", entry="0,0.5")
    p.edge(kms, aud, "encrypts", dashed=True, exit="0,0.5", entry="1,0.5")
    p.edge(eng, qry, "graph reads", color=INK, width=2.25, exit="1,0.9", entry="0.5,0",
           points=[(1050, 380), (1050, 612), (488, 612)])  # fmt: skip
    p.edge(qry, nep, "SPARQL, SigV4", color=INK, width=2.25)
    p.edge(load, nep, "loads graphs", exit="0,0.5", entry="1,0.25")
    p.edge(apply, nep, "INSERT DATA", exit="0,0.5", entry="1,0.75")
    p.edge(inbox, sfn, "")
    p.edge(sfn, tex, "")
    p.edge(sfn, apply, "after a steward approves", exit="0.5,1", entry="0,0.5",
           points=[(218, 880), (900, 880), (900, 818)])  # fmt: skip
    p.edge(corpus, kb, "", exit="0.5,1", entry="0.5,0")
    p.edge(kb, vec, "", exit="0.5,1", entry="0.5,0")

    for n, (x, y) in enumerate([(180, 322), (430, 322), (530, 280), (1012, 240), (970, 316), (425, 690),
                                (1070, 150)], 1):  # fmt: skip
        p.badge(n, x, y)
    p.note(
        "<b>How one question is answered</b><br><br>"
        "<b>1</b>&nbsp; The browser loads the app and calls the API on the same CloudFront address.<br><br>"
        "<b>2</b>&nbsp; API Gateway rejects a request with no valid Cognito token before any code runs.<br><br>"
        "<b>3</b>&nbsp; The token carries exactly one role group.<br><br>"
        "<b>4</b>&nbsp; The engine asks Cedar whether that role may ask, read, approve, or review.<br><br>"
        "<b>5</b>&nbsp; The fixed-pattern parser reads the question. (A model reader exists for messy wording; it is "
        "off in this deployment.)<br><br>"
        "<b>6</b>&nbsp; Seven rules read the graph through fixed SPARQL templates. The query Lambda puts only the graphs "
        "this role may read in the FROM clauses.<br><br>"
        "<b>7</b>&nbsp; The decision is stored with its cutoff, release, facts, and a signature, and an audit copy is "
        "locked in S3.",
        1420, 120, 310, 640,
    )  # fmt: skip
    p.legend(1420, 790, [("Request and data path", INK, False), ("Other data flow", MUTED, False),
                         ("Policy, token, or key", MUTED, True)])  # fmt: skip
    p.text("Only Neptune bills while idle. scripts/teardown.py removes everything but the budget.", 1420, 920, 310, 40)
    return p


# ---- Page 2: request path (sequence) -----------------------------------------------------------------------------


def request_path() -> Page:
    p = Page("2. Request path", 1640, 1200)
    p.title("A clearance question, step by step",
            "One request from a signed-in licensing manager to a stored decision. Time runs down the page. "
            "Every call that crosses a service boundary is signed or carries the user's token.")  # fmt: skip
    lanes = [
        ("user", "sec", "Licensing manager"),
        ("cloudfront", "net", "CloudFront"),
        ("api_gateway", "net", "API Gateway"),
        ("cognito", "sec", "Cognito"),
        ("lambda", "compute", "Engine Lambda"),
        ("verified_permissions", "sec", "Cedar policies"),
        ("neptune", "db", "Graph (Neptune or snapshot)"),
        ("dynamodb", "db", "DynamoDB"),
        ("s3", "store", "S3 audit"),
    ]
    x0, gap, top, bottom = 80, 178, 130, 1010
    xs = []
    for i, (icon, cat, label) in enumerate(lanes):
        x = x0 + i * gap
        xs.append(x + 28)
        p.icon(icon, cat, f"<b>{label}</b>", x, top, size=56)
        p.line(x + 28, top + 92, x + 28, bottom, dashed=True, arrow=False, color="#C6CBD0", width=1.25)
    msgs = [
        (0, 3, "1. sign in: user name and password", False),
        (3, 0, "2. ID token with one role group", True),
        (0, 1, "3. POST /api/decide, Authorization: token", False),
        (1, 2, "4. forward on the same origin", False),
        (2, 3, "5. verify the token's signature", False),
        (2, 4, "6. invoke with verified claims", False),
        (4, 5, "7. may this role AskClearance?", False),
        (5, 4, "8. allow", True),
        (4, 4, "9. parse: patent, license type, field, territory, dates", False),
        (4, 6, "10. fixed SPARQL templates, FROM the allowed graphs only", False),
        (6, 4, "11. facts with recording times and source clauses", True),
        (4, 4, "12. seven rules, then the versioned combiner", False),
        (4, 7, "13. store the decision row", False),
        (4, 8, "14. lock a signed copy (Object Lock)", False),
        (4, 0, "15. verdict, the rule that decided, the clauses behind it", True),
    ]
    y = top + 120
    for a, b, label, reply in msgs:
        if a == b:
            p.box(label, xs[a] + 8, y - 12, 260, 26, fill="#FFF4E8", stroke="#ED7100", size=11)
        else:
            p.line(xs[a], y, xs[b], y, label, dashed=reply, color=INK if not reply else MUTED, width=1.6, above=True)
        y += 52
    p.note("<b>What this path guarantees</b><br>• No code runs for a request without a valid token.<br>"
           "• The role comes from the token, never from the request body.<br>"
           "• A rule can only read graphs the role may read; the candidate graph is never read by a rule.<br>"
           "• The same request at the same cutoff gives the same signature.", 80, 1040, 760, 110)  # fmt: skip
    return p


# ---- Page 3: ingestion workflow ----------------------------------------------------------------------------------


def ingestion() -> Page:
    p = Page("3. Ingestion workflow", 1700, 900)
    p.title("Ingesting a license agreement",
            "Step Functions state machine gonogo-ingest. A PDF becomes a proposed grant, waits for a person, and only "
            "then reaches the graph. The text is evidence: nothing in it is ever followed as an instruction.")  # fmt: skip
    inbox = p.icon("s3", "store", "S3 inbox<br>KMS encrypted", 40, 240)
    start = p.icon("lambda", "compute", "Start Lambda<br>one run per PDF", 170, 240)
    p.zone("ingest", "State machine: gonogo-ingest (Step Functions)", 300, 130, 1370, 450)
    s1 = p.box("<b>ReadWithTextract</b><br>OCR Lambda", 330, 240, 150, 60, fill="#E8F7F4", stroke="#01A88D")
    tex = p.icon("textract", "ml", "Textract", 378, 380)
    s2 = p.box("<b>ExtractGrant</b><br>fixed patterns, no model", 520, 240, 170, 60, fill="#FFF4E8", stroke="#ED7100")
    s3 = p.box("<b>CheckShapes</b><br>propose on a copy, SHACL", 730, 240, 170, 60, fill="#FFF4E8", stroke="#ED7100")
    ch = p.diamond("Conforms?", 935, 235)
    fail = p.box("<b>Invalid</b><br>a person reads the PDF", 925, 480, 130, 56, fill="#FBE3E1", stroke="#CF3A34")
    s4 = p.box("<b>AwaitApproval</b><br>waitForTaskToken, up to 7 days", 1090, 240, 190, 60, fill="#ECE6FB",
               stroke="#6D44CC")  # fmt: skip
    pend = p.icon("dynamodb", "db", "Pending table<br>token + proposal", 1062, 390, where="bottom",
                  size=48)  # fmt: skip
    s5 = p.box("<b>WriteToGraph</b><br>Apply Lambda, in the VPC", 1330, 160, 170, 56, fill="#F2F8EA", stroke="#7AA116")
    s6 = p.box("<b>RerunRequests</b><br>verdicts before and after", 1330, 320, 170, 56, fill="#F2F8EA",
               stroke="#7AA116")  # fmt: skip
    nep = p.icon("neptune", "db", "Neptune", 1580, 240)
    rej = p.box("<b>NotApproved</b>", 1330, 470, 170, 40, fill="#FBE3E1", stroke="#CF3A34")
    for a, b in ((inbox, start), (start, s1), (s1, s2), (s2, s3), (s3, ch)):
        p.edge(a, b, "", color=INK, width=2)
    p.edge(s1, tex, "read", exit="0.5,1", entry="0.5,0")
    p.edge(ch, s4, "yes", color=INK, width=2)
    p.edge(ch, fail, "no", exit="0.5,1", entry="0.5,0")
    p.edge(s4, pend, "park", dashed=True, exit="0.2,1", entry="0.5,0")
    p.edge(s4, s5, "approved", color=INK, width=2, exit="1,0.3", entry="0,0.5")
    p.edge(s5, s6, "", color=INK, width=2)
    p.edge(s4, rej, "rejected", exit="0.85,1", entry="0,0.5", points=[(1251, 490)])
    p.edge(s5, nep, "INSERT DATA", exit="1,0.5", entry="0,0.3")
    p.edge(s6, nep, "two cutoffs", exit="1,0.5", entry="0,0.8")

    steward = p.icon("user", "sec", "Steward", 1000, 640)
    gw = p.icon("api_gateway", "net", "POST /ingest/decide<br>Cognito token", 1180, 640)
    counsel = p.icon("user", "sec", "Counsel", 1360, 640)
    p.edge(steward, gw, "approve or reject")
    p.edge(counsel, gw, "second review", exit="0,0.5", entry="1,0.5")
    p.edge(gw, s4, "SendTaskSuccess", dashed=True, exit="0.5,0", entry="0.6,1")
    p.note("<b>Cedar decides who may approve.</b> One steward is enough unless the approval conflicts with an approved "
           "fact or would raise a verdict to GO. Then the decision answers 202, the run keeps waiting, and counsel's "
           "second review releases it. Nobody, including the pipeline, approves what they proposed.",
           1450, 610, 230, 200)  # fmt: skip
    p.note("<b>What extraction refuses</b><br>• a field of use that is not a concept in the field scheme<br>"
           "• a licensee that is not one known licensee<br>• an agreement already on record<br><br>"
           "<b>What it never copies</b><br>• the royalty article (royalty terms live only in the royalty graph)<br>"
           "• an unrecognized article, which is kept as text and shown to the steward",
           40, 620, 420, 180)  # fmt: skip
    p.note("<b>On the synthetic agreements</b><br>101 of 120 read exactly as written, 19 refused for a person, "
           "none read wrong. A planted instruction to mark every request GO changes no verdict.",
           490, 620, 400, 90)  # fmt: skip
    return p


# ---- Page 4: security and network --------------------------------------------------------------------------------


def security() -> Page:
    p = Page("4. Security and network", 1700, 1060)
    p.title("Security and network boundaries",
            "What can reach what. The graph sits in a VPC with no route to the internet; only two functions may write "
            "to it, and neither has an API route an outside caller can use to send it arbitrary data.")  # fmt: skip
    p.group("cloud", "AWS account (organization member)", 30, 120, 1300, 900)
    p.group("region", "us-east-2 (Ohio): the only region the code allows", 60, 160, 1240, 840)
    p.zone("identity", "Identity", 90, 210, 300, 330)
    cog = p.icon("cognito", "sec", "Cognito user pool<br>admin-created users,<br>one group per user", 130, 260)
    gw = p.icon("api_gateway", "net", "API Gateway<br>Cognito authorizer", 270, 260)
    avp = p.icon("verified_permissions", "sec", "Verified Permissions<br>strict schema", 200, 420)
    p.zone("decide", "Outside the VPC: they call AWS APIs, so they need no NAT", 420, 210, 520, 330)
    eng = p.icon("lambda", "compute", "Engine Lambda", 460, 262, where="top")
    ocr = p.icon("lambda", "compute", "Ingest Lambdas", 600, 262, where="top")
    tex = p.icon("textract", "ml", "Textract", 740, 262, where="top")
    p.icon("bedrock", "ml", "Bedrock", 860, 262, where="top")
    p.icon("dynamodb", "db", "DynamoDB<br>KMS encrypted", 600, 420)
    p.icon("s3", "store", "S3 audit, inbox<br>KMS, Object Lock", 740, 420)
    p.icon("key_management_service", "sec", "KMS key<br>encrypts tables,<br>buckets, Neptune", 860, 420)
    p.group("vpc", "VPC: two isolated subnets, no NAT, no internet gateway, no interface endpoints", 90, 580, 1180, 400)
    p.group("subnet", "Security group: port 8182 from members of this group only", 130, 640, 820, 310)
    q = p.icon("lambda", "compute", "Query Lambda<br>ReadDataViaQuery", 170, 720, where="right", size=48)
    lo = p.icon("lambda", "compute", "Loader Lambda<br>read, write, delete", 370, 720, where="right", size=48)
    ap = p.icon("lambda", "compute", "Apply Lambda<br>read, write", 570, 720, where="right", size=48)
    re = p.icon("lambda", "compute", "Rerun Lambda<br>read only", 760, 720, where="right", size=48)
    nep = p.icon("neptune", "db", "Neptune Serverless<br>IAM auth, KMS at rest", 460, 860, where="right")
    s3e = p.icon("endpoints", "net", "S3 gateway endpoint<br>(free)", 1020, 720)
    g = p.icon("s3", "store", "S3 graph files", 1150, 720)
    p.edge(gw, cog, "", dashed=True)
    p.edge(gw, eng, "verified claims")
    p.edge(eng, avp, "same Cedar text", dashed=True, exit="0,0.9", entry="1,0.5", points=[(440, 312), (440, 448)])
    p.edge(ocr, tex, "")
    p.edge(eng, q, "invoke", exit="0.5,1", entry="0,0.5", points=[(488, 560), (76, 560), (76, 744)])
    for fn in (q, lo, ap, re):
        p.edge(fn, nep, "", exit="0.5,1", entry="0.5,0", color="#7AA116")
    p.edge(lo, s3e, "graph files", exit="0.5,0", entry="0.5,0", dashed=True, points=[(394, 690), (1048, 690)])
    p.edge(s3e, g, "")
    p.note("<b>Who may touch Neptune</b><br><br>"
           "<table border='0' cellpadding='3'><tr><td><b>Function</b></td><td><b>Read</b></td><td><b>Write</b></td>"
           "<td><b>API route</b></td></tr>"
           "<tr><td>Query</td><td>yes</td><td>no</td><td>/query, /decide</td></tr>"
           "<tr><td>Loader</td><td>yes</td><td>yes</td><td>none</td></tr>"
           "<tr><td>Apply</td><td>yes</td><td>yes</td><td>none (state machine)</td></tr>"
           "<tr><td>Rerun</td><td>yes</td><td>no</td><td>none (state machine)</td></tr>"
           "<tr><td>Engine</td><td colspan='3'>no network path; reads a bundled snapshot</td></tr></table>",
           1360, 120, 320, 230)  # fmt: skip
    p.note("<b>Checked on every build</b> (tests/infra)<br>• no NAT gateway, internet gateway, or interface endpoint<br>"
           "• exactly two IAM policies grant WriteDataViaQuery<br>• every API method needs a Cognito token<br>"
           "• the inbox and audit buckets block public access and use KMS<br>• nothing outside us-east-2",
           1360, 380, 320, 160)  # fmt: skip
    p.note("<b>Checked against the live stack</b> (infra/evidence.py)<br>Verified Permissions gave the same answer as "
           "in-process Cedar on 126 of 126 questions. A request with no token got 401, and a role that may not read a "
           "graph got 403 before any query ran.", 1360, 570, 320, 130)  # fmt: skip
    p.legend(1360, 730, [("Call or data path", MUTED, False), ("Token, policy, or key", MUTED, True),
                         ("Neptune access (IAM)", "#7AA116", False)])  # fmt: skip
    return p


# ---- Page 5: data and access -------------------------------------------------------------------------------------


def data_access() -> Page:
    from authz.cedar import ROLES, Principal, readable_graphs

    p = Page("5. Data and access", 1500, 1000)
    p.title("Four named graphs, six roles",
            "The graph is split into named graphs, and Cedar decides which a role may query. The query service writes "
            "only the allowed graphs into the FROM clauses, so a forbidden graph is never even searched. The grid "
            "below is read from the Cedar policies when the diagram is built.")  # fmt: skip
    graphs = [
        ("release", "Release graph", "ontology, vocabularies, shapes", "#E6F2F8", "#147EBA"),
        ("approved", "Approved graph", "facts a person or policy approved", "#F2F8EA", "#7AA116"),
        ("candidate", "Candidate graph", "proposals; no rule reads it", "#FFF4E8", "#ED7100"),
        ("royalty", "Royalty graph", "confidential royalty terms", "#FBE3E1", "#CF3A34"),
    ]
    col0, colw, top, rowh = 380, 210, 280, 84
    for c, (_, name, what, fill, stroke) in enumerate(graphs):
        p.store(f"{name}<br><span style='font-weight:normal;font-size:11px'>{what}</span>",
                col0 + c * colw + 10, 140, colw - 20, 110, fill, stroke)  # fmt: skip
    p.box("<b>Other access</b><br><span style='font-size:11px'>Cedar actions beyond graph reads</span>",
          col0 + 4 * colw + 10, 160, 250, 70, fill="#F2F3F3", stroke=MUTED)  # fmt: skip
    labels = {
        "licensing_manager": ("Licensing manager", "asks questions, views and reruns decisions"),
        "steward": ("Steward", "proposes and approves facts, never their own"),
        "counsel": ("Counsel", "second review of risky approvals, approves impact reports, reads the royalty table"),
        "ontology_owner": ("Ontology owner", "proposes releases, publishes them once counsel approves"),
        "finance_analyst": ("Finance analyst", "reads royalty terms in the Snowflake table, never the graph"),
        "auditor": ("Auditor", "views and reruns decisions, reads release history, no graph"),
    }
    for r, role in enumerate(ROLES):
        y = top + r * rowh
        p.box("", 30, y, col0 + 4 * colw + 270 - 30, rowh - 8, fill="#FFFFFF" if r % 2 else "#FAFAFA",
              stroke="#E9EBED")  # fmt: skip
        p.icon("user", "sec", "", 44, y + 14, size=48)
        p.text(f"<b>{labels[role][0]}</b>", 104, y + 22, 260, 24, size=13, color=INK)
        allowed = {g.rsplit("/", 1)[-1] for g in readable_graphs(Principal("x", role))}
        for c, (key, *_rest) in enumerate(graphs):
            x = col0 + c * colw + 30
            if key in allowed:
                fill = "#FBE3E1" if key == "royalty" else "#DFF4E8"
                color = "#CF3A34" if key == "royalty" else "#178A58"
                p.box("✓ may query", x, y + 18, colw - 60, 38, fill=fill, stroke=color, font=color, bold=True)
            else:
                p.box("no", x, y + 18, colw - 60, 38, fill="#F2F3F3", stroke="#E9EBED", font="#879196")
        p.text(labels[role][1], col0 + 4 * colw + 14, y + 14, 250, 50, size=12, color=INK)
    p.note("<b>Rules read release and approved only.</b> A proposal changes no verdict until a person approves it, "
           "because the candidate graph is outside every rule's FROM clause.<br><br>"
           "<b>Royalty terms never leave their graph.</b> Only counsel may query them. The benchmark corpus, the "
           "public demo snapshot, and the ingestion workflow all exclude them, and a test checks each.",
           30, 800, 760, 120)  # fmt: skip
    p.icon("neptune", "db", "Neptune holds all four graphs. Each query names its graphs with FROM; the query "
           "service refuses GRAPH, SERVICE, and updates.", 820, 820, where="right", size=48)  # fmt: skip
    return p


# ---- Page 6: benchmark -------------------------------------------------------------------------------------------


def benchmark() -> Page:
    p = Page("6. Benchmark", 1640, 1000)
    p.title("How the benchmark answers 200 questions four ways",
            "The same questions and the same facts go to every answerer; only the method differs. The right answers "
            "were fixed by hand when each case was planted, never by the rule engine. Model: Claude Haiku 4.5 on "
            "Bedrock, temperature 0.")  # fmt: skip
    gold = p.box("<b>Golden set</b><br>45 planted cases × 4 wordings<br>+ 20 unanswerable", 40, 450, 200, 90,
                 fill="#F2F3F3", stroke=MUTED)  # fmt: skip
    rows = [("A", "Vector RAG", "bench", 130), ("B", "Graph agent", "ingest", 330),
            ("C", "Rules only", "decide", 530), ("C+", "Rules + model reader", "graph", 730)]  # fmt: skip
    zones = {k: p.zone(z, f"{k}. {name}", 300, y, 900, 180) for k, name, z, y in rows}
    a1 = p.icon("bedrock", "ml", "Knowledge Base<br>embeds the question (Titan)", 380, 175)
    vec = p.icon("s3", "store", "S3 Vectors<br>1,925 documents", 640, 175)
    a2 = p.icon("bedrock", "ml", "Haiku reads 12 passages,<br>gives a verdict", 900, 175)
    p.edge(a1, vec, "search", dashed=True)
    p.edge(a1, a2, "top 12 passages", color=INK, exit="0.5,0", entry="0.5,0", points=[(408, 160), (928, 160)])
    b1 = p.icon("bedrock", "ml", "Strands agent on Haiku<br>4-5 calls a question", 380, 375)
    b2 = p.box("Graph tools<br>patent, records, overlapping<br>grants, notices", 560, 368, 200, 70, fill="#FFFFFF",
               stroke="#E7157B")  # fmt: skip
    b3 = p.box("Rules' own SPARQL<br>templates, as-of filter", 820, 368, 170, 70, fill="#FFFFFF", stroke="#E7157B")
    b4 = p.box("Passages filtered<br>to the patent (KB)", 1020, 368, 150, 70, fill="#FFFFFF", stroke="#E7157B")
    p.edge(b1, b2, "", color=INK)
    p.edge(b2, b3, "", color=INK)
    p.edge(b2, b4, "", color=INK, exit="0.5,0", entry="0.5,0", points=[(660, 352), (1095, 352)])
    c1 = p.box("Fixed-pattern parser<br>(no model)", 380, 580, 170, 70, fill="#FFFFFF", stroke="#ED7100")
    c2 = p.box("Seven rules +<br>versioned combiner", 620, 580, 170, 70, fill="#FFFFFF", stroke="#ED7100")
    p.edge(c1, c2, "", color=INK)
    p.text("Refuses what it cannot parse: NEEDS INFO, never a guess.", 830, 600, 330, 40, color=INK)
    d1 = p.icon("bedrock", "ml", "Haiku fills a form only<br>when the parser misses a part", 380, 775)
    d2 = p.box("Every value must name<br>a concept the graph holds", 620, 780, 190, 70, fill="#FFFFFF",
               stroke="#7AA116")  # fmt: skip
    d3 = p.box("Seven rules +<br>versioned combiner", 880, 780, 170, 70, fill="#FFFFFF", stroke="#7AA116")
    p.edge(d1, d2, "", color=INK)
    p.edge(d2, d3, "", color=INK)
    for key, *_ in rows:
        p.edge(gold, zones[key], "", exit="1,0.5", entry="0,0.5", color=MUTED, width=1.25, curved=True)
    score = p.box("<b>Scorer</b><br>verdict accuracy, false GO,<br>citation precision, latency, cost", 1260, 450,
                  220, 90, fill="#F2F3F3", stroke=MUTED)  # fmt: skip
    for key, *_ in rows:
        p.edge(zones[key], score, "", exit="1,0.5", entry="0,0.5", color=MUTED, width=1.25, curved=True)
    out = p.box("eval/results.md and the Benchmark page<br><b>CI fails on any false GO by C or C+</b>", 1260, 600,
                220, 80, fill="#FBE3E1", stroke="#CF3A34")  # fmt: skip
    p.edge(score, out, "")
    return p


# ---- Page 7: stacks and cost -------------------------------------------------------------------------------------


def stacks() -> Page:
    p = Page("7. Stacks and cost", 1600, 820)
    p.title("The five CDK stacks, and what each costs while idle",
            "Everything is deployed for a session, checked, and torn down by scripts/teardown.py. The public demo on "
            "Vercel keeps working with no AWS account. Neptune is the one resource that bills by the hour.")  # fmt: skip
    cols = [
        ("gonogo-core", "identity", "Identity, keys, storage, policy",
         [("cognito", "sec", "Cognito"), ("verified_permissions", "sec", "Verified Permissions"),
          ("key_management_service", "sec", "KMS key"), ("dynamodb", "db", "DynamoDB"), ("s3", "store", "S3 audit")],
         "about $1 a month (the KMS key)"),
        ("gonogo-api", "graph", "Network, graph, functions, API",
         [("neptune", "db", "Neptune (flag)"), ("lambda", "compute", "Lambdas"), ("api_gateway", "net", "API Gateway"),
          ("step_functions", "app", "Ingestion (flag)"), ("textract", "ml", "Textract")],
         "Neptune: about $0.16 per capacity-unit hour"),
        ("gonogo-ui", "edge", "Where the UI lives",
         [("cloudfront", "net", "CloudFront"), ("s3", "store", "S3 site")], "free while idle"),
        ("gonogo-eval", "bench", "Benchmark search",
         [("bedrock", "ml", "Knowledge Base"), ("s3", "store", "S3 Vectors"), ("s3", "store", "S3 corpus")],
         "cents of storage"),
        ("gonogo-budget", "cost", "Cost alarm", [("budgets", "mgmt", "$10 budget")], "free; survives teardown"),
    ]  # fmt: skip
    for i, (name, zone, what, items, cost) in enumerate(cols):
        x = 30 + i * 310
        p.zone(zone, f"{name}<br><span style='font-weight:normal'>{what}</span>", x, 130, 290, 560)
        for j, (icon, cat, label) in enumerate(items):
            p.icon(icon, cat, label, x + 30, 210 + j * 90, where="right", size=48)
        p.box(f"<b>Idle cost:</b> {cost}", x + 15, 630, 260, 44, fill="#FFFFFF", stroke=ZONE[zone][1], size=12)
    p.text("Deploy: <font face='monospace'>cdk deploy --all -c deployNeptune=true -c deployIngest=true</font>"
           "&nbsp;&nbsp;·&nbsp;&nbsp;Tear down: <font face='monospace'>uv run python -m scripts.teardown</font>"
           "&nbsp;&nbsp;·&nbsp;&nbsp;Resource list: docs/aws-resources.md", 30, 720, 1540, 30, size=13, color=INK)  # fmt: skip
    return p


PAGES = [overview, request_path, ingestion, security, data_access, benchmark, stacks]
SLUGS = ["overview", "request-path", "ingestion", "security", "data-access", "benchmark", "stacks"]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    pages = [build() for build in PAGES]
    body = "".join(pg.xml(f"page-{i + 1}") for i, pg in enumerate(pages))
    src = OUT / "gonogo-aws.drawio"
    src.write_text(f'<mxfile host="app.diagrams.net">{body}</mxfile>')
    for f in OUT.glob("gonogo-aws*.png"):
        f.unlink()
    for i, slug in enumerate(SLUGS, 1):
        png = OUT / f"gonogo-aws-{i}-{slug}.png"
        subprocess.run(
            [
                "drawio",
                "-x",
                "-f",
                "png",
                "--no-sandbox",
                "-s",
                "2",
                "-b",
                "16",
                "-p",
                str(i),
                "-o",
                str(png),
                str(src),
            ],
            check=True,
            capture_output=True,
        )
        print("wrote", png.relative_to(ROOT))
    (OUT / "gonogo-aws.svg").unlink(missing_ok=True)


if __name__ == "__main__":
    main()
