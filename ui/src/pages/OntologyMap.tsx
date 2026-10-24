import * as d3 from "d3";
import { useEffect, useMemo, useRef, useState } from "react";
import { Failed, Loading } from "../components/Loading";
import { KIND_LABEL, useJson, type Kind, type OntEdge, type OntNode, type Ontology } from "../data";

type EdgeMode = "both" | "subclass" | "property";

interface SimNode extends d3.SimulationNodeDatum {
  id: string;
  data: OntNode;
  r: number;
  degree: number;
}

interface SimLink {
  source: SimNode;
  target: SimNode;
  data: OntEdge;
  curve: number;
}

const KINDS: Kind[] = ["fact", "thing", "party", "document", "vocabulary", "process", "external"];

/** Where each group of classes settles. Links still pull related classes together. */
const ANCHOR: Record<Kind, [number, number]> = {
  fact: [500, 330],
  thing: [150, 350],
  party: [170, 120],
  document: [540, 650],
  vocabulary: [850, 150],
  process: [820, 590],
  external: [150, 560],
};

function colorOf(kind: Kind): string {
  return `var(--k-${kind})`;
}

export default function OntologyMap() {
  const { data, error } = useJson<Ontology>("ontology.json");
  const [selected, setSelected] = useState<string | null>(() => {
    // A link such as #/ontology?select=Grant opens with that class selected.
    return new URLSearchParams(window.location.hash.split("?")[1] ?? "").get("select");
  });
  const [hidden, setHidden] = useState<Set<Kind>>(new Set());
  const [mode, setMode] = useState<EdgeMode>("both");
  const [query, setQuery] = useState("");
  const [box, setBox] = useState("0 0 1200 800");
  const svgRef = useRef<SVGSVGElement>(null);
  const layoutRef = useRef<{ pos: Map<string, [number, number]>; box: [number, number, number, number] } | null>(null);
  const restyle = useRef<(() => void) | null>(null);
  const stateRef = useRef({ selected, hidden, mode, query });
  stateRef.current = { selected, hidden, mode, query };

  const byId = useMemo(() => new Map((data?.nodes ?? []).map((n) => [n.id, n])), [data]);

  useEffect(() => {
    if (!data || !svgRef.current) return;
    const svg = d3.select(svgRef.current);
    svg.selectAll("*").remove();

    const degree = new Map<string, number>();
    data.edges.forEach((e) => {
      degree.set(e.source, (degree.get(e.source) ?? 0) + 1);
      degree.set(e.target, (degree.get(e.target) ?? 0) + 1);
    });
    const nodes: SimNode[] = data.nodes.map((n) => {
      const [ax, ay] = ANCHOR[n.kind];
      const deg = degree.get(n.id) ?? 0;
      return { id: n.id, data: n, degree: deg, r: n.external ? 7 : 8 + 2.4 * Math.sqrt(deg), x: ax + (Math.random() - 0.5) * 80, y: ay + (Math.random() - 0.5) * 80 };
    });
    const index = new Map(nodes.map((n) => [n.id, n]));
    const pairCount = new Map<string, number>();
    const links: SimLink[] = data.edges
      .filter((e) => e.source !== e.target && index.has(e.source) && index.has(e.target))
      .map((e) => {
        const key = [e.source, e.target].sort().join("|");
        const n = pairCount.get(key) ?? 0;
        pairCount.set(key, n + 1);
        const side = e.source < e.target ? 1 : -1;
        return { source: index.get(e.source)!, target: index.get(e.target)!, data: e, curve: e.kind === "subclass" ? 0 : side * (n + 1) };
      });

    const sim = d3
      .forceSimulation<SimNode>(nodes)
      .force(
        "link",
        d3
          .forceLink<SimNode, SimLink>(links)
          .id((d) => d.id)
          .distance((l) => (l.data.kind === "subclass" ? 88 : 190))
          .strength((l) => (l.data.kind === "subclass" ? 0.7 : 0.06)),
      )
      .force("charge", d3.forceManyBody<SimNode>().strength(-900))
      .force("collide", d3.forceCollide<SimNode>().radius((d) => d.r + 34))
      .force("x", d3.forceX<SimNode>((d) => ANCHOR[d.data.kind][0]).strength(0.3))
      .force("y", d3.forceY<SimNode>((d) => ANCHOR[d.data.kind][1]).strength(0.3))
      .stop();
    for (let i = 0; i < 700; i++) sim.tick();

    // Fit the viewBox to the settled layout, with room for labels.
    const pad = 56;
    const x0 = Math.min(...nodes.map((n) => (n.x ?? 0) - n.r)) - pad - 30;
    const x1 = Math.max(...nodes.map((n) => (n.x ?? 0) + n.r)) + pad + 30;
    const y0 = Math.min(...nodes.map((n) => (n.y ?? 0) - n.r)) - pad;
    const y1 = Math.max(...nodes.map((n) => (n.y ?? 0) + n.r)) + pad;
    setBox(`${x0} ${y0} ${x1 - x0} ${y1 - y0}`);
    layoutRef.current = {
      pos: new Map(nodes.map((n) => [n.id, [n.x ?? 0, n.y ?? 0] as [number, number]])),
      box: [x0, y0, x1 - x0, y1 - y0],
    };

    const defs = svg.append("defs");
    defs
      .append("marker")
      .attr("id", "arrow-sub")
      .attr("viewBox", "0 0 10 10")
      .attr("refX", 9)
      .attr("refY", 5)
      .attr("markerWidth", 9)
      .attr("markerHeight", 9)
      .attr("orient", "auto")
      .append("path")
      .attr("d", "M1,1 L9,5 L1,9 z")
      .style("fill", "var(--surface)")
      .style("stroke", "var(--faint)")
      .style("stroke-width", 1.3);
    defs
      .append("marker")
      .attr("id", "arrow-prop")
      .attr("viewBox", "0 0 10 10")
      .attr("refX", 9)
      .attr("refY", 5)
      .attr("markerWidth", 8)
      .attr("markerHeight", 8)
      .attr("orient", "auto")
      .append("path")
      .attr("d", "M1,1 L9,5 L1,9 z")
      .style("fill", "var(--accent)");

    const root = svg.append("g");
    svg.call(
      d3
        .zoom<SVGSVGElement, unknown>()
        .scaleExtent([0.5, 3])
        .on("zoom", (event: d3.D3ZoomEvent<SVGSVGElement, unknown>) => root.attr("transform", event.transform.toString())),
    );
    svg.on("dblclick.zoom", null);
    svg.on("click", () => setSelected(null));

    const linkSel = root
      .append("g")
      .attr("fill", "none")
      .selectAll<SVGPathElement, SimLink>("path")
      .data(links)
      .join("path")
      .attr("marker-end", (d) => (d.data.kind === "subclass" ? "url(#arrow-sub)" : "url(#arrow-prop)"))
      .style("stroke", (d) => (d.data.kind === "subclass" ? "var(--line-strong)" : "var(--accent)"))
      .style("stroke-width", (d) => (d.data.kind === "subclass" ? 1.4 : 1.8))
      .style("stroke-dasharray", (d) => (d.data.kind === "chain" ? "5 4" : null));

    const edgeLabel = root
      .append("g")
      .selectAll<SVGTextElement, SimLink>("text")
      .data(links.filter((l) => l.data.kind !== "subclass"))
      .join("text")
      .attr("text-anchor", "middle")
      .attr("font-size", 11)
      .attr("font-weight", 600)
      .style("fill", "var(--accent-ink)")
      .style("paint-order", "stroke")
      .style("stroke", "var(--surface)")
      .style("stroke-width", 4)
      .style("pointer-events", "none")
      .text((d) => d.data.label);

    const nodeSel = root
      .append("g")
      .selectAll<SVGGElement, SimNode>("g")
      .data(nodes)
      .join("g")
      .attr("tabindex", 0)
      .attr("role", "button")
      .attr("aria-label", (d) => `${d.data.label}. ${KIND_LABEL[d.data.kind]}.`)
      .style("cursor", "pointer")
      .on("click", (event: MouseEvent, d) => {
        event.stopPropagation();
        setSelected(d.id);
      })
      .on("keydown", (event: KeyboardEvent, d) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          setSelected(d.id);
        }
      });
    nodeSel
      .append("circle")
      .attr("r", (d) => d.r)
      .style("fill", (d) => colorOf(d.data.kind))
      .style("fill-opacity", (d) => (d.data.external ? 0.25 : 0.92))
      .style("stroke", (d) => colorOf(d.data.kind))
      .style("stroke-width", 2)
      .style("stroke-dasharray", (d) => (d.data.external ? "3 3" : null));
    const wrap = (label: string): string[] => {
      const lines: string[] = [];
      let line = "";
      for (const word of label.split(" ")) {
        if (line && (line + " " + word).length > 16) {
          lines.push(line);
          line = word;
        } else {
          line = line ? `${line} ${word}` : word;
        }
      }
      if (line) lines.push(line);
      return lines;
    };
    nodeSel
      .append("text")
      .attr("text-anchor", "middle")
      .attr("font-size", 13)
      .attr("font-weight", 560)
      .style("fill", "var(--ink)")
      .style("paint-order", "stroke")
      .style("stroke", "var(--surface)")
      .style("stroke-width", 4)
      .style("pointer-events", "none")
      .each(function (d) {
        const text = d3.select(this);
        wrap(d.data.label).forEach((line, i) => {
          text
            .append("tspan")
            .attr("x", 0)
            .attr("y", d.r + 14 + i * 14)
            .text(line);
        });
      });

    const pathFor = (d: SimLink): string => {
      const s = d.source;
      const t = d.target;
      const dx = (t.x ?? 0) - (s.x ?? 0);
      const dy = (t.y ?? 0) - (s.y ?? 0);
      const dist = Math.hypot(dx, dy) || 1;
      const ux = dx / dist;
      const uy = dy / dist;
      const x1 = (s.x ?? 0) + ux * (s.r + 2);
      const y1 = (s.y ?? 0) + uy * (s.r + 2);
      const x2 = (t.x ?? 0) - ux * (t.r + 5);
      const y2 = (t.y ?? 0) - uy * (t.r + 5);
      if (!d.curve) return `M${x1},${y1}L${x2},${y2}`;
      const mx = (x1 + x2) / 2 - uy * d.curve * 34;
      const my = (y1 + y2) / 2 + ux * d.curve * 34;
      return `M${x1},${y1}Q${mx},${my} ${x2},${y2}`;
    };
    const labelPos = (d: SimLink): [number, number] => {
      const s = d.source;
      const t = d.target;
      const dx = (t.x ?? 0) - (s.x ?? 0);
      const dy = (t.y ?? 0) - (s.y ?? 0);
      const dist = Math.hypot(dx, dy) || 1;
      return [((s.x ?? 0) + (t.x ?? 0)) / 2 - (dy / dist) * d.curve * 17, ((s.y ?? 0) + (t.y ?? 0)) / 2 + (dx / dist) * d.curve * 17 - 3];
    };

    const draw = () => {
      linkSel.attr("d", pathFor);
      edgeLabel.attr("x", (d) => labelPos(d)[0]).attr("y", (d) => labelPos(d)[1]);
      nodeSel.attr("transform", (d) => `translate(${d.x ?? 0},${d.y ?? 0})`);
    };
    draw();

    nodeSel.call(
      d3
        .drag<SVGGElement, SimNode>()
        .on("start", (event: d3.D3DragEvent<SVGGElement, SimNode, SimNode>, d) => {
          if (!event.active) sim.alphaTarget(0.25).restart();
          d.fx = d.x;
          d.fy = d.y;
        })
        .on("drag", (event: d3.D3DragEvent<SVGGElement, SimNode, SimNode>, d) => {
          d.fx = event.x;
          d.fy = event.y;
        })
        .on("end", (event: d3.D3DragEvent<SVGGElement, SimNode, SimNode>, d) => {
          if (!event.active) sim.alphaTarget(0);
          d.fx = null;
          d.fy = null;
        }),
    );
    sim.on("tick", draw);

    restyle.current = () => {
      const { selected: sel, hidden: off, mode: m, query: q } = stateRef.current;
      const needle = q.trim().toLowerCase();
      const neighbors = new Set<string>();
      if (sel) {
        neighbors.add(sel);
        links.forEach((l) => {
          if (l.source.id === sel) neighbors.add(l.target.id);
          if (l.target.id === sel) neighbors.add(l.source.id);
        });
      }
      const visibleNode = (n: SimNode) => !off.has(n.data.kind);
      const matches = (n: SimNode) => needle !== "" && (n.data.label.toLowerCase().includes(needle) || n.id.toLowerCase().includes(needle));
      nodeSel
        .style("display", (n) => (visibleNode(n) ? null : "none"))
        .style("opacity", (n) => {
          if (needle) return matches(n) ? 1 : 0.18;
          if (sel) return neighbors.has(n.id) ? 1 : 0.15;
          return 1;
        });
      nodeSel.select("circle").style("stroke-width", (n) => (n.id === sel ? 4 : 2));
      const linkVisible = (l: SimLink) =>
        visibleNode(l.source) && visibleNode(l.target) && (m === "both" || (m === "subclass") === (l.data.kind === "subclass"));
      linkSel
        .style("display", (l) => (linkVisible(l) ? null : "none"))
        .style("opacity", (l) => {
          if (sel) return l.source.id === sel || l.target.id === sel ? 1 : 0.07;
          return needle ? 0.15 : 0.85;
        });
      edgeLabel
        .style("display", (l) => (linkVisible(l) ? null : "none"))
        .style("opacity", (l) => (sel ? (l.source.id === sel || l.target.id === sel ? 1 : 0) : 0.0));
    };
    restyle.current();

    return () => {
      sim.stop();
    };
  }, [data]);

  useEffect(() => {
    restyle.current?.();
  }, [selected, hidden, mode, query]);

  if (error) return <Failed error={error} />;
  if (!data) return <Loading what="the ontology" />;

  const node: OntNode | undefined = selected ? byId.get(selected) : undefined;
  // Park the panel in the corner farthest from the selected class, so its neighbors stay visible.
  let corner = "bottom-right";
  const layout = layoutRef.current;
  if (node && layout) {
    const [px, py] = layout.pos.get(node.id) ?? [0, 0];
    const fx = (px - layout.box[0]) / layout.box[2];
    const fy = (py - layout.box[1]) / layout.box[3];
    corner = `${fy > 0.5 ? "top" : "bottom"}-${fx > 0.5 ? "left" : "right"}`;
  }
  const outgoing = node ? data.edges.filter((e) => e.source === node.id && e.kind !== "subclass") : [];
  const incoming = node ? data.edges.filter((e) => e.target === node.id && e.kind !== "subclass") : [];
  const parents = node ? data.edges.filter((e) => e.source === node.id && e.kind === "subclass") : [];
  const children = node ? data.edges.filter((e) => e.target === node.id && e.kind === "subclass") : [];

  return (
    <>
      <div className="page-head">
        <div className="eyebrow">The ontology</div>
        <h1>{data.counts.classes} classes, drawn as a graph</h1>
        <p className="lede">
          Each dot is an OWL class, grouped by what it describes. Gray arrows are subclass links, blue arrows are
          object properties, and dashed blue arrows are property chains that a reasoner uses to derive rights
          coverage. Click a class to read its definition, the rules that read it, and the modeling decisions behind it.
        </p>
      </div>

      <div className="viz" style={{ position: "relative" }}>
        <div>
          <div className="viz-toolbar">
            <div className="legend" role="group" aria-label="Show or hide groups">
              {KINDS.map((k) => (
                <button
                  key={k}
                  className="legend-item"
                  aria-pressed={!hidden.has(k)}
                  onClick={() => {
                    const next = new Set(hidden);
                    if (next.has(k)) next.delete(k);
                    else next.add(k);
                    setHidden(next);
                  }}
                >
                  <span className="swatch" style={{ background: colorOf(k), opacity: k === "external" ? 0.5 : 1 }} />
                  {KIND_LABEL[k]}
                </button>
              ))}
            </div>
            <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center" }}>
              <div className="segmented" role="group" aria-label="Arrows to show">
                {(["both", "subclass", "property"] as const).map((m) => (
                  <button key={m} aria-pressed={mode === m} onClick={() => setMode(m)}>
                    {m === "both" ? "All arrows" : m === "subclass" ? "Subclass" : "Properties"}
                  </button>
                ))}
              </div>
              <input type="search" placeholder="Find a class" aria-label="Find a class" value={query} onChange={(e) => setQuery(e.target.value)} />
            </div>
          </div>
          <svg ref={svgRef} viewBox={box} role="group" aria-label="Ontology graph" style={{ height: "min(78vh, 860px)" }} />
        </div>

        <aside className={`overlay-panel ${node ? `open ${corner}` : "hint"}`} aria-live="polite">
          {node ? (
            <button className="close-x" onClick={() => setSelected(null)} aria-label="Close details">×</button>
          ) : null}
          {node ? (
            <>
              <div>
                <span className="tag" style={{ background: "transparent", border: `1px solid ${colorOf(node.kind)}`, color: "var(--ink)" }}>
                  {KIND_LABEL[node.kind]}
                </span>
              </div>
              <h3>{node.label}</h3>
              {node.definition ? <p>{node.definition}</p> : <p className="muted">A term that GoNoGo reuses from another vocabulary.</p>}
              {node.comment ? <p className="muted" style={{ fontSize: 14 }}>{node.comment}</p> : null}
              {node.rules.length ? (
                <div>
                  <div className="muted" style={{ fontSize: 12.5, marginBottom: 2 }}>Read by rules</div>
                  {node.rules.map((r) => (
                    <span className="tag rule" key={r}>{r}</span>
                  ))}
                </div>
              ) : null}
              {node.decisions.length ? (
                <div>
                  <div className="muted" style={{ fontSize: 12.5, marginBottom: 2 }}>Modeling decisions</div>
                  {node.decisions.map((d) => (
                    <a className="tag" key={d} href={`https://github.com/abh2050/gonogo/blob/main/docs/modeling-decisions.md#${d.toLowerCase()}`} target="_blank" rel="noreferrer">
                      {d}
                    </a>
                  ))}
                </div>
              ) : null}
              {parents.length || children.length ? (
                <div style={{ fontSize: 14 }}>
                  {parents.length ? <p><span className="muted">Subclass of </span>{parents.map((p) => <ClassLink key={p.target} id={p.target} byId={byId} onPick={setSelected} />)}</p> : null}
                  {children.length ? <p><span className="muted">Subclasses </span>{children.map((c) => <ClassLink key={c.source} id={c.source} byId={byId} onPick={setSelected} />)}</p> : null}
                </div>
              ) : null}
              {outgoing.length || incoming.length ? (
                <details open>
                  <summary style={{ cursor: "pointer", fontWeight: 600 }}>{outgoing.length + incoming.length} object properties</summary>
                  <div style={{ fontSize: 14, marginTop: 6 }}>
                    {outgoing.map((e, i) => (
                      <p key={`o${i}`}>
                        <span className="mono" style={{ color: "var(--accent-ink)" }}>{e.label}</span> <span className="muted">→</span>{" "}
                        <ClassLink id={e.target} byId={byId} onPick={setSelected} />
                      </p>
                    ))}
                    {incoming.map((e, i) => (
                      <p key={`i${i}`}>
                        <ClassLink id={e.source} byId={byId} onPick={setSelected} /> <span className="muted">→</span>{" "}
                        <span className="mono" style={{ color: "var(--accent-ink)" }}>{e.label}</span>
                      </p>
                    ))}
                  </div>
                </details>
              ) : null}
              {node.datatypeProperties.length ? (
                <details>
                  <summary style={{ cursor: "pointer", fontWeight: 600 }}>{node.datatypeProperties.length} data properties</summary>
                  <ul style={{ margin: "8px 0 0", paddingLeft: 18, fontSize: 13.5 }}>
                    {node.datatypeProperties.map((p) => (
                      <li key={p.name} title={p.definition}>
                        <span className="mono">{p.name}</span>
                      </li>
                    ))}
                  </ul>
                </details>
              ) : null}
            </>
          ) : (
            <>
              <h3>How to read this</h3>
              <p className="muted" style={{ fontSize: 14 }}>
                Click a class for its definition. Drag to move, scroll to zoom. Dot size grows with the number of links.
              </p>
              <p className="muted" style={{ fontSize: 13 }}>
                {data.counts.classes} classes · {data.counts.objectProperties} object properties · {data.counts.datatypeProperties} data properties
              </p>
            </>
          )}
        </aside>
      </div>
    </>
  );
}

function ClassLink({ id, byId, onPick }: { id: string; byId: Map<string, OntNode>; onPick: (id: string) => void }) {
  const n = byId.get(id);
  return (
    <button
      onClick={() => onPick(id)}
      style={{ background: "none", border: 0, padding: "0 6px 0 0", cursor: "pointer", color: "var(--accent-ink)", fontWeight: 600, textDecoration: "underline" }}
    >
      {n?.label ?? id}
    </button>
  );
}
