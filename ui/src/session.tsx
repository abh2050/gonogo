import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, type ActResult, type Decision, type Diff, type GEvent, type Role } from "./api";

// The browser holds the session: the steward's event log and the decisions made so far. The server replays
// the log on every call. Session storage keeps the session across a page change, not across browser tabs.

export interface Entry {
  decision: Decision;
  label: string;
  diff?: Diff; // against the previous decision on the same request
  after_event?: string;
}

interface SessionValue {
  events: GEvent[];
  history: Entry[];
  steward: string;
  setSteward: (name: string) => void;
  role: Role;
  setRole: (role: Role) => void;
  record: (entry: Entry) => void;
  act: (event: GEvent) => Promise<{ sparql: string[]; affected: Entry[]; result: ActResult }>;
  reset: () => void;
}

const KEY = "gonogo-session-v1";
const SessionContext = createContext<SessionValue | null>(null);

function load(): { events: GEvent[]; history: Entry[]; steward: string; role: Role } {
  try {
    const raw = sessionStorage.getItem(KEY);
    if (raw) return JSON.parse(raw);
  } catch {
    // Storage can be blocked or hold an older shape. Start fresh.
  }
  return { events: [], history: [], steward: "Demo Steward", role: "steward" };
}

export function SessionProvider({ children }: { children: ReactNode }) {
  const initial = useMemo(load, []);
  const [events, setEvents] = useState<GEvent[]>(initial.events);
  const [history, setHistory] = useState<Entry[]>(initial.history);
  const [steward, setSteward] = useState(initial.steward);
  const [role, setRole] = useState<Role>(initial.role ?? "steward");

  useEffect(() => {
    try {
      sessionStorage.setItem(KEY, JSON.stringify({ events, history, steward, role }));
    } catch {
      // The session still works for this page view.
    }
  }, [events, history, steward, role]);

  const record = useCallback((entry: Entry) => setHistory((h) => [entry, ...h].slice(0, 40)), []);

  // Apply a steward action, then rerun every distinct request decided so far, so the steward sees which
  // verdicts the new evidence changed.
  const act = useCallback(
    async (event: GEvent) => {
      // The questions asked so far travel with the action, so the server can tell whether it moves one to GO.
      const asked = [...new Map(history.map((e) => [e.decision.id, e])).values()].slice(0, 20).map((e) =>
        e.decision.parse?.text ? { text: e.decision.parse.text } : { request: requestOf(e.decision) },
      );
      const out = await api.act(events, { ...event, steward, role }, asked);
      setEvents(out.events);
      const seen = new Set<string>();
      const affected: Entry[] = [];
      for (const e of history) {
        const key = JSON.stringify(e.decision.request);
        if (seen.has(key)) continue;
        seen.add(key);
        // A typed question is parsed again, so a new identity link can resolve the licensee.
        const text = e.decision.parse?.text;
        const input = text ? { text } : { request: requestOf(e.decision) };
        const res = await api.decide(out.events, { ...input, previous: e.decision });
        if (!res.decision) continue;
        const entry: Entry = { decision: res.decision, label: e.label, diff: res.diff, after_event: String(out.events.at(-1)?.id ?? "") };
        if (res.diff && (res.diff.verdict_changed || res.diff.changes.length)) affected.push(entry);
      }
      if (affected.length) setHistory((h) => [...affected, ...h].slice(0, 40));
      return { sparql: out.sparql_update, affected, result: out.result };
    },
    [events, history, steward, role],
  );

  const reset = useCallback(() => {
    setEvents([]);
    setHistory([]);
  }, []);

  const value = useMemo(
    () => ({ events, history, steward, setSteward, role, setRole, record, act, reset }),
    [events, history, steward, role, record, act, reset],
  );
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionValue {
  const v = useContext(SessionContext);
  if (!v) throw new Error("useSession needs a SessionProvider");
  return v;
}

export function requestOf(d: Decision): Record<string, unknown> {
  const r = d.request;
  return {
    patent_key: r.patent_key,
    exclusivity: r.exclusivity,
    field: r.field,
    territory: r.territory,
    start: r.start,
    end: r.end,
    licensee_name: r.licensee_name ?? null,
    licensee_ids: (r.licensee_ids as string[]) ?? [],
    licensee_country: (r.licensee_country as string | null) ?? null,
  };
}
