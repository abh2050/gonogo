import { useState } from "react";
import { STATUS_CLASS, VERDICT_CLASS, local, type Decision, type Diff, type Finding } from "../api";

const STATUS_TEXT: Record<string, string> = {
  PASS: "pass",
  FAIL: "fail",
  PENDING: "pending",
  REVIEW: "review",
  UNKNOWN: "unknown",
  NOT_APPLICABLE: "n/a",
};

/** Seven tiles, one per rule, in the order the combiner reads them. */
export function RuleStrip({ decision, changed, onPick, picked }: { decision: Decision; changed?: Set<string>; onPick?: (rule: string) => void; picked?: string | null }) {
  return (
    <div className="rule-strip" role="list" aria-label="Rule results">
      {decision.findings.map((f) => (
        <button
          key={f.rule}
          role="listitem"
          className={`rule-tile ${STATUS_CLASS[f.status]}${changed?.has(f.rule) ? " changed" : ""}`}
          aria-pressed={picked === f.rule}
          onClick={() => onPick?.(f.rule)}
          title={`${f.rule} ${f.name}: ${f.summary}`}
        >
          <span className="rule-id">{f.rule}</span>
          <span className="rule-status">{STATUS_TEXT[f.status]}</span>
        </button>
      ))}
    </div>
  );
}

function highlight(text: string, start: number, end: number, clauseStart: number) {
  // Clause spans are offsets in the document; the stored text starts at the clause's own start.
  const a = Math.max(0, start - clauseStart);
  const b = Math.max(a, end - clauseStart);
  if (a === 0 && b >= text.length) return <mark>{text}</mark>;
  return (
    <>
      {text.slice(0, a)}
      <mark>{text.slice(a, b)}</mark>
      {text.slice(b)}
    </>
  );
}

export function FindingDetail({ finding, onFact }: { finding: Finding; onFact?: (iri: string) => void }) {
  return (
    <div className="finding">
      <div className="finding-head">
        <span className={`chip ${STATUS_CLASS[finding.status]}`}>{finding.status.replace("_", " ")}</span>
        <h3>
          {finding.rule} · {finding.name}
        </h3>
        <span className="mono faint">v{finding.rule_version}</span>
      </div>
      <p>{finding.summary}</p>
      {finding.missing.length ? (
        <p className="callout warn">Missing: {finding.missing.join("; ")}</p>
      ) : null}
      {finding.notes.map((n) => (
        <p key={n} className="muted small">
          {n}
        </p>
      ))}
      {finding.facts.length ? (
        <>
          <h4>Facts the rule read</h4>
          <ul className="facts">
            {finding.facts.map((f) => (
              <li key={f.iri}>
                <button className="link" onClick={() => onFact?.(f.iri)} title="Show this fact's provenance graph">
                  {f.label}
                </button>
                <span className="fact-meta">
                  <span className="tag">{f.kind}</span>
                  {f.origin === "synthetic" ? <span className="tag synthetic">synthetic</span> : <span className="tag real">real</span>}
                  {f.approved_by ? <span>approved by {local(f.approved_by).replace(/-/g, " ")}</span> : null}
                  {f.recorded_at ? <span className="mono">recorded {f.recorded_at.slice(0, 10)}</span> : null}
                </span>
              </li>
            ))}
          </ul>
        </>
      ) : null}
      {finding.clauses.length ? (
        <>
          <h4>Source clauses</h4>
          {finding.clauses.map((c) => (
            <blockquote key={c.iri + c.start} className="clause">
              <div className="clause-text">{highlight(c.text, c.start, c.end, c.start)}</div>
              <cite>
                {c.kind} clause ·{" "}
                {c.document_url ? (
                  <a href={c.document_url} target="_blank" rel="noreferrer">
                    {c.document_title ?? local(c.document)}
                  </a>
                ) : (
                  (c.document_title ?? local(c.document))
                )}{" "}
                · chars {c.start}–{c.end}
              </cite>
            </blockquote>
          ))}
        </>
      ) : null}
    </div>
  );
}

export function DiffView({ diff }: { diff: Diff }) {
  return (
    <div className="diff">
      <div className="diff-verdicts">
        <span className={`chip ${VERDICT_CLASS[diff.verdict_before]}`}>{diff.verdict_before}</span>
        <span className="arrow" aria-hidden="true">→</span>
        <span className={`chip ${VERDICT_CLASS[diff.verdict_after]}`}>{diff.verdict_after}</span>
        {!diff.verdict_changed ? <span className="muted small">verdict unchanged</span> : null}
      </div>
      {diff.changes.map((c) => (
        <div key={c.rule} className="diff-row">
          <strong>
            {c.rule} {c.name}
          </strong>
          <span className={`chip ${STATUS_CLASS[c.from]}`}>{c.from}</span>
          <span aria-hidden="true">→</span>
          <span className={`chip ${STATUS_CLASS[c.to]}`}>{c.to}</span>
          <p className="muted small">{c.reason}</p>
        </div>
      ))}
    </div>
  );
}

export default function VerdictCard({ decision, diff, onFact }: { decision: Decision; diff?: Diff; onFact?: (iri: string) => void }) {
  const decisive = decision.findings.find((f) => f.status === "FAIL") ?? decision.findings.find((f) => f.status !== "PASS" && f.status !== "NOT_APPLICABLE");
  const [picked, setPicked] = useState<string | null>(diff?.changes[0]?.rule ?? decisive?.rule ?? decision.findings[0]?.rule ?? null);
  const changed = new Set(diff?.changes.map((c) => c.rule));
  const finding = decision.findings.find((f) => f.rule === picked);
  const r = decision.request;
  return (
    <article className={`card verdict-panel ${VERDICT_CLASS[decision.verdict]}`}>
      <header className="verdict-top">
        <div>
          <div className="eyebrow">Verdict</div>
          <div className={`verdict-big ${VERDICT_CLASS[decision.verdict]}`}>{decision.verdict}</div>
        </div>
        <dl className="request-facts">
          <div>
            <dt>Patent</dt>
            <dd className="mono">{r.patent_key}</dd>
          </div>
          <div>
            <dt>License</dt>
            <dd>{String(r.exclusivity).replace(/-/g, " ")}</dd>
          </div>
          <div>
            <dt>Field</dt>
            <dd>{String(r.field).replace(/-/g, " ")}</dd>
          </div>
          <div>
            <dt>Territory</dt>
            <dd>{r.territory}</dd>
          </div>
          <div>
            <dt>Term</dt>
            <dd className="mono">
              {r.start} → {r.end}
            </dd>
          </div>
          {r.licensee_name ? (
            <div>
              <dt>Licensee</dt>
              <dd>{r.licensee_name}</dd>
            </div>
          ) : null}
        </dl>
      </header>
      <ol className="explanation">
        {decision.explanation.map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ol>
      {diff ? <DiffView diff={diff} /> : null}
      <RuleStrip decision={decision} changed={changed} onPick={setPicked} picked={picked} />
      {finding ? <FindingDetail finding={finding} onFact={onFact} /> : <p className="muted small">Pick a rule to see its evidence.</p>}
      <footer className="decision-meta">
        <span className="mono">{decision.id}</span>
        <span>release {decision.release_version}</span>
        <span>combiner {decision.combiner_policy_version}</span>
        <span className="mono">cutoff {decision.recording_cutoff.replace("T", " ").replace("+00:00", "Z")}</span>
        <span>{decision.events_applied} steward action{decision.events_applied === 1 ? "" : "s"} applied</span>
        <span className="mono" title="SHA-256 over the findings">sig {decision.signature.slice(0, 12)}</span>
      </footer>
    </article>
  );
}
