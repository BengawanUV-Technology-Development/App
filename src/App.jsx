import { useState } from "react";
import "./App.css";
import AppShell from "./components/layout/AppShell";
import { useTelemetry } from "./hooks/useTelemetry";
import DashboardView from "./views/DashboardView";
import LogsView from "./views/LogsView";
import { apiPost, clearOperatorToken, setOperatorToken } from "./services/api";

function OperatorSessionGate({ onAuthenticated }) {
  const [token, setToken] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const submit = async (event) => {
    event.preventDefault();
    if (!token.trim()) return;
    setLoading(true);
    setError("");
    setOperatorToken(token);
    const result = await apiPost("/api/v1/session/verify");
    setLoading(false);
    if (!result.ok) {
      clearOperatorToken();
      setError(result.error || "Operator token rejected");
      return;
    }
    onAuthenticated();
  };

  return (
    <main className="operator-session-gate">
      <form onSubmit={submit}>
        <span>BENGAWAN UAV</span>
        <h1>Operator session</h1>
        <p>Enter the ground backend token. It remains only in this application session.</p>
        <input
          type="password"
          autoFocus
          autoComplete="off"
          value={token}
          onChange={(event) => setToken(event.target.value)}
          placeholder="Bearer token"
          aria-label="Operator token"
        />
        <button type="submit" disabled={loading || !token.trim()}>{loading ? "VERIFYING" : "START SESSION"}</button>
        {error ? <small>{error}</small> : null}
      </form>
    </main>
  );
}

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
  const [authenticated, setAuthenticated] = useState(false);
  return authenticated ? <AuthenticatedApp /> : <OperatorSessionGate onAuthenticated={() => setAuthenticated(true)} />;
}

export default App;
