import * as d3 from "d3";
import { useMemo, useRef, useState } from "react";
import { Failed, Loading } from "../components/Loading";
import { useJson, type Bitemporal, type BitemporalFact } from "../data";

const W = 1000;
const H = 520;
const M = { top: 46, right: 28, bottom: 58, left: 92 };

const day = (iso: string) => new Date(iso.length === 10 ? `${iso}T00:00:00Z` : iso);
const fmt = d3.utcFormat("%-d %b %Y");
const fmtShort = d3.utcFormat("%b %Y");

function believed(f: BitemporalFact, cutoff: Date): boolean {
  if (day(f.recordedAt) > cutoff) return false;
  return !(f.supersededAt && day(f.supersededAt) <= cutoff);
}

export default function TimeTravel() {
  const { data, error } = useJson<Bitemporal>("bitemporal.json");
  const [cutoffMs, setCutoffMs] = useState<number | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);

  const scales = useMemo(() => {
    if (!data) return null;
    const vFrom = d3.min(data.facts, (f) => day(f.validFrom))!;
    const vTo = d3.max(data.facts, (f) => day(f.validTo))!;
    const rMin = d3.min(data.facts, (f) => day(f.recordedAt))!;
    const rMax = d3.utcMonth.offset(day(data.cutoffAfter), 7);
    const x = d3
      .scaleUtc()
      .domain([d3.utcMonth.offset(vFrom, -12), d3.utcMonth.offset(vTo, 12)])
      .range([M.left, W - M.right]);
    const y = d3
      .scaleUtc()
      .domain([d3.utcMonth.offset(rMin, -4), d3.utcMonth.offset(rMax, 2)])
      .range([M.top, H - M.bottom]);
    return { x, y };
  }, [data]);

  if (error) return <Failed error={error} />;
  if (!data || !scales) return <Loading what="the time model" />;

  const { x, y } = scales;
  const before = day(data.cutoffBefore);
  const after = day(data.cutoffAfter);
  const cutoff = new Date(cutoffMs ?? after.getTime());
  const lo = y.domain()[0].getTime();
  const hi = day(data.cutoffAfter).getTime() + 90 * 86400000;
  const known = data.facts.filter((f) => believed(f, cutoff));
  const conflict = known.some((f) => f.field === data.requestField);
  const yEnd = y.range()[1];

  const setFromPointer = (clientY: number) => {
    const svg = svgRef.current;
    if (!svg) return;
    const box = svg.getBoundingClientRect();
    const svgY = ((clientY - box.top) / box.height) * H;
    const t = y.invert(Math.min(Math.max(svgY, y.range()[0]), yEnd)).getTime();
    setCutoffMs(Math.min(Math.max(t, lo), hi));
  };

  const xTicks = x.ticks(d3.utcYear.every(2) ?? d3.utcYear);
  const yTicks = y.ticks(d3.utcMonth.every(6) ?? d3.utcMonth);

  return (
    <>
      <div className="page-head">
        <div className="eyebrow">The time model</div>
        <h1>What the system knew, and when</h1>
        <p className="lede">
          Every fact has two times. The valid time says when it holds in the world, and the recording time says when
          the system learned it. A late correction supersedes a fact and never deletes it. Drag the line to choose a
          recording cutoff, and see which grant the system believed at that moment.
        </p>
      </div>

      <div className="split">
        <div className="viz">
          <div className="viz-toolbar">
            <div className="segmented" role="group" aria-label="Jump to a cutoff">
              <button aria-pressed={cutoff.getTime() === before.getTime()} onClick={() => setCutoffMs(before.getTime())}>
                Replay the {fmt(before).replace(/ \d{4}$/, "")} decision
              </button>
              <button aria-pressed={cutoff.getTime() === after.getTime()} onClick={() => setCutoffMs(after.getTime())}>
                Decide again on {fmt(after).replace(/ \d{4}$/, "")}
              </button>
            </div>
            <span className="muted" style={{ fontSize: 14 }}>Cutoff: <strong style={{ color: "var(--ink)" }}>{fmt(cutoff)}</strong></span>
          </div>
          <svg
            ref={svgRef}
            viewBox={`0 0 ${W} ${H}`}
            role="group"
            aria-label="Bitemporal diagram: valid time across, recording time down"
            onPointerDown={(e) => {
              (e.currentTarget as SVGSVGElement).setPointerCapture(e.pointerId);
              setFromPointer(e.clientY);
            }}
            onPointerMove={(e) => {
              if (e.buttons === 1) setFromPointer(e.clientY);
            }}
            style={{ touchAction: "none", cursor: "ns-resize" }}
          >
            {xTicks.map((t) => (
              <g key={`x${t.getTime()}`}>
                <line x1={x(t)} x2={x(t)} y1={M.top} y2={H - M.bottom} style={{ stroke: "var(--line)" }} />
                <text x={x(t)} y={H - M.bottom + 20} textAnchor="middle" fontSize="12" style={{ fill: "var(--muted)" }}>{t.getUTCFullYear()}</text>
              </g>
            ))}
            {yTicks.map((t) => (
              <g key={`y${t.getTime()}`}>
                <line x1={M.left} x2={W - M.right} y1={y(t)} y2={y(t)} style={{ stroke: "var(--line)" }} />
                <text x={M.left - 10} y={y(t) + 4} textAnchor="end" fontSize="12" style={{ fill: "var(--muted)" }}>{fmtShort(t)}</text>
              </g>
            ))}
            <text x={(M.left + W - M.right) / 2} y={H - 12} textAnchor="middle" fontSize="13" fontWeight="600" style={{ fill: "var(--ink)" }}>
              Valid time: when the grant applies in the world →
            </text>
            <text transform={`translate(18,${(M.top + H - M.bottom) / 2}) rotate(-90)`} textAnchor="middle" fontSize="13" fontWeight="600" style={{ fill: "var(--ink)" }}>
              Recording time: when the system learned it (later is lower) →
            </text>

            {data.facts.map((f, i) => {
              const live = believed(f, cutoff);
              const x0 = x(day(f.validFrom));
              const x1 = x(day(f.validTo));
              const y0 = y(day(f.recordedAt));
              const y1 = f.supersededAt ? y(day(f.supersededAt)) : yEnd;
              const color = i === 0 ? "var(--counsel)" : "var(--go)";
              const soft = i === 0 ? "var(--counsel-soft)" : "var(--go-soft)";
              return (
                <g key={f.id} style={{ opacity: live ? 1 : 0.38, transition: "opacity .15s" }}>
                  <rect x={x0} y={y0} width={x1 - x0} height={y1 - y0} rx={10} style={{ fill: soft, stroke: color, strokeWidth: live ? 3 : 1.5 }} />
                  <text x={(x0 + x1) / 2} y={(y0 + y1) / 2 - 6} textAnchor="middle" fontSize="15" fontWeight="650" style={{ fill: "var(--ink)" }}>
                    {f.id} · {f.field}
                  </text>
                  <text x={(x0 + x1) / 2} y={(y0 + y1) / 2 + 14} textAnchor="middle" fontSize="12.5" style={{ fill: "var(--muted)" }}>
                    recorded {fmt(day(f.recordedAt))}
                    {f.supersededAt ? `, replaced ${fmt(day(f.supersededAt))}` : ", still current"}
                  </text>
                </g>
              );
            })}

            <g>
              <line x1={M.left - 6} x2={W - M.right} y1={y(cutoff)} y2={y(cutoff)} style={{ stroke: "var(--accent)", strokeWidth: 2.5, strokeDasharray: "7 5" }} />
              <rect x={W - M.right - 150} y={y(cutoff) - 26} width={150} height={22} rx={7} style={{ fill: "var(--accent)" }} />
              <text x={W - M.right - 75} y={y(cutoff) - 11} textAnchor="middle" fontSize="12.5" fontWeight="650" fill="#fff">
                cutoff {fmt(cutoff)}
              </text>
            </g>
          </svg>
          <div style={{ padding: "6px 18px 16px" }}>
            <label className="muted" style={{ fontSize: 13 }} htmlFor="cutoff">Recording cutoff</label>
            <input
              id="cutoff"
              type="range"
              min={lo}
              max={hi}
              step={86400000}
              value={cutoff.getTime()}
              onChange={(e) => setCutoffMs(Number(e.target.value))}
            />
          </div>
        </div>

        <aside className="panel" aria-live="polite">
          <h3>At {fmt(cutoff)}, the system believes</h3>
          {known.length ? (
            known.map((f) => (
              <div key={f.id} className="callout">
                <strong>{f.id}</strong> grants exclusive rights in <strong>{f.field}</strong> on {data.patent}, valid from{" "}
                {fmt(day(f.validFrom))} to {fmt(day(f.validTo))}.
              </div>
            ))
          ) : (
            <div className="callout">The system has recorded no grant on this patent yet.</div>
          )}
          <div>
            <div className="muted" style={{ fontSize: 12.5, marginBottom: 4 }}>The request</div>
            <p style={{ fontSize: 14.5 }}>{data.requestText}</p>
          </div>
          <div className={`callout ${conflict ? "warn" : "ok"}`}>
            {known.length === 0
              ? "With no grant on record, rule R2 finds nothing to conflict with."
              : conflict
                ? `Rule R2 finds an overlapping exclusive grant in ${data.requestField}, so the verdict is NO GO.`
                : `The believed grant is in a different field from the request (${data.requestField}), so rule R2 finds no conflict.`}
          </div>
          <p className="muted" style={{ fontSize: 13.5 }}>
            A stored decision keeps its cutoff. Replaying the {fmt(before).replace(/ \d{4}$/, "")} decision uses that
            cutoff, so it returns the original answer even though a correction arrived afterward. A new request uses
            today's cutoff and sees the correction.
          </p>
          <p className="muted" style={{ fontSize: 13.5 }}>
            In the graph: <code>gng:recordedAt</code>, <code>gng:supersededAt</code>, and <code>gng:supersedes</code>.
            Every query adds one filter, written once in the template engine, so no rule can forget it.
          </p>
        </aside>
      </div>
    </>
  );
}
