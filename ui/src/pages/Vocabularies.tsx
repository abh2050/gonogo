import * as d3 from "d3";
import { useMemo, useState } from "react";
import { Failed, Loading } from "../components/Loading";
import { useJson, type Concept, type Scheme } from "../data";

type Role = "grant" | "request";
type Which = "fields" | "territories";

interface Placed {
  concept: Concept;
  depth: number;
  x: number; // vertical position
  y: number; // horizontal position
  parent: string | null;
  isRoot: boolean;
}

const COLUMN = 250;
const ROW = 21;
const MARGIN = { top: 28, left: 170, right: 230, bottom: 28 };

function label(c: Concept): string {
  return c.iso ? `${c.label} (${c.iso})` : c.label;
}

function descendants(c: Concept): Set<string> {
  const out = new Set<string>([c.id]);
  (c.children ?? []).forEach((k) => descendants(k).forEach((id) => out.add(id)));
  return out;
}

function flatten(c: Concept, into: Map<string, Concept> = new Map()): Map<string, Concept> {
  into.set(c.id, c);
  (c.children ?? []).forEach((k) => flatten(k, into));
  return into;
}

function relation(grant: Concept, request: Concept): { text: string; tone: "ok" | "warn" } {
  if (grant.id === request.id) {
    return { text: "The grant and the request name the same concept, so the grant covers the request exactly. Rule R2 sees an overlap.", tone: "warn" };
  }
  if (descendants(grant).has(request.id)) {
    return {
      text: `The grant covers the request. "${request.label}" sits beneath "${grant.label}", so rights granted for the broader concept reach it. Rule R2 sees an overlap.`,
      tone: "warn",
    };
  }
  if (descendants(request).has(grant.id)) {
    return {
      text: `The request covers the grant. "${request.label}" is broader than "${grant.label}", so asking for it reaches the granted concept. Rule R2 sees an overlap.`,
      tone: "warn",
    };
  }
  return {
    text: `No overlap. "${grant.label}" and "${request.label}" sit on different branches, so neither one reaches the other. Rule R2 finds no conflict on this dimension.`,
    tone: "ok",
  };
}

