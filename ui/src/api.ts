import { authHeader } from "./auth";

// Types and calls for the GoNoGo API (api/index.py). The server keeps no session: every call carries the
// steward's event log, and the server replays it over the frozen graphs.

export type Status = "PASS" | "FAIL" | "UNKNOWN" | "REVIEW" | "PENDING" | "NOT_APPLICABLE";
export type Verdict = "GO" | "NO GO" | "HOLD" | "COUNSEL" | "NO DATA";
export type GEvent = Record<string, unknown> & { id?: string; at?: string; action: string };

export interface FactRef {
  iri: string;
  kind: string;
  label: string;
  recorded_at: string | null;
  approved_by: string | null;
  origin: "real" | "synthetic";
  sources: { title?: string; url?: string; kind?: string }[];
}

export interface ClauseRef {
  iri: string;
  fact: string;
  kind: string;
  text: string;
  start: number;
  end: number;
  document: string;
  document_title: string | null;
  document_url: string | null;
}

export interface Finding {
  rule: string;
  name: string;
  status: Status;
  summary: string;
  rule_version: string;
  facts: FactRef[];
  clauses: ClauseRef[];
  details: Record<string, unknown>;
  missing: string[];
  notes: string[];
}

export interface Decision {
  id: string;
  request: Record<string, unknown> & { patent_key: string; exclusivity: string; field: string; territory: string; start: string; end: string; licensee_name?: string | null };
  user: string;
  role: string;
  release_version: string;
  rule_versions: Record<string, string>;
  combiner_policy_version: string;
  evaluation_time: string;
  recording_cutoff: string;
  findings: Finding[];
  facts_read: string[];
  verdict: Verdict;
  signature: string;
  explanation: string[];
  events_applied: number;
  parse: Parse | null;
}

export interface Found {
  value: string;
  span: [number, number];
  text: string;
  label: string | null;
  how: "rule" | "model" | "computed";
}

export interface Candidate {
  iri: string;
  name: string;
  status: string;
  score: number;
  why: string;
}

export interface Parse {
  text: string;
  found: Partial<Record<"patent_key" | "exclusivity" | "field" | "territory" | "start" | "end" | "licensee", Found>>;
  missing: string[];
  notes: string[];
  licensee: { status: string; ids: string[]; country: string | null; candidates: Candidate[] } | null;
  parser: string;
  complete: boolean;
}

export interface Change {
  rule: string;
  name: string;
  from: Status;
  to: Status;
  reason: string;
  summary_before: string;
  summary_after: string;
  added_facts: string[];
  removed_facts: string[];
}

export interface Diff {
  verdict_before: Verdict;
  verdict_after: Verdict;
  verdict_changed: boolean;
  changes: Change[];
}

export type Role = "licensing_manager" | "steward" | "counsel" | "ontology_owner" | "finance_analyst" | "auditor";
export const ROLES: Role[] = ["steward", "counsel", "licensing_manager", "ontology_owner", "finance_analyst", "auditor"];
export const ROLE_LABEL: Record<Role, string> = {
  licensing_manager: "Licensing manager",
  steward: "Data steward",
  counsel: "Patent counsel",
  ontology_owner: "Ontology owner",
  finance_analyst: "Finance analyst",
  auditor: "Auditor",
};

export interface Flags {
  conflicts: { fact: string; reason: string }[];
  upgrades: { patent: string; field: string; from: string; to: string }[];
}

export interface QueueFact {
  id: string;
  kind: string;
  summary: string;
  patent_key: string | null;
  proposed_at: string;
  proposed_by: string;
  origin: "real" | "synthetic" | "model";
  source: string;
  conflicts: { fact: string; reason: string }[];
  warning: string | null;
  state: "proposed" | "pending_second_review";
  first_approver: string | null;
  needs: "steward" | "counsel";
  quote?: string;
  grant?: string;
}

