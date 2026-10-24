import { useMemo, useState } from "react";
import ChartCanvas, { type ChartColors } from "../components/ChartCanvas";
import { Failed, Loading } from "../components/Loading";
import Stat from "../components/Stat";
import { useJson, type Findings as FindingsData, type LapsedPatent } from "../data";

const STATE_LABEL: Record<string, string> = {
  lapsed: "Lapsed for unpaid fees",
  in_force: "In force",
  abandoned: "Abandoned",
  term_ended: "Term ended",
};

function year(iso: string): number {
  const d = new Date(iso + "T00:00:00Z");
  return d.getUTCFullYear() + (d.getUTCMonth() + 0.5) / 12;
}

function Dumbbell({ rows, median }: { rows: LapsedPatent[]; median: number }) {
  const [hover, setHover] = useState<LapsedPatent | null>(null);
  const rowH = 6;
  const left = 56;
  const right = 24;
  const top = 34;
  const width = 1000;
  const min = Math.floor(Math.min(...rows.map((r) => year(r.lapse))) / 2) * 2;
  const max = Math.ceil(Math.max(...rows.map((r) => year(r.nasaExpires))) / 2) * 2;
  const x = (iso: string) => left + ((year(iso) - min) / (max - min)) * (width - left - right);
  const height = top + rows.length * rowH + 12;
  const ticks: number[] = [];
  for (let y = min; y <= max; y += 2) ticks.push(y);
  return (
    <div className="viz" style={{ position: "relative" }}>
      <div className="viz-toolbar">
        <div className="legend">
          <span className="legend-item" style={{ cursor: "default" }}>
            <span className="swatch" style={{ background: "var(--nogo)" }} /> Date USPTO recorded the lapse
          </span>
          <span className="legend-item" style={{ cursor: "default" }}>
            <span className="swatch" style={{ background: "var(--faint)" }} /> Expiration date in the NASA snapshot
          </span>
        </div>
        <span className="muted" style={{ fontSize: 14 }}>Median gap: {median} years</span>
      </div>
      <div className="scroll-y">
        <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${rows.length} lapsed patents. Each line runs from the lapse date to the date that the NASA snapshot still shows the patent alive.`}>
          {ticks.map((t) => (
            <g key={t}>
              <line x1={left + ((t - min) / (max - min)) * (width - left - right)} x2={left + ((t - min) / (max - min)) * (width - left - right)} y1={top - 8} y2={height - 6} style={{ stroke: "var(--line)" }} />
              <text x={left + ((t - min) / (max - min)) * (width - left - right)} y={top - 14} textAnchor="middle" fontSize="12" style={{ fill: "var(--muted)" }}>{t}</text>
            </g>
          ))}
          {rows.map((r, i) => {
            const y = top + i * rowH + rowH / 2;
            return (
              <g key={r.key} onMouseEnter={() => setHover(r)} onMouseLeave={() => setHover(null)}>
                <rect x={0} y={y - rowH / 2} width={width} height={rowH} fill="transparent" />
                <line x1={x(r.lapse)} x2={x(r.nasaExpires)} y1={y} y2={y} style={{ stroke: hover?.key === r.key ? "var(--ink)" : "var(--line-strong)", strokeWidth: hover?.key === r.key ? 2 : 1.2 }} />
                <circle cx={x(r.nasaExpires)} cy={y} r={2.1} style={{ fill: "var(--faint)" }} />
                <circle cx={x(r.lapse)} cy={y} r={2.4} style={{ fill: "var(--nogo)" }} />
              </g>
            );
          })}
        </svg>
      </div>
      {hover ? (
        <div className="tooltip" style={{ left: "50%", top: 74, transform: "translate(-50%, 0)" }}>
          {hover.key}: lapsed {hover.lapse}, shown alive until {hover.nasaExpires} ({hover.phantomYears} years)
        </div>
      ) : null}
    </div>
  );
}

export default function Findings() {
  const { data, error } = useJson<FindingsData>("findings.json");

  const lapsedSorted = useMemo(
    () => [...(data?.legalStatus.lapsed ?? [])].sort((a, b) => a.lapse.localeCompare(b.lapse)),
    [data],
  );

  if (error) return <Failed error={error} />;
  if (!data) return <Loading what="the findings" />;

  const ls = data.legalStatus;
  const lapsed = ls.states.lapsed ?? 0;
  const pct = Math.round((lapsed / ls.nasaCallsInForce) * 100);
  const stateOrder = ["lapsed", "in_force", "abandoned", "term_ended"].filter((k) => k in ls.states);

  const doughnut = (c: ChartColors) => ({
    type: "doughnut" as const,
    data: {
      labels: stateOrder.map((k) => `${STATE_LABEL[k]} (${ls.states[k]})`),
      datasets: [{ data: stateOrder.map((k) => ls.states[k]), backgroundColor: [c.nogo, c.go, c.nodata, c.amber], borderColor: c.surface, borderWidth: 3 }],
    },
    options: {
      maintainAspectRatio: false,
      cutout: "64%",
      plugins: { legend: { position: "bottom" as const, labels: { usePointStyle: true, padding: 16 } } },
    },
    plugins: [
      {
        id: "center-label",
        afterDraw(chart: { ctx: CanvasRenderingContext2D; chartArea: { left: number; right: number; top: number; bottom: number } }) {
          const { ctx, chartArea } = chart;
          const cx = (chartArea.left + chartArea.right) / 2;
          const cy = (chartArea.top + chartArea.bottom) / 2;
          ctx.save();
          ctx.textAlign = "center";
          ctx.fillStyle = c.ink;
          ctx.font = '700 38px "Inter Variable", system-ui, sans-serif';
          ctx.fillText(`${pct}%`, cx, cy + 6);
          ctx.fillStyle = c.muted;
          ctx.font = '500 13px "Inter Variable", system-ui, sans-serif';
          ctx.fillText("lapsed", cx, cy + 28);
          ctx.restore();
        },
      },
    ],
  });

  const matchChart = (c: ChartColors) => ({
    type: "bar" as const,
    data: {
      labels: ["NASA Patents snapshot alone", "Snapshot plus NASA T2 portal"],
      datasets: [{ data: [data.noticeMatch.datasetOnly, data.noticeMatch.withT2], backgroundColor: [c.nodata, c.accent], borderRadius: 8, barThickness: 44 }],
    },
    options: {
      indexAxis: "y" as const,
      maintainAspectRatio: false,
      plugins: { legend: { display: false }, tooltip: { callbacks: { label: (i: { parsed: { x: number | null } }) => `${i.parsed.x} of ${data.noticeMatch.total} notices` } } },
      scales: { x: { max: data.noticeMatch.total, grid: { color: c.line }, title: { display: true, text: `Notices that name a known patent (of ${data.noticeMatch.total})` } }, y: { grid: { display: false } } },
    },
  });

  const e = data.extraction;
  const extractionChart = (c: ChartColors) => ({
    type: "bar" as const,
    data: {
      labels: ["Licensee", "Territory", "Objection deadline", "Exclusivity type chosen", "Field of use stated"],
      datasets: [{ data: [e.licensee, e.territory, e.deadline, e.specificExclusivity, e.fieldStated], backgroundColor: [c.accent, c.accent, c.accent, c.amber, c.nogo], borderRadius: 8 }],
    },
    options: {
      indexAxis: "y" as const,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: { x: { max: e.total, grid: { color: c.line }, title: { display: true, text: `Notices that state it (of ${e.total})` } }, y: { grid: { display: false } } },
    },
  });

  const classes = Object.keys(data.factsByClass);
  const factsChart = (c: ChartColors) => ({
    type: "bar" as const,
    data: {
      labels: classes,
      datasets: [
        { label: "Real", data: classes.map((k) => data.factsByClass[k].real), backgroundColor: c.go, borderRadius: 4 },
        { label: "Synthetic, labeled", data: classes.map((k) => data.factsByClass[k].synthetic), backgroundColor: c.counsel, borderRadius: 4 },
      ],
    },
    options: {
      indexAxis: "y" as const,
      maintainAspectRatio: false,
      plugins: { legend: { position: "bottom" as const, labels: { usePointStyle: true } } },
      scales: { x: { stacked: true, grid: { color: c.line } }, y: { stacked: true, grid: { display: false } } },
    },
  });

  const a = data.applications;
  const appPct = Math.round((a.nowGranted / a.listedAsApplication) * 100);

  return (
    <>
      <div className="page-head">
        <div className="eyebrow">What the real data showed</div>
        <h1>Public data is older than it looks</h1>
        <p className="lede">
          GoNoGo reads four public sources and the USPTO. Comparing them showed where a rule that trusts one source
          would give a wrong answer. These charts come from the same data files that the tests check.
        </p>
      </div>

      <section>
        <div className="grid cols-3" style={{ alignItems: "stretch" }}>
          <Stat value={`${pct}%`} label="of patents that the NASA snapshot calls in force have lapsed" note={`${lapsed} of ${ls.nasaCallsInForce}, according to USPTO maintenance-fee records`} />
          <Stat value={`${ls.phantomYearsMedian} years`} label="median gap between the lapse and the date the snapshot still shows" note="the years in which a naive rule would pass R1" />
          <Stat value={`${a.nowGranted} of ${a.listedAsApplication}`} label="applications in the snapshot have since been granted" note={`${appPct}% — the snapshot is about ten years old`} />
        </div>
      </section>

      <section className="section">
        <h2>Which patents are really alive</h2>
        <p className="muted">
          Rule R1 asks whether a patent is in force. The NASA Patents snapshot lists an expiration date for each patent,
          but a patent also dies early when its owner skips a maintenance fee. Only the USPTO records that.
        </p>
        <div className="grid cols-2">
          <div className="card">
            <h3>What USPTO shows for the {ls.nasaCallsInForce} patents the snapshot calls alive</h3>
            <ChartCanvas label="Doughnut chart of USPTO legal states for patents that the NASA snapshot calls in force" build={doughnut} height={340} />
          </div>
          <div className="card" style={{ display: "grid", gap: 12, alignContent: "start" }}>
            <h3>Why this matters</h3>
            <p>
              A system that trusted the snapshot would return GO on a patent that died years ago. GoNoGo keeps both
              registries as separate facts, prefers the USPTO fact, and falls back to the snapshot only when the USPTO has
              no record.
            </p>
            <div className="callout warn">
              The first patent checked, US 8,077,103, has a USPTO expiry recorded in January 2020. The snapshot lists it as in force until July 2027.
            </div>
            <p className="muted" style={{ fontSize: 14 }}>
              The gap is the finding. It is also why the model keeps one status fact per source (modeling decision MD10).
            </p>
          </div>
        </div>
      </section>

      <section className="section">
        <h2>The years that don't exist</h2>
        <p className="muted">
          Each line is one lapsed patent. It starts where the USPTO recorded the lapse and ends where the snapshot
          says the patent expires. Scroll to see all {lapsedSorted.length}.
        </p>
        <Dumbbell rows={lapsedSorted} median={ls.phantomYearsMedian} />
      </section>

      <section className="section">
        <h2>Matching notices to patents</h2>
        <p className="muted">
          The Federal Register has {data.noticeMatch.total} NASA license notices since 2018. Most cite patents newer than
          the public patent snapshot, so the snapshot alone matches only a third of them. The NASA Technology Transfer
          portal closes part of the gap.
        </p>
        <div className="card">
          <ChartCanvas label="Bar chart of notices that match a known patent, with and without the T2 portal" build={matchChart} height={190} />
        </div>
      </section>

      <section className="section">
        <h2>What a notice actually says</h2>
        <p className="muted">
          Notices name a licensee, a territory, and a deadline almost every time. They rarely choose an exclusivity type
          (since 2021 most offer all three) and rarely state a field of use. GoNoGo records that absence explicitly
          instead of guessing, so a rule can return NO DATA.
        </p>
        <div className="card">
          <ChartCanvas label="Bar chart of how many notices state each field" build={extractionChart} height={300} />
        </div>
      </section>

      <section className="section">
        <h2>Real facts and synthetic facts</h2>
        <p className="muted">
          Nobody publishes signed licenses, ownership records, consents, or export classifications, so a seeded
          generator creates them. Every synthetic fact carries a link to the generator run, and the shapes reject a fact
          that has no origin.
        </p>
        <div className="card">
          <ChartCanvas label="Stacked bar chart of real and synthetic facts by class" build={factsChart} height={340} />
        </div>
      </section>
    </>
  );
}
