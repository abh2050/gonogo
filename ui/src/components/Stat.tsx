import type { ReactNode } from "react";

export default function Stat({ value, label, note }: { value: ReactNode; label: string; note?: string }) {
  return (
    <div className="card stat">
      <div className="stat-value">{value}</div>
      <div className="stat-label">{label}</div>
      {note ? <div className="stat-note">{note}</div> : null}
    </div>
  );
}
