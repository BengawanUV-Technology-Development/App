function LogsView() {
  return (
    <section className="placeholder-stack">
      <header className="view-header">
        <div>
          <p className="view-kicker">Logs</p>
          <h1 className="view-title">Session logs</h1>
          <p className="view-copy">Mission and system logs stay simple for this phase.</p>
        </div>
      </header>
      <article className="panel placeholder-card">
        <p className="panel-label">Placeholder</p>
        <h2>Log browser shell</h2>
        <p className="muted">The future logs view can plug into `/logs/summary` and `/logs/recent` here.</p>
      </article>
    </section>
  );
}

export default LogsView;
