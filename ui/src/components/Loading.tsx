export function Loading({ what }: { what: string }) {
  return <div className="loading">Loading {what}…</div>;
}

export function Failed({ error }: { error: string }) {
  return (
    <div className="error" role="alert">
      Could not load the data: {error}. Run <code>python -m kg.export_viz</code> to create it.
    </div>
  );
}