export interface AuthzMatrix {
  roles: Role[];
  rows: { label: string; action: string; allowed: Record<Role, boolean> }[];
  policies: string[];
}

export interface Party {
  iri: string;
  name: string;
  address?: string | null;
  origin?: string;
}

export interface QueueLink {
  id: string;
  a: Party;
  b: Party;
  status: string;
  score: number;
  basis: string;
  address: string;
  state: "proposed" | "pending_second_review";
  first_approver: string | null;
}

export interface Queue {
  facts: QueueFact[];
  links: QueueLink[];
  decided: Record<string, { decision: string; event: string }>;
  why: Record<string, string[]>;
}

export interface ActResult {
  action: string;
  route: "immediate" | "pending_second_review" | "approved" | "denied" | "rejected" | "proposed";
  flags?: Flags;
  policies?: string[];
  new_facts: string[];
  superseded: string[];
  patents: string[];
  candidate?: string;
}

export interface Concept {
  id: string;
  label: string;
  broader: string | null;
}

export interface Vocabulary {
  fields: Concept[];
  territories: Concept[];
  exclusivity: string[];
}

export interface Example {
  id: string;
  title: string;
  expect: Verdict;
  text: string;
}

export interface GraphNode {
  id: string;
  label: string;
  types: string[];
  depth: number;
  attrs: Record<string, string>;
}

export interface ProvGraph {
  root: string;
  nodes: GraphNode[];
  links: { source: string; target: string; label: string }[];
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function call<T>(path: string, body?: unknown, root = "/api/"): Promise<T> {
  const res = await fetch(`${root}${path}`, {
    method: body === undefined ? "GET" : "POST",
    headers: { ...(body === undefined ? {} : { "Content-Type": "application/json" }), ...authHeader() },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const j = await res.json();
      detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch {
      // The body was not JSON. Keep the status text.
    }
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as T;
}

export const api = {
  health: () => call<{ release: string; demo_now: string; combiner_policy: string; rules: Record<string, string>; graphs: Record<string, number> }>("health"),
  vocabulary: () => call<Vocabulary>("vocabulary"),
  examples: () => call<Example[]>("examples"),
  decide: (events: GEvent[], input: { text?: string; request?: Record<string, unknown>; previous?: Decision | null }) =>
    call<{ parse: Parse | null; decision: Decision | null; diff?: Diff }>("decide", { events, ...input }),
  rerun: (events: GEvent[], record: Decision) => call<{ decision: Decision; reproduced: boolean }>("rerun", { events, record }),
  queue: (events: GEvent[]) => call<Queue>("queue", { events }),
  act: (events: GEvent[], event: GEvent, requests: Record<string, unknown>[] = []) =>
    call<{ events: GEvent[]; result: ActResult; sparql_update: string[] }>("act", { events, event, requests }),
  authz: () => call<AuthzMatrix>("authz"),
  // The same request, decided over Neptune by the query Lambda. It exists only in the AWS deployment.
  neptuneDecide: (request: Record<string, unknown>) =>
    call<{ decision: Decision; backend: string }>("decide", { request }, "/"),
  neptuneHealth: () => call<{ status: string; role: string; user: string; graphs: string[] }>("health", undefined, "/"),
  provenance: (events: GEvent[], iri: string) => call<ProvGraph>("provenance", { events, iri }),
};

export const VERDICT_CLASS: Record<Verdict, string> = {
  GO: "go",
  "NO GO": "nogo",
  HOLD: "hold",
  COUNSEL: "counsel",
  "NO DATA": "nodata",
};

export const STATUS_CLASS: Record<Status, string> = {
  PASS: "go",
  FAIL: "nogo",
  PENDING: "hold",
  REVIEW: "counsel",
  UNKNOWN: "nodata",
  NOT_APPLICABLE: "na",
};

export function local(iri: string): string {
  return iri.replace(/\/$/, "").split(/[/#]/).pop() ?? iri;
}
