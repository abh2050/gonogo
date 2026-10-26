"""Write docs/architecture/gonogo-aws.drawio with draw.io's AWS icon set, then export PNG and SVG with the draw.io CLI.

    uv run python scripts/drawio_aws.py

The services are the ones the CDK stacks in infra/stacks.py deploy. Edit the file in draw.io or change this script.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from xml.sax.saxutils import quoteattr

OUT = Path(__file__).resolve().parent.parent / "docs" / "architecture"
COLORS = {
    "net": "#8C4FFF",
    "compute": "#ED7100",
    "store": "#7AA116",
    "sec": "#DD344C",
    "db": "#C925D1",
    "app": "#E7157B",
}
# id: (icon, color class, label, x, y)
NODES = {
    "user": ("user", "sec", "Person<br>one of six roles", 40, 300),
    "cf": ("cloudfront", "net", "CloudFront<br>one address", 250, 300),
    "site": ("s3", "store", "S3: the app<br>private, OAC", 250, 110),
    "gw": ("api_gateway", "net", "API Gateway<br>token check, throttling", 480, 300),
    "cog": ("cognito", "sec", "Cognito<br>six role groups", 480, 110),
    "eng": ("lambda", "compute", "Engine Lambda<br>rules, approvals", 730, 300),
    "avp": ("verified_permissions", "sec", "Verified Permissions<br>21 Cedar policies", 730, 110),
    "ddb": ("dynamodb", "db", "DynamoDB<br>decisions", 990, 120),
    "aud": ("s3", "store", "S3 audit<br>Object Lock", 990, 300),
    "evb": ("eventbridge", "app", "EventBridge<br>action events", 990, 470),
    "kms": ("key_management_service", "sec", "KMS key<br>rotates yearly", 1220, 300),
    "qry": ("lambda", "compute", "Query Lambda<br>read-only, graph allowlist", 730, 680),
    "load": ("lambda", "compute", "Loader Lambda<br>only writer, no route", 1190, 680),
    "nep": ("neptune", "db", "Neptune Serverless<br>1 to 4 NCU, IAM auth", 960, 680),
    "bud": ("budgets", "app", "AWS Budgets<br>$10 alarm", 40, 680),
}
TOP_LABEL = {"site", "cog", "avp"}
# from, to, label, dashed
EDGES = [
    ("user", "cf", "HTTPS", 0),
    ("cf", "site", "static files", 0),
    ("cf", "gw", "/api /decide /query", 0),
    ("gw", "cog", "verify token", 0),
    ("gw", "eng", "", 0),
    ("eng", "avp", "same policy text", 1),
    ("eng", "ddb", "", 0),
    ("eng", "aud", "", 0),
    ("eng", "evb", "", 0),
    ("eng", "qry", "invoke", 0),
    ("qry", "nep", "SPARQL, SigV4", 0),
    ("load", "nep", "writes graphs", 0),
    ("aud", "kms", "encrypts", 1),
]


def cell(i: int, key: str) -> str:
    icon, cls, label, x, y = NODES[key]
    top = key in TOP_LABEL
    side = "labelPosition=right;align=left;spacingLeft=6;" if key == "eng" else ""
    style = (
        f"sketch=0;outlineConnect=0;fontColor=#232F3E;gradientColor=none;fillColor={COLORS[cls]};strokeColor=none;"
        f"dashed=0;verticalLabelPosition={'top' if top else 'bottom'};"
        f"verticalAlign={'bottom' if top else 'top'};align=center;html=1;fontSize=12;fontStyle=0;"
        f"aspect=fixed;{side}shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.{icon};"
    )
    return (
        f'<mxCell id="{key}" value={quoteattr(label)} style={quoteattr(style)} vertex="1" parent="1">'
        f'<mxGeometry x="{x}" y="{y}" width="64" height="64" as="geometry"/></mxCell>'
    )


ANCHORS = {
    ("cf", "site"): "exitX=0.5;exitY=0;entryX=0.5;entryY=1;",
    ("gw", "cog"): "exitX=0.5;exitY=0;entryX=0.5;entryY=1;",
    ("eng", "avp"): "exitX=0.5;exitY=0;entryX=0.5;entryY=1;",
    ("eng", "ddb"): "exitX=1;exitY=0.5;entryX=0;entryY=0.5;",
    ("eng", "aud"): "exitX=1;exitY=0.5;entryX=0;entryY=0.5;",
    ("eng", "evb"): "exitX=1;exitY=0.5;entryX=0;entryY=0.5;",
    ("eng", "qry"): "exitX=0.5;exitY=1;entryX=0.5;entryY=0;",
    ("qry", "nep"): "exitX=1;exitY=0.5;entryX=0;entryY=0.5;",
    ("load", "nep"): "exitX=0;exitY=0.5;entryX=1;entryY=0.5;",
    ("aud", "kms"): "exitX=1;exitY=0.5;entryX=0;entryY=0.5;",
}


def edge(i: int, a: str, b: str, label: str, dashed: int) -> str:
    style = ANCHORS.get((a, b), "") + (
        "edgeStyle=orthogonalEdgeStyle;rounded=1;html=1;endArrow=block;endFill=1;strokeColor=#545B64;strokeWidth=2;"
        f"fontSize=11;fontColor=#545B64;labelBackgroundColor=#FFFFFF;{'dashed=1;' if dashed else ''}"
    )
    return (
        f'<mxCell id="e{i}" value={quoteattr(label)} style={quoteattr(style)} edge="1" parent="1" '
        f'source="{a}" target="{b}">'
        '<mxGeometry relative="1" as="geometry"/></mxCell>'
    )


def group(gid: str, label: str, x: int, y: int, w: int, h: int, style: str) -> str:
    return (
        f'<mxCell id="{gid}" value={quoteattr(label)} style={quoteattr(style)} vertex="1" parent="1">'
        f'<mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry"/></mxCell>'
    )


def build() -> str:
    cloud = (
        "points=[[0,0],[0.25,0],[0.5,0],[0.75,0],[1,0],[1,0.25],[1,0.5],[1,0.75],[1,1],[0.75,1],[0.5,1],[0.25,1],"
        "[0,1],[0,0.75],[0,0.5],[0,0.25]];outlineConnect=0;gradientColor=none;html=1;whiteSpace=wrap;fontSize=13;"
        "fontStyle=1;container=0;collapsible=0;recursiveResize=0;shape=mxgraph.aws4.group;grIcon=mxgraph.aws4.group_aws_cloud_alt;"
        "strokeColor=#232F3E;fillColor=none;verticalAlign=top;align=left;spacingLeft=30;fontColor=#232F3E;dashed=0;"
    )
    vpc = (
        "points=[[0,0],[0.25,0],[0.5,0],[0.75,0],[1,0],[1,0.25],[1,0.5],[1,0.75],[1,1],[0.75,1],[0.5,1],[0.25,1],"
        "[0,1],[0,0.75],[0,0.5],[0,0.25]];outlineConnect=0;gradientColor=none;html=1;whiteSpace=wrap;fontSize=12;"
        "fontStyle=0;container=0;collapsible=0;recursiveResize=0;shape=mxgraph.aws4.group;grIcon=mxgraph.aws4.group_vpc;"
        "strokeColor=#8C4FFF;fillColor=none;verticalAlign=top;align=right;spacingRight=10;fontColor=#8C4FFF;dashed=0;"
    )
    parts = [
        group("cloud", "AWS Cloud: us-east-2", 20, 20, 1340, 880, cloud),
        group("vpc", "VPC: isolated subnets, no NAT, no internet route", 690, 590, 640, 230, vpc),
    ]
    parts += [cell(i, k) for i, k in enumerate(NODES)]
    parts += [edge(i, *e) for i, e in enumerate(EDGES)]
    body = "".join(parts)
    return (
        '<mxfile host="app.diagrams.net"><diagram name="GoNoGo on AWS" id="gonogo-aws">'
        '<mxGraphModel dx="1400" dy="900" grid="0" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" '
        'fold="1" '
        'page="1" pageScale="1" pageWidth="1400" pageHeight="920" math="0" shadow="0"><root>'
        f'<mxCell id="0"/><mxCell id="1" parent="0"/>{body}</root></mxGraphModel></diagram></mxfile>'
    )


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    src = OUT / "gonogo-aws.drawio"
    src.write_text(build())
    for fmt, extra in (("png", ["-s", "2"]), ("svg", [])):
        subprocess.run(
            [
                "drawio",
                "-x",
                "-f",
                fmt,
                "--no-sandbox",
                *extra,
                "-b",
                "10",
                "-o",
                str(OUT / f"gonogo-aws.{fmt}"),
                str(src),
            ],
            check=True,
            capture_output=True,
        )
        print("wrote", OUT / f"gonogo-aws.{fmt}")
