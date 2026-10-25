import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, type Decision, type Diff, type GEvent } from "./api";

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
  record: (entry: Entry) => void;
  act: (event: GEvent) => Promise<{ sparql: string[]; affected: Entry[]; newFacts: string[] }>;
  reset: () => void;
}

const KEY = "gonogo-session-v1";
const SessionContext = createContext<SessionValue | null>(null);

function load(): { events: GEvent[]; history: Entry[]; steward: string } {
  try {
    const raw = sessionStorage.getItem(KEY);
    if (raw) return JSON.parse(raw);
  } catch {
    // Storage can be blocked or hold an older shape. Start fresh.
  }
  return { events: [], history: [], steward: "Demo Steward" };
}

export function SessionProvider({ children }: { children: ReactNode }) {
  const initial = useMemo(load, []);
  const [events, setEvents] = useState<GEvent[]>(initial.events);
  const [history, setHistory] = useState<Entry[]>(initial.history);
  const [steward, setSteward] = useState(initial.steward);

  useEffect(() => {
    try {
      sessionStorage.setItem(KEY, JSON.stringify({ events, history, steward }));
    } catch {
      // The session still works for this page view.
    }
  }, [events, history, steward]);

  const record = useCallback((entry: Entry) => setHistory((h) => [entry, ...h].slice(0, 40)), []);

  // Apply a steward action, then rerun every distinct request decided so far, so the steward sees which
  // verdicts the new evidence changed.
  const act = useCallback(
    async (event: GEvent) => {
      const out = await api.act(events, { ...event, steward });
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
      return { sparql: out.sparql_update, affected, newFacts: out.result.new_facts };
    },
    [events, history, steward],
  );

  const reset = useCallback(() => {
    setEvents([]);
    setHistory([]);
  }, []);

  const value = useMemo(
    () => ({ events, history, steward, setSteward, record, act, reset }),
    [events, history, steward, record, act, reset],
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
