import { useState } from "react";

// A small diagram engine: boxes at fixed positions, arrows between them, groups behind them, and a panel that
// explains whichever box you point at. The layout is data, so the page and the docs can show the same picture.

export type Kind = "step" | "store" | "service" | "person" | "control" | "model" | "ext";

export interface DNode {
  id: string;
  x: number;
  y: number;
  w?: number;
  h?: number;
  label: string;
  sub?: string;
  kind: Kind;
  detail: string;
  where?: string; // where in the repository
  dashed?: boolean;
}
export interface DEdge {
  from: string;
  to: string;
  label?: string;
  dashed?: boolean;
}
export interface DGroup {
  x: number;
  y: number;
  w: number;
  h: number;
  label: string;
}

const FILL: Record<Kind, string> = {
  step: "var(--accent-soft)",
  store: "var(--surface-2)",
  service: "color-mix(in srgb, var(--k-thing) 14%, var(--surface))",
  person: "color-mix(in srgb, var(--k-party) 14%, var(--surface))",
  control: "color-mix(in srgb, var(--k-vocabulary) 16%, var(--surface))",
  model: "color-mix(in srgb, var(--k-document) 16%, var(--surface))",
  ext: "var(--surface)",
};
const STROKE: Record<Kind, string> = {
  step: "var(--accent)",
  store: "var(--line-strong)",
  service: "var(--k-thing)",
  person: "var(--k-party)",
  control: "var(--k-vocabulary)",
  model: "var(--k-document)",
  ext: "var(--line-strong)",
};

const W = 150;
const H = 62;

function box(n: DNode) {
  return { x: n.x, y: n.y, w: n.w ?? W, h: n.h ?? H };
}

/** The point where the line from a box's center toward (tx, ty) leaves the box. */
function edgePoint(n: DNode, tx: number, ty: number): [number, number] {
  const b = box(n);
  const cx = b.x + b.w / 2;
  const cy = b.y + b.h / 2;
  const dx = tx - cx;
  const dy = ty - cy;
  if (dx === 0 && dy === 0) return [cx, cy];
  const s = Math.min(b.w / 2 / Math.abs(dx || 1e-9), b.h / 2 / Math.abs(dy || 1e-9));
  return [cx + dx * s, cy + dy * s];
}

export default function Diagram({
  nodes,
  edges,
  groups = [],
  width,
  height,
  label,
}: {
  nodes: DNode[];
  edges: DEdge[];
  groups?: DGroup[];
  width: number;
  height: number;
  label: string;
}) {
  const [picked, setPicked] = useState<string | null>(null);
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const sel = picked ? byId.get(picked) : undefined;
  const related = new Set(sel ? edges.filter((e) => e.from === sel.id || e.to === sel.id).flatMap((e) => [e.from, e.to]) : []);

  return (
    <div className="diagram">
      <div className="viz diagram-viz">
        <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={label}>
          <defs>
            <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
              <path d="M0,0 L10,5 L0,10 z" fill="var(--faint)" />
            </marker>
          </defs>
          {groups.map((g) => (
            <g key={g.label}>
              <rect x={g.x} y={g.y} width={g.w} height={g.h} rx={16} fill="none" stroke="var(--line-strong)" strokeDasharray="6 5" />
              <text x={g.x + 14} y={g.y + 20} className="group-label">
                {g.label}
              </text>
            </g>
          ))}
          {edges.map((e) => {
            const a = byId.get(e.from)!;
            const b = byId.get(e.to)!;
            const ba = box(a);
            const bb = box(b);
            const [x1, y1] = edgePoint(a, bb.x + bb.w / 2, bb.y + bb.h / 2);
            const [x2, y2] = edgePoint(b, ba.x + ba.w / 2, ba.y + ba.h / 2);
            const lit = sel && (e.from === sel.id || e.to === sel.id);
            return (
              <g key={`${e.from}-${e.to}-${e.label ?? ""}`} opacity={sel && !lit ? 0.25 : 1}>
                <line
                  x1={x1}
                  y1={y1}
                  x2={x2}
                  y2={y2}
                  stroke={lit ? "var(--accent)" : "var(--faint)"}
                  strokeWidth={lit ? 2.2 : 1.5}
                  strokeDasharray={e.dashed ? "5 4" : undefined}
                  markerEnd="url(#arrow)"
                />
                {e.label ? (
                  <text x={(x1 + x2) / 2} y={(y1 + y2) / 2 - 5} textAnchor="middle" className="edge-note">
                    {e.label}
                  </text>
                ) : null}
              </g>
            );
          })}
          {nodes.map((n) => {
            const b = box(n);
            const dim = sel && n.id !== sel.id && !related.has(n.id);
            return (
              <g
                key={n.id}
                className={`dnode${n.id === picked ? " picked" : ""}`}
                opacity={dim ? 0.35 : 1}
                tabIndex={0}
                role="button"
                aria-label={`${n.label}: ${n.detail}`}
                onMouseEnter={() => setPicked(n.id)}
                onFocus={() => setPicked(n.id)}
                onClick={() => setPicked(n.id)}
              >
                <rect
                  x={b.x}
                  y={b.y}
                  width={b.w}
                  height={b.h}
                  rx={n.kind === "store" ? 22 : 12}
                  fill={FILL[n.kind]}
                  stroke={STROKE[n.kind]}
                  strokeWidth={n.id === picked ? 3 : 1.6}
                  strokeDasharray={n.dashed ? "6 4" : undefined}
                />
                <text x={b.x + b.w / 2} y={b.y + b.h / 2 + (n.sub ? -3 : 5)} textAnchor="middle" className="dnode-label">
                  {n.label}
                </text>
                {n.sub ? (
                  <text x={b.x + b.w / 2} y={b.y + b.h / 2 + 14} textAnchor="middle" className="dnode-sub">
                    {n.sub}
                  </text>
                ) : null}
              </g>
            );
          })}
        </svg>
      </div>
      <aside className="panel diagram-panel" aria-live="polite">
        {sel ? (
          <>
            <h3>{sel.label}</h3>
            <p>{sel.detail}</p>
            {sel.where ? (
              <p className="mono faint small break">{sel.where}</p>
            ) : null}
          </>
        ) : (
          <p className="muted">Point at a box to see what it does and where its code lives. The arrows that touch it light up.</p>
        )}
      </aside>
    </div>
  );
}
