import * as d3 from "d3";
import { useEffect, useMemo, useRef, useState } from "react";
import ChartCanvas, { type ChartColors } from "../components/ChartCanvas";
import { Failed, Loading } from "../components/Loading";
import Stat from "../components/Stat";
import { useJson } from "../data";

interface Answerer {
  questions: number;
  accuracy: number | null;
  false_go: string[];
  false_go_rate: number | null;
  missed_go_rate: number | null;
  citation_precision: number | null;
  decisive_recall: number | null;
  cases: number;
  case_accuracy: number | null;
  accuracy_by_style: Record<string, number | null>;
  accuracy_by_family: Record<string, [number, number]>;
  errors: number;
  latency_p50_s: number | null;
  latency_p95_s: number | null;
  model_calls: number;
  tokens_in: number;
  tokens_out: number;
  model_cost_usd: number;
  confusion: Record<string, number>;
}

interface BenchmarkData {
  answerers: Record<string, Answerer>;
  golden: { questions: number; cases: number; verdicts: Record<string, number> };
  pgraph: {
    requests: number;
    with_a_conflict: number;
    agree: number;
    median_ms: { sparql_rdflib: number; cypher_neo4j: number };
    query_lines: { sparql: number; cypher: number };
  } | null;
}

const NAMES: Record<string, { short: string; long: string; how: string }> = {
  A: { short: "A. Vector RAG", long: "Vector search, then a model reads the passages", how: "Retrieves the 12 closest passages from the document corpus and asks a model for the verdict. Nothing checks its reasoning." },
  B: { short: "B. Graph agent", long: "A model with graph tools", how: "A Strands agent looks up records through the rules' own SPARQL templates, then applies the policy itself." },
  C: { short: "C. Rules only", long: "Fixed parser and the seven rules", how: "No model. The fixed-pattern parser reads the question and the rules decide. It refuses what it cannot parse." },
  "C+": { short: "C+. Rules with a model reader", long: "GoNoGo as deployed", how: "A model only reads the question into a form. Every value must name a concept the graph holds, and the rules decide." },
};
const ORDER = ["A", "B", "C", "C+"];
const VERDICTS = ["GO", "NO GO", "HOLD", "COUNSEL", "NO DATA", "NEEDS INFO", "ERROR"];

/** One color per answerer, so a bar means the same answerer on every chart. */
function paint(c: ChartColors, k: string): string {
  return { A: c.nodata, B: c.hold, C: c.counsel, "C+": c.go }[k] ?? c.accent;
}

function pct(v: number | null): string {
  return v === null ? "n/a" : `${v}%`;
}

function Confusion({ data, id }: { data: Answerer; id: string }) {
  const ref = useRef<SVGSVGElement>(null);
  useEffect(() => {
    const svg = d3.select(ref.current);
    svg.selectAll("*").remove();
    const cell = 62;
    const left = 92;
    const top = 70;
    const rows = VERDICTS.slice(0, 6);
    const cols = VERDICTS;
    const get = (e: string, g: string) => data.confusion[`${e} -> ${g}`] ?? 0;
    const max = Math.max(1, ...rows.flatMap((r) => cols.map((c) => get(r, c))));
    const color = d3.scaleSqrt<string>().domain([0, max]).range(["transparent", "#3b6df0"]);
    svg.attr("viewBox", `0 0 ${left + cols.length * cell + 10} ${top + rows.length * cell + 30}`);
    svg
      .append("text")
      .attr("x", left)
      .attr("y", 18)
      .attr("class", "conf-axis")
      .text("What the answerer said");
    svg
      .append("text")
      .attr("transform", `translate(14, ${top + (rows.length * cell) / 2}) rotate(-90)`)
      .attr("text-anchor", "middle")
      .attr("class", "conf-axis")
      .text("What was right");
    cols.forEach((c, i) =>
      svg.append("text").attr("x", left + i * cell + cell / 2).attr("y", top - 10).attr("text-anchor", "middle").attr("class", "conf-label").text(c === "NEEDS INFO" ? "NEEDS\u00a0INFO" : c).style("font-size", "10px"),
    );
    rows.forEach((r, j) => {
      svg.append("text").attr("x", left - 8).attr("y", top + j * cell + cell / 2 + 4).attr("text-anchor", "end").attr("class", "conf-label").text(r);
      cols.forEach((c, i) => {
        const n = get(r, c);
        const wrong = r !== c;
        const g = svg.append("g").attr("transform", `translate(${left + i * cell}, ${top + j * cell})`);
        g.append("rect")
          .attr("width", cell - 3)
          .attr("height", cell - 3)
          .attr("rx", 6)
          .attr("fill", n ? (wrong ? (c === "GO" ? "var(--nogo)" : "var(--hold)") : color(n)) : "var(--surface-2, transparent)")
          .attr("fill-opacity", n ? (wrong ? Math.min(1, 0.35 + 0.65 * (n / max)) : 0.95) : 1)
          .attr("stroke", c === "GO" && wrong && n ? "var(--nogo)" : "var(--line)");
        if (n)
          g.append("text")
            .attr("x", (cell - 3) / 2)
            .attr("y", (cell - 3) / 2 + 5)
            .attr("text-anchor", "middle")
            .attr("class", "conf-num")
            .text(n);
        g.append("title").text(`${n} questions: right answer ${r}, said ${c}`);
      });
    });
  }, [data, id]);
  return <svg ref={ref} className="confusion" role="img" aria-label="Right answers against the answers given, by verdict" />;
}

