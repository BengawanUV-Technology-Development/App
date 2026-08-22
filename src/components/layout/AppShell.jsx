import Sidebar from "./Sidebar";
import StatusBar from "./StatusBar";

function AppShell({ activeView, onNavigate, health, telemetry, children }) {
  const linkActive = Boolean(health?.backend_online && !health?.stale);

  return (
    <div className="app-shell">
      <header className="top-frame">
        <Sidebar activeView={activeView} onNavigate={onNavigate} />
        <div className="connection-panel">
          <div className="connection-summary">
            <span className={`connection-dot ${linkActive ? "is-online" : ""}`} />
            <span>
              <strong>MAVLink telemetry</strong>
              <small>{linkActive ? "UDP mirror · 14551" : "Backend offline"}</small>
            </span>
          </div>
          <div className="connection-meta">
            <span>Telemetry {linkActive ? "ACTIVE" : health?.status || "OFFLINE"}</span>
            <span>Vehicle {health?.connected ? "CONNECTED" : "STANDBY"}</span>
          </div>
        </div>
      </header>
      <main className="main-content">{children}</main>
      <StatusBar health={health} telemetry={telemetry} />
    </div>
  );
}

export default AppShell;
