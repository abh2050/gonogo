import { useCallback, useEffect, useState } from "react";
import { api, local, type Queue } from "../api";
import ProvenanceGraph from "../components/ProvenanceGraph";
import { DiffView } from "../components/VerdictCard";
import { useSession, type Entry } from "../session";

interface Outcome {
  title: string;
  sparql: string[];
  affected: Entry[];
  newFact?: string;
}

function Decide({ onApprove, onReject, approveText, rejectText, busy }: { onApprove: (reason: string) => void; onReject: (reason: string) => void; approveText: string; rejectText: string; busy: boolean }) {
  const [reason, setReason] = useState("");
  const ok = reason.trim().length >= 3;
  return (
    <div className="decide">
      <input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Reason (required, recorded with the action)" aria-label="Reason" />
      <button className="button primary" disabled={!ok || busy} onClick={() => onApprove(reason)}>
        {approveText}
      </button>
      <button className="button" disabled={!ok || busy} onClick={() => onReject(reason)}>
        {rejectText}
      </button>
    </div>
  );
}

export default function Steward() {
  const { events, act, steward, setSteward, reset, history } = useSession();
  const [queue, setQueue] = useState<Queue | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const [fact, setFact] = useState<string | null>(null);

  const load = useCallback(() => {
    api.queue(events).then(setQueue).catch((e: Error) => setError(e.message));
  }, [events]);
  useEffect(load, [load]);

  async function run(title: string, event: Record<string, unknown> & { action: string }) {
    setBusy(true);
    setError(null);
    try {
      const out = await act(event);
      setOutcome({ title, sparql: out.sparql, affected: out.affected, newFact: out.newFacts[0] });
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="page">
      <header className="page-head">
        <div className="eyebrow">Steward</div>
        <h1>New evidence waits for a person</h1>
        <p className="lede">
          No rule reads a proposed fact until you approve it. Approve or reject each one with a reason. An approval
          must pass SHACL, records you as the approver, and supersedes the old fact without deleting it. Every
          decision you made in this session then reruns, and the diff names the rule that changed.
        </p>
      </header>

      <div className="steward-bar card">
        <label>
          Acting as
          <input value={steward} onChange={(e) => setSteward(e.target.value)} aria-label="Steward name" />
        </label>
        <span className="muted small">
          {events.length} action{events.length === 1 ? "" : "s"} in this session · {history.length} decision{history.length === 1 ? "" : "s"}
        </span>
        <button className="button" onClick={() => (reset(), setOutcome(null))} disabled={!events.length && !history.length}>
          Start over
        </button>
      </div>
      {error ? <div className="error">{error}</div> : null}

      {outcome ? (
        <section className="card outcome">
          <div className="eyebrow">Done · {outcome.title}</div>
          {outcome.affected.length ? (
            outcome.affected.map((a) => (
              <div key={a.decision.id + a.after_event} className="affected">
                <strong>{a.label}</strong>
                {a.diff ? <DiffView diff={a.diff} /> : null}
              </div>
            ))
          ) : (
            <p className="muted">
              {history.length
                ? "No decision in this session changed. Ask a question about the same patent to see the effect."
                : "No decisions in this session yet. Ask a question about this patent to see the effect."}
            </p>
          )}
          {outcome.newFact ? (
            <button className="button" onClick={() => setFact(outcome.newFact!)}>
              Show the new fact's provenance graph
            </button>
          ) : null}
          <details>
            <summary>The same change as SPARQL Update, for Fuseki or Neptune</summary>
            <pre className="sparql">{outcome.sparql.join("\n\n")}</pre>
          </details>
        </section>
      ) : null}
      {fact ? <ProvenanceGraph iri={fact} onClose={() => setFact(null)} /> : null}

      <section className="section">
        <h2>Proposed facts</h2>
        {!queue ? <div className="loading">Loading the queue…</div> : null}
        {queue && !queue.facts.length ? <p className="muted">The candidate graph is empty.</p> : null}
        <div className="queue">
          {queue?.facts.map((f) => (
            <article key={f.id} className={`card queue-item${f.warning ? " warned" : ""}`}>
              <div className="queue-head">
                <span className="tag">{f.kind}</span>
                <span className="tag synthetic">{f.origin}</span>
                <span className="mono">{f.patent_key}</span>
              </div>
              <h3>{f.summary}</h3>
              <p className="muted small">
                {f.source} Proposed {f.proposed_at.slice(0, 10)}.
              </p>
              {f.warning ? <p className="callout warn small">{f.warning}</p> : null}
              <button className="link small" onClick={() => setFact(f.id)}>
                Inspect the candidate in the graph
              </button>
              <Decide
                busy={busy}
                approveText="Approve"
                rejectText="Reject"
                onApprove={(reason) => run(`approved ${local(f.id)}`, { action: "approve_fact", reason, params: { candidate: f.id } })}
                onReject={(reason) => run(`rejected ${local(f.id)}`, { action: "reject_fact", reason, params: { candidate: f.id } })}
              />
            </article>
          ))}
        </div>
      </section>

      <section className="section">
        <h2>Possible duplicate companies</h2>
        <p className="muted">
          The rules treat two spellings of one company as two licensees until you link them. The resolver proposes
          pairs after removing legal suffixes and checking addresses, but it never links them itself. A link writes{" "}
          <code>owl:sameAs</code> and a dated identity link, and every rule that matches licensees then sees both
          names.
        </p>
        {queue && !queue.links.length ? <p className="muted">No open pairs.</p> : null}
        <div className="queue">
          {queue?.links.map((l) => (
            <article key={l.id} className="card queue-item">
              <div className="queue-head">
                <span className="tag">{l.status}</span>
                <span className="mono">score {l.score.toFixed(2)}</span>
              </div>
              <h3>
                “{l.a.name}” and “{l.b.name}”
              </h3>
              <p className="muted small">
                {l.basis}. Addresses: {l.address && l.address !== "unknown" ? l.address : "not on record for both"}.
              </p>
              <Decide
                busy={busy}
                approveText="Same company"
                rejectText="Different"
                onApprove={(reason) => run(`linked ${l.a.name} and ${l.b.name}`, { action: "link_identity", reason, params: { a: l.a.iri, b: l.b.iri, score: l.score } })}
                onReject={(reason) => run(`kept ${l.a.name} and ${l.b.name} apart`, { action: "reject_link", reason, params: { a: l.a.iri, b: l.b.iri } })}
              />
            </article>
          ))}
        </div>
      </section>

      {queue && Object.keys(queue.decided).length ? (
        <section className="section">
          <h2>Event log</h2>
          <p className="muted">Your browser holds this log and sends it with every call. The server replays it over the frozen graph, so it stores nothing.</p>
          <ol className="event-log">
            {events.map((e) => (
              <li key={String(e.id)}>
                <span className="mono">{String(e.id)}</span> <span className="mono faint">{String(e.at)}</span> <strong>{e.action}</strong> by {String(e.steward)}: “{String(e.reason)}”
              </li>
            ))}
          </ol>
        </section>
      ) : null}
    </div>
  );
}
