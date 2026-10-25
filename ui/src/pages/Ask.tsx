import { useEffect, useMemo, useState } from "react";
import { api, VERDICT_CLASS, type Decision, type Diff, type Example, type Parse, type Vocabulary } from "../api";
import ProvenanceGraph from "../components/ProvenanceGraph";
import VerdictCard from "../components/VerdictCard";
import { useSession } from "../session";

const PART_LABEL: Record<string, string> = {
  licensee: "Licensee",
  patent_key: "Patent",
  exclusivity: "License type",
  field: "Field of use",
  territory: "Territory",
  start: "Start",
  end: "End",
};

/** The question with every part the parser read underlined, so a reader sees exactly what was understood. */
function ParsedText({ parse }: { parse: Parse }) {
  const spans = Object.entries(parse.found)
    .filter(([, f]) => f && f.span[0] >= 0 && f.how !== "computed")
    .map(([k, f]) => ({ k, s: f!.span[0], e: f!.span[1] }))
    .sort((a, b) => a.s - b.s);
  const out: React.ReactNode[] = [];
  let at = 0;
  for (const sp of spans) {
    if (sp.s < at) continue;
    out.push(parse.text.slice(at, sp.s));
    out.push(
      <mark key={sp.k} className={`part part-${sp.k}`} title={PART_LABEL[sp.k]}>
        {parse.text.slice(sp.s, sp.e)}
        <span className="part-tag">{PART_LABEL[sp.k]}</span>
      </mark>,
    );
    at = sp.e;
  }
  out.push(parse.text.slice(at));
  return <p className="parsed">{out}</p>;
}