export default function Vocabularies() {
  const fields = useJson<Scheme>("fields.json");
  const territories = useJson<Scheme>("territories.json");
  const [which, setWhich] = useState<Which>("fields");
  const [role, setRole] = useState<Role>("grant");
  const [picked, setPicked] = useState<Record<Which, { grant: string; request: string }>>({
    fields: { grant: "optics", request: "lasers" },
    territories: { grant: "NORTH-AMERICA", request: "US" },
  });

  const scheme = which === "fields" ? fields.data : territories.data;

  const model = useMemo(() => {
    if (!scheme) return null;
    const root: Concept =
      which === "fields" ? { id: "__root", label: "Fields of use", notation: "", children: scheme.tops } : scheme.tops[0];
    const laid = d3
      .tree<Concept>()
      .nodeSize([ROW, COLUMN])
      .separation((a, b) => (a.parent === b.parent ? 1 : 1.35))(d3.hierarchy<Concept>(root, (d) => d.children));
    const nodes = laid.descendants();
    const minX = Math.min(...nodes.map((n) => n.x));
    const maxX = Math.max(...nodes.map((n) => n.x));
    const maxDepth = Math.max(...nodes.map((n) => n.depth));
    const placed: Placed[] = nodes.map((n) => ({
      concept: n.data,
      depth: n.depth,
      x: n.x - minX + MARGIN.top,
      y: n.y + MARGIN.left,
      parent: n.parent ? n.parent.data.id : null,
      isRoot: n.depth === 0,
    }));
    return {
      placed,
      byId: flatten(root),
      root,
      width: maxDepth * COLUMN + MARGIN.left + MARGIN.right,
      height: maxX - minX + MARGIN.top + MARGIN.bottom,
    };
  }, [scheme, which]);

  if (fields.error || territories.error) return <Failed error={fields.error ?? territories.error ?? ""} />;
  if (!scheme || !model) return <Loading what="the vocabularies" />;

  const current = picked[which];
  const grant = model.byId.get(current.grant) ?? model.root;
  const request = model.byId.get(current.request) ?? model.root;
  const grantReach = descendants(grant);
  const requestReach = descendants(request);
  const rel = relation(grant, request);
  const byConcept = new Map(model.placed.map((p) => [p.concept.id, p]));
  const reachList = [...grantReach].map((id) => model.byId.get(id)!).filter(Boolean);

  const choose = (id: string) => {
    if (id === "__root") return;
    setPicked({ ...picked, [which]: { ...current, [role]: id } });
  };

  const link = (parent: Placed, child: Placed): string => {
    const mid = (parent.y + child.y) / 2;
    return `M${parent.y},${parent.x}C${mid},${parent.x} ${mid},${child.x} ${child.y},${child.x}`;
  };

  return (
    <>
      <div className="page-head">
        <div className="eyebrow">Vocabularies</div>
        <h1>Broader means wider rights</h1>
        <p className="lede">
          Fields of use and territories are SKOS concepts, not OWL subclasses. A grant for a broader concept covers
          everything beneath it, and the ontology states that rule once, as a property chain. Pick a grant and a
          request below to see how the rule answers.
        </p>
      </div>

      <div className="split">
        <div className="viz">
          <div className="viz-toolbar">
            <div className="segmented" role="group" aria-label="Vocabulary">
              <button aria-pressed={which === "fields"} onClick={() => setWhich("fields")}>Fields of use</button>
              <button aria-pressed={which === "territories"} onClick={() => setWhich("territories")}>Territories</button>
            </div>
            <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
              <span className="muted" style={{ fontSize: 14 }}>A click sets the</span>
              <div className="segmented" role="group" aria-label="Which role a click sets">
                <button aria-pressed={role === "grant"} onClick={() => setRole("grant")}>
                  <span className="swatch" style={{ background: "var(--accent)", marginRight: 6 }} />Grant
                </button>
                <button aria-pressed={role === "request"} onClick={() => setRole("request")}>
                  <span className="swatch" style={{ background: "var(--amber)", marginRight: 6 }} />Request
                </button>
              </div>
            </div>
          </div>
          <svg viewBox={`0 0 ${model.width} ${model.height}`} role="group" aria-label={`${which} hierarchy`}>
            <g fill="none">
              {model.placed
                .filter((p) => p.parent !== null)
                .map((p) => {
                  const parent = byConcept.get(p.parent!)!;
                  const inGrant = grantReach.has(p.concept.id) && grantReach.has(parent.concept.id);
                  const inRequest = requestReach.has(p.concept.id) && requestReach.has(parent.concept.id);
                  return (
                    <path
                      key={p.concept.id}
                      d={link(parent, p)}
                      style={{
                        stroke: inGrant ? "var(--accent)" : inRequest ? "var(--amber)" : "var(--line-strong)",
                        strokeWidth: inGrant || inRequest ? 2.6 : 1.4,
                      }}
                    />
                  );
                })}
            </g>
            <g>
              {model.placed.map((p) => {
                const id = p.concept.id;
                const inGrant = grantReach.has(id);
                const inRequest = requestReach.has(id);
                const isGrant = id === grant.id;
                const isRequest = id === request.id;
                const r = isGrant || isRequest ? 8.5 : p.depth <= 1 ? 6.5 : 5.5;
                const fill = isGrant ? "var(--accent)" : isRequest ? "var(--amber)" : inGrant ? "var(--accent-soft)" : inRequest ? "var(--amber-soft)" : "var(--surface)";
                const stroke = inGrant && inRequest ? "var(--counsel)" : inGrant ? "var(--accent)" : inRequest ? "var(--amber)" : "var(--faint)";
                return (
                  <g
                    key={id}
                    transform={`translate(${p.y},${p.x})`}
                    onClick={() => choose(id)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        choose(id);
                      }
                    }}
                    tabIndex={p.isRoot && which === "fields" ? -1 : 0}
                    role="button"
                    aria-label={`${label(p.concept)}${isGrant ? ", the grant" : ""}${isRequest ? ", the request" : ""}`}
                    style={{ cursor: p.isRoot && which === "fields" ? "default" : "pointer" }}
                  >
                    <rect x={p.concept.children ? -(COLUMN - 60) : -8} y={-ROW / 2} width={COLUMN - 40} height={ROW} fill="transparent" />
                    <circle r={r} style={{ fill, stroke, strokeWidth: isGrant || isRequest ? 3 : 2 }} />
                    <text
                      x={p.concept.children ? -(r + 8) : r + 8}
                      textAnchor={p.concept.children ? "end" : "start"}
                      dy="0.34em"
                      fontSize={p.depth === 0 ? 14 : 13}
                      fontWeight={p.depth <= 1 || isGrant || isRequest ? 650 : 480}
                      style={{ fill: "var(--ink)", pointerEvents: "none", paintOrder: "stroke", stroke: "var(--surface)", strokeWidth: 5, strokeLinejoin: "round" }}
                    >
                      {label(p.concept)}
                    </text>
                  </g>
                );
              })}
            </g>
          </svg>
        </div>

        <aside className="panel" aria-live="polite">
          <h3>Does the grant touch the request?</h3>
          <div style={{ display: "grid", gap: 6, fontSize: 15 }}>
            <div>
              <span className="swatch" style={{ background: "var(--accent)", marginRight: 8 }} />
              <strong>Grant:</strong> {label(grant)}
            </div>
            <div>
              <span className="swatch" style={{ background: "var(--amber)", marginRight: 8 }} />
              <strong>Request:</strong> {label(request)}
            </div>
          </div>
          <div className={`callout ${rel.tone}`}>{rel.text}</div>
          <div>
            <div className="muted" style={{ fontSize: 12.5, marginBottom: 4 }}>
              The grant's rights reach {reachList.length} concept{reachList.length === 1 ? "" : "s"}
            </div>
            <div>
              {reachList.slice(0, 14).map((c) => (
                <span className="tag" key={c.id}>{c.label}</span>
              ))}
              {reachList.length > 14 ? <span className="muted"> and {reachList.length - 14} more</span> : null}
            </div>
          </div>
          <p className="muted" style={{ fontSize: 13.5 }}>
            In the graph, this is <code>{which === "fields" ? "gng:coversField" : "gng:coversTerritory"}</code>, derived
            from <code>skos:narrowerTransitive</code> by a property chain. Moving one concept in the hierarchy changes
            which requests a grant reaches, so every hierarchy edit is a legal change. The release pipeline will list
            each verdict that an edit would flip before the edit goes live.
          </p>
          <p className="muted" style={{ fontSize: 13.5 }}>
            {which === "fields"
              ? "The top level reuses the NASA Technology Transfer portal's categories. The second level is GoNoGo's refinement."
              : "Countries carry ISO 3166-1 alpha-2 codes. The regions are commercial groupings, so North America includes Mexico."}
          </p>
        </aside>
      </div>
    </>
  );
}
