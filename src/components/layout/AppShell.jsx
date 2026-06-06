import Sidebar from "./Sidebar";
import StatusBar from "./StatusBar";

function AppShell({ activeView, onNavigate, health, telemetry, children }) {
  return (
    <div className="app-shell">
      <header className="top-frame">
        <Sidebar activeView={activeView} onNavigate={onNavigate} />
        <div className="connection-panel">
          <div className="connection-summary">
            <strong>Mission Planner Bridge</strong>
            <span>{health.bridge?.online ? "ONLINE" : "OFFLINE"}</span>
          </div>
          <div className="connection-meta">
            <span>Telemetry {health.stale ? "STALE" : "LIVE"}</span>
            <span>WebSocket {health.websocket || "DISCONNECTED"}</span>
          </div>
        </div>
      </header>
      <main className="main-content">{children}</main>
      <StatusBar health={health} telemetry={telemetry} />
    </div>
  );
}

export default AppShell;
