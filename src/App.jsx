import { useState } from "react";
import "./App.css";
import AppShell from "./components/layout/AppShell";
import { useTelemetry } from "./hooks/useTelemetry";
import ConfigView from "./views/ConfigView";
import DashboardView from "./views/DashboardView";
import LogsView from "./views/LogsView";
import MissionView from "./views/MissionView";

function App() {
  const [activeView, setActiveView] = useState("dashboard");
  const { health, telemetry, statusText, isRefreshing, refresh } = useTelemetry();

  const renderView = () => {
    if (activeView === "config") {
      return <ConfigView />;
    }

    if (activeView === "mission") {
      return <MissionView isConnected={health.connected} onTelemetryRefresh={refresh} />;
    }

    if (activeView === "logs") {
      return <LogsView />;
    }

    return (
      <DashboardView
        health={health}
        telemetry={telemetry}
        statusText={statusText}
        isRefreshing={isRefreshing}
        onRefresh={refresh}
      />
    );
  };

  return (
    <AppShell activeView={activeView} onNavigate={setActiveView} health={health} telemetry={telemetry} onRefresh={refresh}>
      {renderView()}
    </AppShell>
  );
}

export default App;
