import { useCallback, useEffect, useState } from "react";
import { api, local, ROLES, ROLE_LABEL, type ActResult, type AuthzMatrix, type Queue, type QueueFact, type QueueLink, type Role } from "../api";
import ProvenanceGraph from "../components/ProvenanceGraph";
import { DiffView } from "../components/VerdictCard";
import { useSession, type Entry } from "../session";

interface Outcome {
  title: string;
  result: ActResult;
  sparql: string[];
  affected: Entry[];
}

const ORIGIN_TEXT: Record<string, string> = {
  synthetic: "synthetic data",
  model: "proposed by a language model",
  real: "real record",
};

function Decide({
  onApprove,
  onReject,
  approveText,
  rejectText,
  busy,
}: {
  onApprove: (reason: string) => void;
  onReject: (reason: string) => void;
  approveText: string;
  rejectText: string;
  busy: boolean;
}) {
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

/** Who may do what, straight from the Cedar policies. A cell is allowed or it is not; nothing is inferred. */
function AuthzGrid({ matrix, role }: { matrix: AuthzMatrix; role: Role }) {
  return (
    <div className="authz-wrap">
      <table className="authz" aria-label="Which role may do which action">
        <thead>
          <tr>
            <th scope="col">Action</th>
            {matrix.roles.map((r) => (
              <th key={r} scope="col" className={r === role ? "me" : undefined}>
                {ROLE_LABEL[r]}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {matrix.rows.map((row) => (
            <tr key={row.label}>
              <th scope="row">{row.label}</th>
              {matrix.roles.map((r) => (
                <td key={r} className={`${row.allowed[r] ? "yes" : "no"}${r === role ? " me" : ""}`}>
                  <span aria-label={row.allowed[r] ? "allowed" : "not allowed"}>{row.allowed[r] ? "●" : "·"}</span>
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Propose({ busy, onPropose }: { busy: boolean; onPropose: (params: Record<string, unknown>, reason: string) => void }) {
  const [kind, setKind] = useState<"export" | "ownership">("export");
  const [patent, setPatent] = useState("LAR-17317-2");
  const [classification, setClassification] = useState("unrestricted");
  const [reason, setReason] = useState("");
  return (
    <form
      className="card form-grid propose"
      onSubmit={(e) => {
        e.preventDefault();
        onPropose(
          kind === "export"
            ? { kind, patent_key: patent, classification, permitted_countries: classification === "restricted" ? ["US"] : [] }
            : { kind, patent_key: patent, complete: true, co_owners: [] },
          reason,
        );
      }}
    >
      <label>
        Kind of fact
        <select value={kind} onChange={(e) => setKind(e.target.value as "export" | "ownership")}>
          <option value="export">Export classification</option>
          <option value="ownership">Ownership record (complete, no co-owners)</option>
        </select>
      </label>
      <label>
        Patent key
        <input value={patent} onChange={(e) => setPatent(e.target.value)} required />
      </label>
      {kind === "export" ? (
        <label>
          Classification
          <select value={classification} onChange={(e) => setClassification(e.target.value)}>
            <option value="unrestricted">Unrestricted</option>
            <option value="restricted">Restricted, permitted in the US</option>
          </select>
        </label>
      ) : null}
      <label className="span-2">
        Why you propose it
        <input value={reason} onChange={(e) => setReason(e.target.value)} required minLength={3} />
      </label>
      <button className="button" disabled={busy}>
        Propose
      </button>
    </form>
  );
}

function RouteNote({ result }: { result: ActResult }) {
  if (result.route === "pending_second_review") {
    return (
      <p className="callout warn">
        <strong>Held for counsel.</strong> This approval changed nothing. It waits because{" "}
        {[
          result.flags?.conflicts.length ? "it conflicts with an approved fact" : "",
          result.flags?.upgrades.length ? "it would move a verdict from COUNSEL or NO GO to GO" : "",
        ]
          .filter(Boolean)
          .join(" and ")}
        . Switch the role to Patent counsel, use a different name, and approve it in the second review.
      </p>
    );
  }
  if (result.route === "denied") return <p className="callout">Counsel denied the approval. No verdict changed.</p>;
  if (result.route === "proposed") return <p className="callout ok">Proposed. It sits in the candidate graph, and no rule reads it until someone else approves it.</p>;
  return null;
}

export default function Steward() {
  const { events, act, steward, setSteward, role, setRole, reset, history } = useSession();
  const [queue, setQueue] = useState<Queue | null>(null);
  const [matrix, setMatrix] = useState<AuthzMatrix | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const [fact, setFact] = useState<string | null>(null);

  const load = useCallback(() => {
    api.queue(events).then(setQueue).catch((e: Error) => setError(e.message));
  }, [events]);
  useEffect(load, [load]);
  useEffect(() => {
    api.authz().then(setMatrix).catch(() => undefined);
  }, []);

  async function run(title: string, event: Record<string, unknown> & { action: string }) {
    setBusy(true);
    setError(null);
    try {
      const out = await act(event);
      const held = out.result.route === "pending_second_review";
      setOutcome({ title: held ? "held for counsel's second review" : title, result: out.result, sparql: out.sparql, affected: out.affected });
    } catch (e) {
      setOutcome(null);
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const factEvent = (f: QueueFact, reason: string, approve: boolean) =>
    f.state === "pending_second_review"
      ? run(`${approve ? "approved" : "denied"} the held approval of ${local(f.id)}`, {
          action: "second_review",
          reason,
          params: { candidate: f.id, decision: approve ? "approve" : "deny" },
        })
      : run(`${approve ? "approved" : "rejected"} ${local(f.id)}`, {
          action: approve ? "approve_fact" : "reject_fact",
          reason,
          params: { candidate: f.id },
        });

  const linkEvent = (l: QueueLink, reason: string, approve: boolean) =>
    l.state === "pending_second_review"
      ? run(`${approve ? "approved" : "denied"} the held link`, {
          action: "second_review",
          reason,
          params: { a: l.a.iri, b: l.b.iri, decision: approve ? "approve" : "deny" },
        })
      : run(approve ? `linked ${l.a.name} and ${l.b.name}` : `kept ${l.a.name} and ${l.b.name} apart`, {
          action: approve ? "link_identity" : "reject_link",
          reason,
          params: approve ? { a: l.a.iri, b: l.b.iri, score: l.score } : { a: l.a.iri, b: l.b.iri },
        });

  const forCounsel = role === "counsel";

  return (
    <div className="page">
      <header className="page-head">
        <div className="eyebrow">Steward</div>
        <h1>New evidence waits for a person, and sometimes for two</h1>
        <p className="lede">
          No rule reads a proposed fact until it is approved. A steward approves alone only when the fact neither
          conflicts with an approved fact nor moves a verdict from COUNSEL or NO GO to GO. Otherwise the approval
          waits for counsel and changes nothing until counsel agrees. Nobody approves a fact they proposed. Cedar
          policies decide each of these, and the grid below shows their answers.
        </p>
      </header>

      <div className="steward-bar card">
        <label>
          Acting as
          <input value={steward} onChange={(e) => setSteward(e.target.value)} aria-label="Name" />
        </label>
        <label>
          Role
          <select value={role} onChange={(e) => setRole(e.target.value as Role)} aria-label="Role">
            {ROLES.map((r) => (
              <option key={r} value={r}>
                {ROLE_LABEL[r]}
              </option>
            ))}
          </select>
        </label>
        <span className="muted small">
          {events.length} action{events.length === 1 ? "" : "s"} · {history.length} decision{history.length === 1 ? "" : "s"}
        </span>
        <button className="button" onClick={() => (reset(), setOutcome(null))} disabled={!events.length && !history.length}>
          Start over
        </button>
      </div>
      <p className="muted small">
        In this public demo you choose your own name and role, so the checks show how the policies work, not who you
        are. In the AWS deployment, the role comes from the signed-in user's Cognito group.
      </p>
      {error ? (
        <div className="error" role="alert">
          <strong>Refused.</strong> {error}
        </div>
      ) : null}

      {outcome ? (
        <section className="card outcome">
          <div className="eyebrow">Done · {outcome.title}</div>
          <RouteNote result={outcome.result} />
          {outcome.result.policies?.length ? (
            <p className="muted small">
              Decided by Cedar policy <code>{outcome.result.policies.join(", ")}</code>.
            </p>
          ) : null}
          {outcome.result.route === "pending_second_review" && outcome.result.flags?.upgrades.length ? (
            <p className="small">
              {outcome.result.flags.upgrades.map((u) => `${u.patent} (${u.field}) would move from ${u.from} to ${u.to}.`).join(" ")}
            </p>
          ) : null}
          {outcome.affected.length ? (
            outcome.affected.map((a) => (
              <div key={a.decision.id + a.after_event} className="affected">
                <strong>{a.label}</strong>
                {a.diff ? <DiffView diff={a.diff} /> : null}
              </div>
            ))
          ) : outcome.result.route === "immediate" || outcome.result.route === "approved" ? (
            <p className="muted">
              {history.length
                ? "No decision in this session changed. Ask a question about the same patent to see the effect."
                : "No decisions in this session yet. Ask a question about this patent to see the effect."}
            </p>
          ) : null}
          {outcome.result.new_facts[0] ? (
            <button className="button" onClick={() => setFact(outcome.result.new_facts[0])}>
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
            <article key={f.id} className={`card queue-item${f.conflicts.length ? " warned" : ""}${f.state === "pending_second_review" ? " held" : ""}`}>
              <div className="queue-head">
                <span className="tag">{f.kind}</span>
                <span className={`tag ${f.origin === "real" ? "real" : "synthetic"}`}>{ORIGIN_TEXT[f.origin]}</span>
                <span className="mono">{f.patent_key}</span>
              </div>
              <h3>{f.summary}</h3>
              {f.quote ? (
                <blockquote className="clause">
                  <div className="clause-text">“{f.quote}”</div>
                  <cite>The notice's own words. The model chose the field; check that these words name it.</cite>
                </blockquote>
              ) : null}
              <p className="muted small">
                {f.source} Proposed by <strong>{f.proposed_by || "unrecorded"}</strong> on {f.proposed_at.slice(0, 10)}.
              </p>
              {f.conflicts.map((c) => (
                <p key={c.reason} className="callout warn small">
                  Conflicts with an approved fact. {c.reason}
                </p>
              ))}
              {f.state === "pending_second_review" ? (
                <>
                  <p className="callout small">
                    <strong>Waiting for counsel.</strong> {f.first_approver} approved it first. {queue.why[f.id]?.join(" ")}
                  </p>
                  {!forCounsel ? <p className="muted small">Switch the role to Patent counsel, with a different name, to review it.</p> : null}
                </>
              ) : null}
              <button className="link small" onClick={() => setFact(f.id)}>
                Inspect the candidate in the graph
              </button>
              {f.state === "pending_second_review" && !forCounsel ? null : (
                <Decide
                  busy={busy}
                  approveText={f.state === "pending_second_review" ? "Approve (second review)" : "Approve"}
                  rejectText={f.state === "pending_second_review" ? "Deny" : "Reject"}
                  onApprove={(reason) => factEvent(f, reason, true)}
                  onReject={(reason) => factEvent(f, reason, false)}
                />
              )}
            </article>
          ))}
        </div>
      </section>

      <section className="section">
        <h2>Propose a fact</h2>
        <p className="muted">
          Anyone with the steward or licensing manager role may propose a fact. The proposer cannot approve it, so try
          approving it under the same name and watch the policy refuse, then switch the name.
        </p>
        <Propose
          busy={busy}
          onPropose={(params, reason) => run(`proposed a ${String(params.kind)} fact`, { action: "propose_fact", reason, params })}
        />
      </section>

      <section className="section">
        <h2>Possible duplicate companies</h2>
        <p className="muted">
          The rules treat two spellings of one company as two licensees until a steward links them. The resolver
          proposes pairs after removing legal suffixes and checking addresses, but it never links them itself. A link
          writes <code>owl:sameAs</code> and a dated identity link, and every rule that matches licensees then sees both
          names. A link that would move one of your questions to GO waits for counsel too.
        </p>
        {queue && !queue.links.length ? <p className="muted">No open pairs.</p> : null}
        <div className="queue">
          {queue?.links.map((l) => (
            <article key={l.id} className={`card queue-item${l.state === "pending_second_review" ? " held" : ""}`}>
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
              {l.state === "pending_second_review" ? (
                <p className="callout small">
                  <strong>Waiting for counsel.</strong> {l.first_approver} approved it first. {queue.why[l.id]?.join(" ")}
                </p>
              ) : null}
              {l.state === "pending_second_review" && !forCounsel ? null : (
                <Decide
                  busy={busy}
                  approveText={l.state === "pending_second_review" ? "Approve (second review)" : "Same company"}
                  rejectText={l.state === "pending_second_review" ? "Deny" : "Different"}
                  onApprove={(reason) => linkEvent(l, reason, true)}
                  onReject={(reason) => linkEvent(l, reason, false)}
                />
              )}
            </article>
          ))}
        </div>
      </section>

      {matrix ? (
        <section className="section">
          <h2>Who may do what</h2>
          <p className="muted">
            Each cell is the answer of {matrix.policies.length} Cedar policies for a typical request. “Approve a
            conflicting fact alone” is empty for every role on purpose: only the two-step path can approve it.
          </p>
          <AuthzGrid matrix={matrix} role={role} />
        </section>
      ) : null}

      {queue && Object.keys(queue.decided).length ? (
        <section className="section">
          <h2>Event log</h2>
          <p className="muted">Your browser holds this log and sends it with every call. The server replays it over the frozen graph, so it stores nothing.</p>
          <ol className="event-log">
            {events.map((e) => (
              <li key={String(e.id)}>
                <span className="mono">{String(e.id)}</span> <span className="mono faint">{String(e.at)}</span> <strong>{e.action}</strong> by {String(e.steward)} ({String(e.role)}){" "}
                {e.route ? <span className={`tag ${e.route === "pending_second_review" ? "synthetic" : "real"}`}>{String(e.route).replace(/_/g, " ")}</span> : null}: “{String(e.reason)}”
              </li>
            ))}
          </ol>
        </section>
      ) : null}
    </div>
  );
}