export default function Benchmark() {
  const { data, error } = useJson<BenchmarkData>("benchmark.json");
  const [pick, setPick] = useState("C+");
  const names = useMemo(() => ORDER.filter((k) => data && k in data.answerers), [data]);

  if (error) return <Failed error={error} />;
  if (!data) return <Loading what="the benchmark" />;
  const a = data.answerers;
  const g = data.golden;
  const best = a["C+"] ?? a["C"];
  const families = Object.keys(best?.accuracy_by_family ?? {});

  const accuracy = (c: ChartColors) => ({
    type: "bar" as const,
    data: {
      labels: names.map((k) => NAMES[k].short),
      datasets: [
        { label: "Right verdict", data: names.map((k) => a[k].accuracy), backgroundColor: c.accent, borderRadius: 6 },
        { label: "Cited the right records", data: names.map((k) => a[k].citation_precision), backgroundColor: c.amber, borderRadius: 6 },
      ],
    },
    options: {
      maintainAspectRatio: false,
      plugins: { legend: { position: "bottom" as const, labels: { usePointStyle: true } } },
      scales: { y: { max: 100, grid: { color: c.line }, title: { display: true, text: "Percent" } }, x: { grid: { display: false } } },
    },
  });

  const falseGo = (c: ChartColors) => ({
    type: "bar" as const,
    data: {
      labels: names.map((k) => NAMES[k].short),
      datasets: [{ label: "False GO", data: names.map((k) => a[k].false_go.length), backgroundColor: names.map((k) => (a[k].false_go.length ? c.nogo : c.go)), borderRadius: 6, minBarLength: 3 }],
    },
    options: {
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: { y: { beginAtZero: true, ticks: { precision: 0 }, grid: { color: c.line }, title: { display: true, text: "Questions" } }, x: { grid: { display: false } } },
    },
  });

  const byFamily = (c: ChartColors) => ({
    type: "bar" as const,
    data: {
      labels: families,
      datasets: names.map((k) => ({
        label: NAMES[k].short,
        data: families.map((f) => {
          const [ok, n] = a[k].accuracy_by_family[f] ?? [0, 0];
          return n ? Math.round((100 * ok) / n) : null;
        }),
        backgroundColor: paint(c, k),
        borderRadius: 4,
      })),
    },
    options: {
      indexAxis: "y" as const,
      maintainAspectRatio: false,
      plugins: { legend: { position: "bottom" as const, labels: { usePointStyle: true } } },
      scales: { x: { max: 100, grid: { color: c.line }, title: { display: true, text: "Percent right" } }, y: { grid: { display: false } } },
    },
  });

  const wording = (c: ChartColors) => ({
    type: "bar" as const,
    data: {
      labels: ["formal", "casual", "terse", "noisy", "unanswerable"],
      datasets: names.map((k) => ({
        label: NAMES[k].short,
        data: ["formal", "casual", "terse", "noisy", "unanswerable"].map((s) => a[k].accuracy_by_style[s] ?? null),
        backgroundColor: paint(c, k),
        borderRadius: 4,
      })),
    },
    options: {
      maintainAspectRatio: false,
      plugins: { legend: { position: "bottom" as const, labels: { usePointStyle: true } } },
      scales: { y: { max: 100, grid: { color: c.line }, title: { display: true, text: "Percent right" } }, x: { grid: { display: false } } },
    },
  });

  const cost = (c: ChartColors) => ({
    type: "bar" as const,
    data: {
      labels: names.map((k) => NAMES[k].short),
      datasets: [{ label: "Median seconds per answer", data: names.map((k) => a[k].latency_p50_s), backgroundColor: c.accent, borderRadius: 6 }],
    },
    options: {
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: { y: { type: "logarithmic" as const, grid: { color: c.line }, title: { display: true, text: "Seconds, log scale" } }, x: { grid: { display: false } } },
    },
  });

  const p = data.pgraph;
  return (
    <>
      <div className="page-head">
        <div className="eyebrow">Does the ontology earn its place?</div>
        <h1>Benchmark: rules over a graph, against a model alone</h1>
        <p className="lede">
          The same {g.questions} questions went to four answerers. Each question is one of {g.cases} planted cases, worded four ways, or a question that
          cannot be answered as asked. The right answer for each was decided by hand when the case was planted, never by the rule engine.
        </p>
      </div>

      <section>
        <div className="grid cols-3" style={{ alignItems: "stretch" }}>
          <Stat value={pct(best.accuracy)} label="GoNoGo's accuracy" note={`${best.false_go.length} false GO in ${g.questions} questions`} />
          <Stat value={a["A"] ? pct(a["A"].accuracy) : "n/a"} label="Vector RAG accuracy" note={a["A"] ? `${a["A"].false_go.length} false GO` : undefined} />
          <Stat value={a["B"] ? pct(a["B"].accuracy) : "n/a"} label="Graph agent accuracy" note={a["B"] ? `${a["B"].false_go.length} false GO` : undefined} />
        </div>
      </section>

      <section className="section">
        <h2>Verdict accuracy and citations</h2>
        <p className="muted">
          A verdict counts only when it matches exactly. A citation counts when it names a record about the question's patent or one planted for its case.
        </p>
        <div className="card">
          <ChartCanvas build={accuracy} label="Verdict accuracy and citation precision for each answerer" />
        </div>
      </section>

      <section className="section">
        <h2>The failure that matters: a false GO</h2>
        <p className="muted">
          A false GO clears a license that should not be granted. It is the one error with a legal cost, so the build fails if the rule pipeline makes one.
        </p>
        <div className="grid cols-2">
          <div className="card">
            <ChartCanvas build={falseGo} label="Questions answered GO when they should not have been" height={280} />
          </div>
          <div className="card" style={{ display: "grid", gap: 10, alignContent: "start" }}>
            {names.map((k) => (
              <div key={k}>
                <strong>{NAMES[k].short}.</strong> {a[k].false_go.length ? `${a[k].false_go.length} false GO (${pct(a[k].false_go_rate)} of the questions that are not GO).` : "No false GO."}{" "}
                <span className="muted">Missed GO: {pct(a[k].missed_go_rate)}.</span>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="section">
        <h2>Where each one goes wrong</h2>
        <p className="muted">Right answers by what the question tests. Each bar is the share of that family's questions answered exactly right.</p>
        <div className="card">
          <ChartCanvas build={byFamily} label="Accuracy by question family and answerer" height={520} />
        </div>
      </section>

      <section className="section">
        <h2>Right answer against given answer</h2>
        <p className="muted">
          Each row is the correct verdict, and each column is what the answerer said. The diagonal is right. Red in the GO column is a false GO.
        </p>
        <div className="viz-toolbar">
          <div className="legend">
            {names.map((k) => (
              <button key={k} className="legend-item" aria-pressed={pick === k} onClick={() => setPick(k)}>
                {NAMES[k].short}
              </button>
            ))}
          </div>
        </div>
        <div className="card">
          <p className="muted" style={{ marginTop: 0 }}>{NAMES[pick].how}</p>
          <Confusion data={a[pick]} id={pick} />
        </div>
      </section>

      <section className="section">
        <h2>Does the wording matter?</h2>
        <p className="muted">
          Every case was asked formally, casually, as a terse note, and with irrelevant detail around it. The fixed parser reads only the formal wording. Letting a model read the question
          fixes that without letting it decide.
        </p>
        <div className="card">
          <ChartCanvas build={wording} label="Accuracy by wording and answerer" />
        </div>
      </section>

      <section className="section">
        <h2>Speed and cost</h2>
        <div className="grid cols-2">
          <div className="card">
            <ChartCanvas build={cost} label="Median seconds per answer for each answerer" height={280} />
          </div>
          <div className="card" style={{ display: "grid", gap: 8, alignContent: "start" }}>
            {names.map((k) => (
              <div key={k}>
                <strong>{NAMES[k].short}.</strong> {a[k].model_calls} model calls, {a[k].tokens_in.toLocaleString()} tokens in,{" "}
                {a[k].tokens_out.toLocaleString()} out, about ${a[k].model_cost_usd.toFixed(2)} for {a[k].questions} questions.
              </div>
            ))}
            <p className="muted" style={{ fontSize: 14 }}>Priced at Claude Haiku 4.5 on-demand rates. Retrieval and agent hosting are not included.</p>
          </div>
        </div>
      </section>

      {p ? (
        <section className="section">
          <h2>The same rule in a property graph</h2>
          <p className="muted">
            Rule R2 was written in SPARQL over RDF and in Cypher over Neo4j, and both ran on {p.requests.toLocaleString()} requests ({p.with_a_conflict} with a conflicting grant).
            They returned the same grants for {p.agree.toLocaleString()} of them. See ADR 0003 for why RDF stays the system of record.
          </p>
          <div className="grid cols-3" style={{ alignItems: "stretch" }}>
            <Stat value={`${p.agree.toLocaleString()} of ${p.requests.toLocaleString()}`} label="Same grants returned" />
            <Stat value={`${p.query_lines.sparql} and ${p.query_lines.cypher}`} label="Lines of SPARQL and Cypher" />
            <Stat value={`${p.median_ms.sparql_rdflib} and ${p.median_ms.cypher_neo4j} ms`} label="Median time, rdflib and Neo4j" />
          </div>
        </section>
      ) : null}
    </>
  );
}
