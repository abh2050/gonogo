import { useEffect, useState } from "react";

export type Kind = "fact" | "thing" | "party" | "document" | "vocabulary" | "process" | "external";

export interface OntNode {
  id: string;
  label: string;
  definition: string;
  comment: string;
  kind: Kind;
  external: boolean;
  rules: string[];
  decisions: string[];
  datatypeProperties: { name: string; definition: string }[];
}

export interface OntEdge {
  source: string;
  target: string;
  kind: "subclass" | "property" | "chain";
  label: string;
  definition?: string;
  rules?: string;
}

export interface Ontology {
  nodes: OntNode[];
  edges: OntEdge[];
  counts: { classes: number; objectProperties: number; datatypeProperties: number };
}

export interface Concept {
  id: string;
  label: string;
  notation: string;
  iso?: string;
  definition?: string;
  children?: Concept[];
}

export interface Scheme {
  title: string;
  tops: Concept[];
}

export interface LapsedPatent {
  key: string;
  lapse: string;
  nasaExpires: string;
  phantomYears: number;
}

export interface Findings {
  legalStatus: {
    nasaCallsInForce: number;
    states: Record<string, number>;
    phantomYearsMedian: number;
    lapsed: LapsedPatent[];
  };
  applications: { listedAsApplication: number; nowGranted: number };
  noticeMatch: { total: number; datasetOnly: number; withT2: number };
  extraction: {
    total: number;
    licensee: number;
    territory: number;
    deadline: number;
    specificExclusivity: number;
    fieldStated: number;
  };
  factsByClass: Record<string, { real: number; synthetic: number }>;
  scope: {
    patents: number;
    byCenter: Record<string, number>;
    byUsptoState: Record<string, number>;
    notices: number;
  };
  synthetic: { agreements: number; injectedCases: number; verdicts: Record<string, number> };
  uspto: { candidates: number; found: number };
}

export interface BitemporalFact {
  id: string;
  field: string;
  validFrom: string;
  validTo: string;
  recordedAt: string;
  supersededAt: string | null;
  supersedes: string[];
}

export interface Bitemporal {
  patent: string;
  requestText: string;
  requestField: string;
  requestExclusivity: string;
  facts: BitemporalFact[];
  cutoffBefore: string;
  cutoffAfter: string;
}

/** Load one JSON file from public/data. The files come from `python -m kg.export_viz`. */
export function useJson<T>(name: string): { data: T | null; error: string | null } {
  const [state, setState] = useState<{ data: T | null; error: string | null }>({ data: null, error: null });
  useEffect(() => {
    let live = true;
    fetch(`${import.meta.env.BASE_URL}data/${name}`)
      .then((r) => {
        if (!r.ok) throw new Error(`${name}: HTTP ${r.status}`);
        return r.json() as Promise<T>;
      })
      .then((data) => live && setState({ data, error: null }))
      .catch((e: unknown) => live && setState({ data: null, error: String(e) }));
    return () => {
      live = false;
    };
  }, [name]);
  return state;
}

export const KIND_LABEL: Record<Kind, string> = {
  fact: "Bitemporal facts",
  thing: "Things",
  party: "Parties",
  document: "Documents and clauses",
  vocabulary: "Controlled vocabularies",
  process: "Activities and actions",
  external: "Reused terms",
};
