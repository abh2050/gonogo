import * as d3 from "d3";
import { useEffect, useMemo, useRef, useState } from "react";
import { api, local, type GraphNode, type ProvGraph } from "../api";
import { useSession } from "../session";

// The neighborhood of one fact, two steps out, drawn from the live graph (with the session's steward actions
// replayed). It shows the PROV-O chain behind a fact: the activity that generated it, the agent or policy that
// approved it, the candidate it was derived from, the fact it superseded, and the clause it was read from.

type Kind = "fact" | "thing" | "party" | "document" | "vocabulary" | "process" | "external";

const KIND_TEXT: Record<Kind, string> = {
  fact: "Fact (bitemporal)",
  process: "Activity",
  party: "Agent or party",
  document: "Document or clause",
  thing: "Patent",
  vocabulary: "Concept or policy",
  external: "Other",
};

function kindOf(n: GraphNode): Kind {
  const t = n.types.join(" ");
  const id = n.id;
  if (/Action|Approve|Reject|Load|Generation|Extraction|Activity|Correct|LinkIdentity/.test(t) || /\/(action|run)\//.test(id) || /\/synth\/generator\/v/.test(id)) return "process";
  if (/Grant|Record|Export|Status|IdentityLink|Classification|BitemporalFact|Term/.test(t)) return "fact";
  if (/Licensee|Steward|Generator|CoOwner|Agent|Organization|Party/.test(t) || /\/(steward|licensee|co-owner)\//.test(id)) return "party";
  if (/Clause|Document|Notice|Agreement/.test(t) || /\/(clause|doc|notice|agreement)\//.test(id)) return "document";
  if (/Patent/.test(t) || /\/patent\//.test(id)) return "thing";
  if (/\/(field|territory|exclusivity|policy|legal-state|center)\//.test(id)) return "vocabulary";
  return "external";
}

interface SimNode extends d3.SimulationNodeDatum {
  id: string;
  data: GraphNode;
  kind: Kind;
}
interface SimLink extends d3.SimulationLinkDatum<SimNode> {
  label: string;
}

const W = 900;
const H = 560;

export default function ProvenanceGraph({ iri, onClose }: { iri: string; onClose: () => void }) {
  const { events } = useSession();
  const [root, setRoot] = useState(iri);
  const [graph, setGraph] = useState<ProvGraph | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string>(iri);
  const svgRef = useRef<SVGSVGElement>(null);

  useEffect(() => setRoot(iri), [iri]);
  useEffect(() => {
    let live = true;
    setGraph(null);
    setError(null);
    api
      .provenance(events, root)
      .then((g) => live && (setGraph(g), setSelected(root)))
      .catch((e: Error) => live && setError(e.message));
    return () => {
      live = false;
    };
  }, [root, events]);

  const byId = useMemo(() => new Map((graph?.nodes ?? []).map((n) => [n.id, n])), [graph]);

  useEffect(() => {
    if (!graph || !svgRef.current) return;
    const svg = d3.select(svgRef.current);
    svg.selectAll("*").remove();
    // Start on a circle in a fixed order, so the same graph always settles into the same layout.
    const nodes: SimNode[] = graph.nodes.map((n, i) => {
      const a = (i / graph.nodes.length) * 2 * Math.PI;
      const r = 60 + n.depth * 90;
      return { id: n.id, data: n, kind: kindOf(n), x: W / 2 + r * Math.cos(a), y: H / 2 + r * Math.sin(a) };
    });
    const index = new Map(nodes.map((n) => [n.id, n]));
    const links: SimLink[] = graph.links.filter((l) => index.has(l.source) && index.has(l.target)).map((l) => ({ source: l.source, target: l.target, label: l.label }));
    const rootNode = index.get(graph.root);
    if (rootNode) {
      rootNode.fx = W / 2;
      rootNode.fy = H / 2;
    }

    const sim = d3
      .forceSimulation<SimNode>(nodes)
      .force("link", d3.forceLink<SimNode, SimLink>(links).id((d) => d.id).distance((l) => (l.label.startsWith("prov:") || l.label.includes("approved") ? 150 : 120)).strength(0.6))
      .force("charge", d3.forceManyBody().strength(-900))
      .force("collide", d3.forceCollide(48))
      .force("x", d3.forceX(W / 2).strength(0.04))
      .force("y", d3.forceY(H / 2).strength(0.06))
      .stop();
    for (let i = 0; i < 320; i++) sim.tick();

    // Fit the settled layout to the frame, keeping the frame's aspect ratio.
    const xs = nodes.map((n) => n.x!), ys = nodes.map((n) => n.y!);
    const pad = 70;
    let [x0, x1, y0, y1] = [Math.min(...xs) - pad, Math.max(...xs) + pad, Math.min(...ys) - pad, Math.max(...ys) + pad];
    const scale = Math.max((x1 - x0) / W, (y1 - y0) / H, 0.7);
    const cx = (x0 + x1) / 2, cy = (y0 + y1) / 2;
    [x0, x1, y0, y1] = [cx - (W * scale) / 2, cx + (W * scale) / 2, cy - (H * scale) / 2, cy + (H * scale) / 2];
    svg.attr("viewBox", `${x0} ${y0} ${x1 - x0} ${y1 - y0}`);

    const defs = svg.append("defs");
    defs
      .append("marker")
      .attr("id", "prov-arrow")
      .attr("viewBox", "0 -5 10 10")
      .attr("refX", 24)
      .attr("markerWidth", 7)
      .attr("markerHeight", 7)
      .attr("orient", "auto")
      .append("path")
      .attr("d", "M0,-4L10,0L0,4")
      .attr("fill", "var(--faint)");

    const g = svg.append("g");
    svg.call(
      d3
        .zoom<SVGSVGElement, unknown>()
        .scaleExtent([0.4, 3])
        .on("zoom", (e: d3.D3ZoomEvent<SVGSVGElement, unknown>) => g.attr("transform", e.transform.toString())),
    );
    svg.on("dblclick.zoom", null);

    const pos = (n: SimNode | string | number) => n as SimNode;
    const link = g.append("g").selectAll("g").data(links).join("g");
    link
      .append("line")
      .attr("class", "plink")
      .attr("data-from", (d) => (d.source as SimNode).id)
      .attr("data-to", (d) => (d.target as SimNode).id)
      .attr("x1", (d) => pos(d.source).x!)
      .attr("y1", (d) => pos(d.source).y!)
      .attr("x2", (d) => pos(d.target).x!)
      .attr("y2", (d) => pos(d.target).y!)
      .attr("stroke", (d) => (d.label.startsWith("prov:") || d.label === "gng:approvedBy" || d.label === "gng:supersedes" ? "var(--accent)" : "var(--line-strong)"))
      .attr("stroke-width", (d) => (d.label.startsWith("prov:") || d.label === "gng:approvedBy" || d.label === "gng:supersedes" ? 1.8 : 1.2))
      .attr("marker-end", "url(#prov-arrow)");
    link
      .append("text")
      .attr("x", (d) => (pos(d.source).x! + pos(d.target).x!) / 2)
      .attr("y", (d) => (pos(d.source).y! + pos(d.target).y!) / 2 - 3)
      .attr("text-anchor", "middle")
      .attr("class", "edge-label")
      .text((d) => d.label);

    const node = g
      .append("g")
      .selectAll("g")
      .data(nodes)
      .join("g")
      .attr("transform", (d) => `translate(${d.x},${d.y})`)
      .attr("class", "prov-node")
      .style("cursor", "pointer")
      .on("click", (_, d) => setSelected(d.id))
      .on("dblclick", (_, d) => setRoot(d.id));
    node
      .append("circle")
      .attr("r", (d) => (d.id === graph.root ? 15 : d.data.depth === 1 ? 10 : 7))
      .attr("fill", (d) => `var(--k-${d.kind})`)
      .attr("stroke", "var(--surface)")
      .attr("stroke-width", 2.5);
    node
      .append("text")
      .attr("y", (d) => (d.id === graph.root ? 30 : 22))
      .attr("text-anchor", "middle")
      .attr("class", "node-label")
      .text((d) => (d.data.label.length > 34 ? d.data.label.slice(0, 32) + "…" : d.data.label));
  }, [graph]);

  useEffect(() => {
    if (!svgRef.current) return;
    const svg = d3.select(svgRef.current);
    svg.selectAll<SVGGElement, SimNode>("g.prov-node").classed("selected", (d) => d.id === selected);
    // The selected node's relationships flow in the direction they point.
    svg.selectAll<SVGLineElement, unknown>("line.plink").classed("flow", function () {
      return this.dataset.from === selected || this.dataset.to === selected;
    });
  }, [selected, graph]);

  const sel = byId.get(selected);
  const kinds = useMemo(() => [...new Set((graph?.nodes ?? []).map(kindOf))], [graph]);

  return (
    <section className="card prov" aria-label="Provenance graph">
      <header className="prov-head">
        <div>
          <div className="eyebrow">Provenance graph · PROV-O</div>
          <h2 className="mono small-h">{local(root)}</h2>
        </div>
        <button className="close-x" onClick={onClose} aria-label="Close the provenance graph">
          ×
        </button>
      </header>
      {error ? <div className="error">{error}</div> : null}
      {!graph && !error ? <div className="loading">Walking the graph…</div> : null}
      <div className="prov-body">
        <div className="viz prov-viz">
          <svg ref={svgRef} viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Graph around ${local(root)}`} />
          <div className="legend prov-legend">
            {kinds.map((k) => (
              <span key={k} className="legend-item">
                <span className="swatch" style={{ background: `var(--k-${k})` }} />
                {KIND_TEXT[k]}
              </span>
            ))}
          </div>
        </div>
        {sel ? (
          <aside className="panel prov-panel">
            <h3>{sel.label}</h3>
            <p className="mono faint small break">{sel.id}</p>
            <div className="chips">
              {sel.types.map((t) => (
                <span key={t} className="tag">
                  {t}
                </span>
              ))}
            </div>
            <dl className="attrs">
              {Object.entries(sel.attrs)
                .slice(0, 14)
                .map(([k, v]) => (
                  <div key={k}>
                    <dt className="mono">{k}</dt>
                    <dd>{v}</dd>
                  </div>
                ))}
            </dl>
            {sel.id !== root ? (
              <button className="button" onClick={() => setRoot(sel.id)}>
                Center the graph here
              </button>
            ) : null}
            <p className="muted small">Click a node to inspect it. Double-click to walk to it. Blue edges are provenance.</p>
          </aside>
        ) : null}
      </div>
    </section>
  );
}