function ParsePanel({ parse }: { parse: Parse }) {
  return (
    <section className="card parse-panel">
      <div className="eyebrow">What the parser read · {parse.parser}</div>
      <ParsedText parse={parse} />
      <table className="parse-table">
        <tbody>
          {Object.keys(PART_LABEL).map((k) => {
            const f = parse.found[k as keyof Parse["found"]];
            return (
              <tr key={k} className={f ? "" : "missing"}>
                <th>{PART_LABEL[k]}</th>
                <td>
                  {f ? (
                    <>
                      <code>{f.value}</code>
                      {f.label && f.label !== f.value ? <span className="muted"> · {f.label}</span> : null}
                      {f.how === "computed" ? <span className="tag">computed from “{f.text}”</span> : null}
                    </>
                  ) : (
                    <span className="missing-text">not stated, so not guessed</span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {parse.licensee ? (
        <div className="licensee-res">
          <strong>Entity resolution: {parse.licensee.status}</strong>
          {parse.licensee.candidates.length ? (
            <ul>
              {parse.licensee.candidates.map((c) => (
                <li key={c.iri}>
                  {c.name} <span className="mono faint">score {c.score.toFixed(2)}</span> <span className="muted small">{c.why}</span>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
      {parse.notes.map((n) => (
        <p key={n} className="callout warn small">
          {n}
        </p>
      ))}
    </section>
  );
}

function StructuredForm({ vocab, initial, onSubmit, busy }: { vocab: Vocabulary; initial: Parse | null; onSubmit: (r: Record<string, unknown>) => void; busy: boolean }) {
  const f = initial?.found ?? {};
  const [form, setForm] = useState({
    patent_key: f.patent_key?.value ?? "",
    exclusivity: f.exclusivity?.value ?? "non-exclusive",
    field: f.field?.value ?? "",
    territory: f.territory?.value ?? "US",
    start: f.start?.value ?? "2027-01-01",
    end: f.end?.value ?? "2031-12-31",
    licensee_name: f.licensee?.value ?? "",
  });
  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setForm({ ...form, [k]: e.target.value });
  const byBroader = (list: Vocabulary["fields"]) => {
    const tops = list.filter((c) => !c.broader || !list.some((p) => p.id === c.broader));
    return tops.map((t) => ({ top: t, kids: list.filter((c) => c.broader === t.id) }));
  };
  return (
    <form
      className="card form-grid"
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit({ ...form, licensee_ids: initial?.licensee?.ids ?? [], licensee_country: initial?.licensee?.country ?? null });
      }}
    >
      <div className="eyebrow span-all">Or fill the request in directly. Every choice is a concept from a GoNoGo scheme.</div>
      <label>
        Patent (NASA case or US number key)
        <input value={form.patent_key} onChange={set("patent_key")} placeholder="LEW-17915-1" required />
      </label>
      <label>
        License type
        <select value={form.exclusivity} onChange={set("exclusivity")}>
          {vocab.exclusivity.map((x) => (
            <option key={x} value={x}>
              {x.replace(/-/g, " ")}
            </option>
          ))}
        </select>
      </label>
      <label>
        Field of use
        <select value={form.field} onChange={set("field")} required>
          <option value="">Choose a field</option>
          {byBroader(vocab.fields).map(({ top, kids }) => (
            <optgroup key={top.id} label={top.label}>
              <option value={top.id}>{top.label} (all)</option>
              {kids.map((k) => (
                <option key={k.id} value={k.id}>
                  {k.label}
                </option>
              ))}
            </optgroup>
          ))}
        </select>
      </label>
      <label>
        Territory
        <select value={form.territory} onChange={set("territory")}>
          {vocab.territories.map((t) => (
            <option key={t.id} value={t.id}>
              {t.broader ? "  " : ""}
              {t.label}
            </option>
          ))}
        </select>
      </label>
      <label>
        Start
        <input type="date" value={form.start} onChange={set("start")} required />
      </label>
      <label>
        End
        <input type="date" value={form.end} onChange={set("end")} required />
      </label>
      <label className="span-2">
        Licensee name (optional)
        <input value={form.licensee_name} onChange={set("licensee_name")} />
      </label>
      <button className="button primary" disabled={busy}>
        Decide
      </button>
    </form>
  );
}

export default function Ask() {
  const { events, record, history } = useSession();
  const [examples, setExamples] = useState<Example[]>([]);
  const [vocab, setVocab] = useState<Vocabulary | null>(null);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [parse, setParse] = useState<Parse | null>(null);
  const [decision, setDecision] = useState<Decision | null>(history[0]?.decision ?? null);
  const [diff, setDiff] = useState<Diff | undefined>(history[0]?.diff);
  const [fact, setFact] = useState<string | null>(null);
  const [rerun, setRerun] = useState<{ ok: boolean; verdict: string } | null>(null);
  const [online, setOnline] = useState<boolean | null>(null);

  useEffect(() => {
    api.examples().then(setExamples).then(() => setOnline(true)).catch(() => setOnline(false));
    api.vocabulary().then(setVocab).catch(() => undefined);
  }, []);

  const exampleLabel = useMemo(() => new Map(examples.map((e) => [e.text, e.title])), [examples]);

  async function ask(input: { text?: string; request?: Record<string, unknown> }) {
    setBusy(true);
    setError(null);
    setRerun(null);
    setFact(null);
    setDecision(null);
    setParse(null);
    try {
      const out = await api.decide(events, input);
      setParse(out.parse);
      setDecision(out.decision);
      setDiff(undefined);
      if (out.decision) {
        const label = input.text ? (exampleLabel.get(input.text) ?? input.text.slice(0, 70)) : `${out.decision.request.patent_key} · ${out.decision.request.field}`;
        record({ decision: out.decision, label });
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function reproduce() {
    if (!decision) return;
    const out = await api.rerun(events, decision);
    setRerun({ ok: out.reproduced, verdict: out.decision.verdict });
  }

  return (
    <div className="page">
      <header className="page-head">
        <div className="eyebrow">Ask</div>
        <h1>Can this company license this patent?</h1>
        <p className="lede">
          Ask in your own words or pick an example. GoNoGo reads the question with fixed patterns, not a language
          model, and underlines what it understood. Seven rules then query the knowledge graph, and the verdict
          shows which rule decided and the evidence it read.
        </p>
      </header>
      {online === false ? (
        <p className="callout warn">
          The API is not reachable. Locally, run <code>uv run uvicorn api.index:app</code> beside <code>npm run dev</code>.
        </p>
      ) : null}

      <section className="examples">
        {examples.map((e) => (
          <button key={e.id} className="example" disabled={busy} onClick={() => (setText(e.text), ask({ text: e.text }))}>
            <span className={`chip ${VERDICT_CLASS[e.expect]}`}>{e.expect}</span>
            <span className="example-title">{e.title}</span>
          </button>
        ))}
      </section>

      <form
        className="ask-box card"
        onSubmit={(e) => {
          e.preventDefault();
          if (text.trim()) ask({ text });
        }}
      >
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={3}
          maxLength={1000}
          placeholder="Can GenH2 Corporation get an exclusive license to US Patent 10,431,355 for energy generation in the USA for five years starting January 1, 2027?"
          aria-label="Clearance question"
        />
        <button className="button primary" disabled={busy || !text.trim()}>
          {busy ? "Deciding…" : "Decide"}
        </button>
      </form>
      {error ? <div className="error">{error}</div> : null}

      {parse ? <ParsePanel parse={parse} /> : null}
      {parse && !parse.complete && vocab ? <StructuredForm key={parse.text} vocab={vocab} initial={parse} busy={busy} onSubmit={(r) => ask({ request: r })} /> : null}
      {!parse && vocab && !decision ? <StructuredForm vocab={vocab} initial={null} busy={busy} onSubmit={(r) => ask({ request: r })} /> : null}

      {decision ? (
        <>
          <VerdictCard key={decision.id + decision.events_applied} decision={decision} diff={diff} onFact={setFact} />
          <div className="row-actions">
            <button className="button" onClick={reproduce}>
              Rerun from the stored cutoff
            </button>
            {rerun ? (
              <span className={`callout ${rerun.ok ? "ok" : "warn"} small`}>
                {rerun.ok
                  ? `Reproduced: the same findings and verdict (${rerun.verdict}), even with ${events.length} later steward action${events.length === 1 ? "" : "s"} in the graph.`
                  : "The rerun did not reproduce. This is a bug."}
              </span>
            ) : null}
            <a className="button" href="#/steward">
              Open the steward queue →
            </a>
          </div>
        </>
      ) : null}
      {fact ? <ProvenanceGraph iri={fact} onClose={() => setFact(null)} /> : null}
    </div>
  );
}
