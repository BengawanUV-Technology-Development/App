import Sidebar from "./Sidebar";
import StatusBar from "./StatusBar";
import ConnectionPanel from "../connection/ConnectionPanel";

function AppShell({ activeView, onNavigate, health, telemetry, onRefresh, children }) {
  return (
    <div className="app-shell">
      <header className="top-frame">
        <Sidebar activeView={activeView} onNavigate={onNavigate} />
        <ConnectionPanel health={health} onChanged={onRefresh} />
      </header>
      <main className="main-content">{children}</main>
      <StatusBar health={health} telemetry={telemetry} />
    </div>
  );
}

export default AppShell;
