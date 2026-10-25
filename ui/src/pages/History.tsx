import * as d3 from "d3";
import { useEffect, useMemo, useRef, useState } from "react";
import { VERDICT_CLASS, type Verdict } from "../api";
import VerdictCard from "../components/VerdictCard";
import { useSession, type Entry } from "../session";

const VERDICT_COLOR: Record<Verdict, string> = {
  GO: "var(--go)",
  "NO GO": "var(--nogo)",
  HOLD: "var(--hold)",
  COUNSEL: "var(--counsel)",
  "NO DATA": "var(--nodata)",
};

/** One row per question, one column per steward action applied: how each verdict moved as evidence arrived. */
function Timeline({ entries, steps, onPick }: { entries: Entry[]; steps: number; onPick: (e: Entry) => void }) {
  const ref = useRef<SVGSVGElement>(null);
  const rows = useMemo(() => [...new Set(entries.map((e) => e.label))], [entries]);
  const height = 40 + rows.length * 46;
  const width = 900;

  useEffect(() => {
    if (!ref.current) return;
    const svg = d3.select(ref.current);
    svg.selectAll("*").remove();
    const x = d3
      .scaleLinear()
      .domain([0, Math.max(steps, 1)])
      .range([300, width - 40]);
    const y = d3
      .scalePoint<string>()
      .domain(rows)
      .range([40, height - 20]);

    const axis = svg.append("g").attr("class", "axis");
    for (let s = 0; s <= Math.max(steps, 1); s++) {
      axis.append("line").attr("x1", x(s)).attr("x2", x(s)).attr("y1", 22).attr("y2", height - 8).attr("stroke", "var(--line)");
      axis
        .append("text")
        .attr("x", x(s))
        .attr("y", 14)
        .attr("text-anchor", "middle")
        .attr("class", "tick-label")
        .text(s === 0 ? "frozen graph" : `after action ${s}`);
    }

    for (const label of rows) {
      const points = entries
        .filter((e) => e.label === label)
        .map((e) => ({ s: e.decision.events_applied, e }))
        .sort((a, b) => a.s - b.s);
      const yy = y(label)!;
      svg
        .append("text")
        .attr("x", 290)
        .attr("y", yy + 4)
        .attr("text-anchor", "end")
        .attr("class", "row-label")
        .text(label.length > 44 ? label.slice(0, 42) + "…" : label);
      svg
        .append("path")
        .attr("d", d3.line<{ s: number }>().x((p) => x(p.s)).y(() => yy)(points))
        .attr("stroke", "var(--line-strong)")
        .attr("stroke-width", 2)
        .attr("fill", "none");
      const dots = svg
        .append("g")
        .selectAll("g")
        .data(points)
        .join("g")
        .attr("transform", (p) => `translate(${x(p.s)},${yy})`)
        .style("cursor", "pointer")
        .on("click", (_, p) => onPick(p.e));
      dots
        .append("circle")
        .attr("r", 9)
        .attr("fill", (p) => VERDICT_COLOR[p.e.decision.verdict])
        .attr("stroke", "var(--surface)")
        .attr("stroke-width", 2);
      dots.append("title").text((p) => `${p.e.decision.verdict} · ${p.e.decision.id}`);
    }
  }, [entries, rows, steps, height, onPick]);

  return <svg ref={ref} viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Verdicts over the session" className="timeline" />;
}

export default function History() {
  const { history, events } = useSession();
  const [picked, setPicked] = useState<Entry | null>(history[0] ?? null);
  const counts = useMemo(() => {
    const c = new Map<Verdict, number>();
    for (const e of history) c.set(e.decision.verdict, (c.get(e.decision.verdict) ?? 0) + 1);
    return c;
  }, [history]);

  return (
    <div className="page">
      <header className="page-head">
        <div className="eyebrow">History</div>
        <h1>Every decision keeps its context</h1>
        <p className="lede">
          Each decision stores what it depended on: the recording cutoff, the release, every rule version, the facts
          each rule read, and a signature over the findings. Because the graph keeps recording time, a decision rerun
          from its cutoff gives the same answer after any later approval. The rerun button on the Ask page checks it.
        </p>
      </header>
      {!history.length ? (
        <p className="callout">
          No decisions yet. Start on the <a href="#/ask">Ask</a> page, then approve a fact on the <a href="#/steward">Steward</a> page.
        </p>
      ) : (
        <>
          <div className="chips">
            {[...counts.entries()].map(([v, n]) => (
              <span key={v} className={`chip ${VERDICT_CLASS[v]}`}>
                {v} × {n}
              </span>
            ))}
            <span className="muted small">
              {events.length} steward action{events.length === 1 ? "" : "s"}
            </span>
          </div>
          <div className="viz card">
            <Timeline entries={history} steps={events.length} onPick={setPicked} />
          </div>
          <div className="history-split">
            <ol className="history-list">
              {history.map((e) => (
                <li key={e.decision.id + e.decision.events_applied}>
                  <button className="history-item" aria-pressed={picked === e} onClick={() => setPicked(e)}>
                    <span className={`chip ${VERDICT_CLASS[e.decision.verdict]}`}>{e.decision.verdict}</span>
                    <span>{e.label}</span>
                    <span className="mono faint small">
                      {e.decision.id} · {e.decision.events_applied} actions
                    </span>
                  </button>
                </li>
              ))}
            </ol>
            {picked ? <VerdictCard key={picked.decision.id + picked.decision.events_applied} decision={picked.decision} diff={picked.diff} /> : null}
          </div>
          <details className="card">
            <summary>The decision record as stored (JSON)</summary>
            <pre className="sparql">{JSON.stringify(picked?.decision, null, 2)}</pre>
          </details>
        </>
      )}
    </div>
  );
}
