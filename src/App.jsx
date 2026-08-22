import { useState } from "react";
import "./App.css";
import AppShell from "./components/layout/AppShell";
import { useTelemetry } from "./hooks/useTelemetry";
import DashboardView from "./views/DashboardView";
import LogsView from "./views/LogsView";

function AuthenticatedApp() {
  const [activeView, setActiveView] = useState("dashboard");
  const { health, telemetry, statusText, isRefreshing, refresh } = useTelemetry();
  const view = activeView === "logs" ? <LogsView /> : (
    <DashboardView health={health} telemetry={telemetry} statusText={statusText} isRefreshing={isRefreshing} onRefresh={refresh} />
  );
  return (
    <AppShell activeView={activeView} onNavigate={setActiveView} health={health} telemetry={telemetry}>
      {view}
    </AppShell>
  );
}

function App() {
  return <AuthenticatedApp />;
}

export default App;
