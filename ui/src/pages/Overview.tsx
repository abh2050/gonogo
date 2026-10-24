import Stat from "../components/Stat";
import { Failed, Loading } from "../components/Loading";
import { useJson, type Findings } from "../data";

const VERDICTS = [
  { cls: "go", name: "GO", text: "Every rule passed, and every fact the rules needed was on record." },
  { cls: "nogo", name: "NO GO", text: "A rule found a conflict, such as an overlapping exclusive license." },
  { cls: "hold", name: "HOLD", text: "A Federal Register objection window is still open." },
  { cls: "counsel", name: "COUNSEL", text: "A rule needs legal judgment, as every exclusive license does." },
  { cls: "nodata", name: "NO DATA", text: "A needed fact is missing. The system will not treat a gap as proof." },
];

const RULES = [
  ["R1", "Patent in force", "Is the patent alive on the start date, according to the registries?"],
  ["R2", "Overlapping grants", "Does a signed or proposed license overlap the field, territory, and term?"],
  ["R3", "Co-exclusive cap", "Would the request exceed the number of co-exclusive licensees?"],
  ["R4", "Notice window", "Has the Federal Register objection window closed?"],
  ["R5", "Export control", "May the licensee's country receive this technology?"],
  ["R6", "Co-owner consent", "Has every co-owner consented to the license?"],
  ["R7", "Statutory review", "Do 35 U.S.C. 209 conditions need counsel's judgment?"],
];

function FlowDiagram() {
  const box = (x: number, y: number, w: number, h: number, title: string, sub: string, kind: "rule" | "llm" | "plain") => (
    <g key={title}>
      <rect
        x={x}
        y={y}
        width={w}
        height={h}
        rx={14}
        fill={kind === "rule" ? "var(--accent-soft)" : "var(--surface)"}
        stroke={kind === "rule" ? "var(--accent)" : "var(--line-strong)"}
        strokeWidth={kind === "rule" ? 2 : 1.5}
        strokeDasharray={kind === "llm" ? "6 5" : undefined}
      />
      <text x={x + w / 2} y={y + h / 2 - 4} textAnchor="middle" fontSize="16" fontWeight="650" fill="var(--ink)">
        {title}
      </text>
      <text x={x + w / 2} y={y + h / 2 + 16} textAnchor="middle" fontSize="12.5" fill="var(--muted)">
        {sub}
      </text>
    </g>
  );
  const arrow = (x1: number, x2: number, y: number) => (
    <g key={`${x1}-${x2}`}>
      <line x1={x1} y1={y} x2={x2 - 6} y2={y} stroke="var(--faint)" strokeWidth="2" />
      <path d={`M${x2 - 10},${y - 5} L${x2},${y} L${x2 - 10},${y + 5}`} fill="none" stroke="var(--faint)" strokeWidth="2" />
    </g>
  );
  return (
    <svg viewBox="0 0 1120 250" role="img" aria-label="Request flows to a language model that parses it, then to seven rules that query the knowledge graph, then to the combiner, then to a verdict, which a language model explains.">
      {box(10, 40, 150, 84, "Request", "plain language", "plain")}
      {arrow(160, 195, 82)}
      {box(195, 40, 160, 84, "Parse", "language model", "llm")}
      {arrow(355, 390, 82)}
      {box(390, 24, 220, 116, "Seven rules", "R1 to R7 · SPARQL templates", "rule")}
      {arrow(610, 645, 82)}
      {box(645, 40, 170, 84, "Combiner", "versioned precedence", "rule")}
      {arrow(815, 850, 82)}
      {box(850, 40, 120, 84, "Verdict", "one of five", "plain")}
      {arrow(970, 995, 82)}
      {box(995, 40, 115, 84, "Explain", "language model", "llm")}
      <g>
        <path d="M500,140 v26 M500,166 h-40" stroke="var(--faint)" strokeWidth="2" fill="none" />
        <ellipse cx="400" cy="184" rx="60" ry="14" fill="var(--surface)" stroke="var(--line-strong)" strokeWidth="1.5" />
        <path d="M340,184 v34 a60,14 0 0 0 120,0 v-34" fill="var(--surface)" stroke="var(--line-strong)" strokeWidth="1.5" />
        <text x="400" y="213" textAnchor="middle" fontSize="13" fontWeight="650" fill="var(--ink)">Knowledge graph</text>
        <text x="500" y="196" fontSize="12.5" fill="var(--muted)">facts, time, provenance</text>
      </g>
      <g fontSize="12.5" fill="var(--muted)">
        <rect x="660" y="170" width="26" height="14" rx="4" fill="var(--accent-soft)" stroke="var(--accent)" strokeWidth="2" />
        <text x="696" y="182">deterministic: same input, same output</text>
        <rect x="660" y="196" width="26" height="14" rx="4" fill="var(--surface)" stroke="var(--line-strong)" strokeWidth="1.5" strokeDasharray="4 3" />
        <text x="696" y="208">language model: helps with words, never decides, never writes a query</text>
      </g>
    </svg>
  );
}

