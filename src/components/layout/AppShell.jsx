import Sidebar from "./Sidebar";
import StatusBar from "./StatusBar";

function AppShell({ activeView, onNavigate, health, telemetry, children }) {
  return (
    <div className="app-shell">
      <header className="top-frame">
        <Sidebar activeView={activeView} onNavigate={onNavigate} />
        <div className="connection-panel">
          <div className="connection-summary">
            <span className={`connection-dot ${health.bridge?.online ? "is-online" : ""}`} />
            <span>
              <strong>Mission Planner Link</strong>
              <small>{health.bridge?.online ? "Bridge online" : "Bridge offline"}</small>
            </span>
          </div>
          <div className="connection-meta">
            <span>Telemetry {health.stale ? "STALE" : "LIVE"}</span>
            <span>Vehicle {health.connected ? "CONNECTED" : "STANDBY"}</span>
          </div>
        </div>
      </header>
      <main className="main-content">{children}</main>
      <StatusBar health={health} telemetry={telemetry} />
    </div>
  );
}

export default AppShell;