export default function Overview() {
  const { data, error } = useJson<Findings>("findings.json");
  return (
    <>
      <div className="page-head">
        <div className="eyebrow">Patent license clearance for NASA technology transfer</div>
        <h1>Rules decide. The language model only helps.</h1>
        <p className="lede">
          A licensing manager asks whether a company can license a NASA patent for a field, a territory, and a term.
          GoNoGo checks seven rules against a knowledge graph and answers with one of five verdicts. Every answer
          shows the rule that fired, the evidence, and the words in the source document.
        </p>
      </div>

      <div className="verdict-list" role="list" aria-label="The five verdicts">
        {VERDICTS.map((v) => (
          <div className="verdict-card" role="listitem" key={v.name}>
            <span className={`chip ${v.cls}`}>{v.name}</span>
            <p>{v.text}</p>
          </div>
        ))}
      </div>

      <section className="section">
        <h2>How a verdict is made</h2>
        <p className="muted">
          A language model turns the question into a structured request and, at the end, writes the explanation. In
          between, reviewed query templates read the graph. The same facts always produce the same verdict, and every
          past verdict reruns from its stored context.
        </p>
        <div className="viz" style={{ padding: 16, overflowX: "auto" }}>
          <div style={{ minWidth: 760 }}>
            <FlowDiagram />
          </div>
        </div>
      </section>

      <section className="section">
        <h2>The seven rules</h2>
        <div className="grid cols-4" style={{ marginTop: 16 }}>
          {RULES.map(([id, name, text]) => (
            <div className="card" key={id}>
              <span className="tag rule">{id}</span>
              <h3>{name}</h3>
              <p className="muted" style={{ fontSize: 14 }}>{text}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="section">
        <h2>The data behind it</h2>
        <p className="muted">
          Real public records from NASA, the Federal Register, and the USPTO, plus synthetic agreements for the facts
          that nobody publishes. Each synthetic fact carries a label in the graph.
        </p>
        {error ? <Failed error={error} /> : null}
        {!data && !error ? <Loading what="data" /> : null}
        {data ? (
          <div className="grid cols-4">
            <Stat value={data.scope.patents} label="patents in scope" note="Langley, Glenn, and Kennedy" />
            <Stat value={data.scope.notices} label="real license notices" note={`of ${data.noticeMatch.total} since 2018`} />
            <Stat
              value={`${data.legalStatus.states.lapsed ?? 0} of ${data.legalStatus.nasaCallsInForce}`}
              label="patents shown alive that have lapsed"
              note="NASA snapshot versus USPTO"
            />
            <Stat value={data.synthetic.injectedCases} label="hand-labeled test cases" note="every verdict is covered" />
          </div>
        ) : null}
      </section>

      <section className="section">
        <h2>Explore</h2>
        <div className="grid cols-2" style={{ marginTop: 16 }}>
          {[
            ["#/ontology", "The ontology", "42 classes drawn as a graph. Click a class to see its definition, the rules that read it, and the decisions behind it."],
            ["#/vocabularies", "The vocabularies", "Fields of use and territories as hierarchies. Choose a grant and a request and watch rights coverage follow the hierarchy."],
            ["#/findings", "Data findings", "What the real data showed, including the patents that a public dataset shows alive after the USPTO recorded them lapsed."],
            ["#/time", "Time", "The bitemporal model. Move a recording cutoff and watch the system's belief change, then see why past decisions reproduce."],
          ].map(([href, title, text]) => (
            <a key={href} href={href} className="card" style={{ textDecoration: "none", color: "inherit" }}>
              <h3>{title} →</h3>
              <p className="muted">{text}</p>
            </a>
          ))}
        </div>
      </section>
    </>
  );
}
