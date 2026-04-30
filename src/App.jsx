import { useEffect, useState } from "react";
import "./App.css";

const API_BASE = "http://localhost:5001";

function App() {
  const [health, setHealth] = useState({ connected: false, error: null, last_update: null, system_address: "-" });
  const [telemetry, setTelemetry] = useState({
    lat: null,
    lng: null,
    alt: null,
    alt_amsl: null,
    armed: null,
    flight_mode: null,
    battery_percent: null,
    last_update: null,
    error: null,
  });
  const [statusText, setStatusText] = useState("Menghubungkan ke backend Python...");
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [modeStatus, setModeStatus] = useState("-");

  const setFlightMode = async (mode) => {
    try {
      const response = await fetch(`${API_BASE}/command/set_flight_mode`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode }),
      });

      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.error || payload.message || "Gagal mengubah flight mode");
      }

      setModeStatus(payload.message || `Flight mode ${mode} dikirim`);
      await fetchTelemetry();
    } catch (error) {
      setModeStatus(String(error));
      console.error("Error setting flight mode:", error);
    }
  };

  const rebootVehicle = async () => {
    try {
      const response = await fetch(`${API_BASE}/command/reboot`, {
        method: "POST",
      });

      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.error || payload.message || "Gagal reboot vehicle");
      }

      setModeStatus(payload.message || "Reboot requested successfully");
      await fetchTelemetry();
    } catch (error) {
      setModeStatus(String(error));
      console.error("Error rebooting vehicle:", error);
    }
  };

  const fetchTelemetry = async () => {
    setIsRefreshing(true);
    try {
      const [healthResponse, telemetryResponse] = await Promise.all([
        fetch(`${API_BASE}/health`),
        fetch(`${API_BASE}/telemetry`),
      ]);

      if (!healthResponse.ok || !telemetryResponse.ok) {
        throw new Error("Backend response was not ok");
      }

      const healthData = await healthResponse.json();
      const telemetryData = await telemetryResponse.json();

      setHealth(healthData);
      setTelemetry(telemetryData);
      if (healthData.connected) {
        setStatusText("FC terhubung");
      } else if (healthData.error) {
        setStatusText(`Retrying: ${healthData.error}`);
      } else {
        setStatusText("Backend aktif, menunggu heartbeat FC");
      }
    } catch (error) {
      setHealth((previous) => ({ ...previous, connected: false, error: String(error) }));
      setStatusText("Backend Python belum bisa diakses");
      console.error("Error fetching from Python:", error);
    } finally {
      setIsRefreshing(false);
    }
  };

  useEffect(() => {
    fetchTelemetry();
    const interval = setInterval(fetchTelemetry, 1000);
    return () => clearInterval(interval);
  }, []);

  const formatCoordinate = (value) => (value === null || value === undefined ? "-" : value.toFixed(6));
  const formatNumber = (value, suffix = "") => (value === null || value === undefined ? "-" : `${value}${suffix}`);
  const formatBattery = (value) => (value === null || value === undefined ? "-" : `${value.toFixed(1)}%`);

  return (
    <main className="app-shell">
      <section className="hero-panel">
        <div>
          <p className="eyebrow">Mission Planner Lite</p>
          <h1>Ground station desktop untuk FC kamu</h1>
          <p className="hero-copy">
            Tahap pertama fokus ke koneksi, telemetry live, dan fondasi arsitektur yang nanti dipakai untuk arm, takeoff, land, dan mission upload.
          </p>
        </div>

        <div className={`status-pill ${health.connected ? "is-online" : "is-waiting"}`}>
          <span className="status-dot" />
          <div>
            <strong>{health.connected ? "Connected" : "Waiting"}</strong>
            <span>{statusText}</span>
          </div>
        </div>
      </section>

      <section className="grid-layout">
        <article className="panel primary">
          <div className="panel-header">
            <div>
              <p className="panel-label">Connection</p>
              <h2>Backend Python</h2>
            </div>
            <button onClick={fetchTelemetry} disabled={isRefreshing}>
              {isRefreshing ? "Refreshing..." : "Refresh"}
            </button>
          </div>

          <div className="metric-grid">
            <div className="metric-card">
              <span>System Address</span>
              <strong>{health.system_address}</strong>
            </div>
            <div className="metric-card">
              <span>Backend Error</span>
              <strong>{health.error || "None"}</strong>
            </div>
            <div className="metric-card">
              <span>Last Health Update</span>
              <strong>{health.last_update ? new Date(health.last_update * 1000).toLocaleTimeString() : "-"}</strong>
            </div>
            <div className="metric-card">
              <span>Telemetry Error</span>
              <strong>{telemetry.error || "None"}</strong>
            </div>
          </div>
        </article>

        <article className="panel map-panel">
          <p className="panel-label">Telemetry</p>
          <h2>Live vehicle data</h2>
          <div className="telemetry-list">
            <div>
              <span>Latitude</span>
              <strong>{formatCoordinate(telemetry.lat)}</strong>
            </div>
            <div>
              <span>Longitude</span>
              <strong>{formatCoordinate(telemetry.lng)}</strong>
            </div>
            <div>
              <span>Relative Altitude</span>
              <strong>{formatNumber(telemetry.alt, " m")}</strong>
            </div>
            <div>
              <span>AMSL Altitude</span>
              <strong>{formatNumber(telemetry.alt_amsl, " m")}</strong>
            </div>
            <div>
              <span>Armed</span>
              <strong>{telemetry.armed === null ? "-" : telemetry.armed ? "Yes" : "No"}</strong>
            </div>
            <div>
              <span>Flight Mode</span>
              <strong>{telemetry.flight_mode || "-"}</strong>
            </div>
            <div>
              <span>Battery</span>
              <strong>{formatBattery(telemetry.battery_percent)}</strong>
            </div>
            <div>
              <span>Last Telemetry Update</span>
              <strong>{telemetry.last_update ? new Date(telemetry.last_update * 1000).toLocaleTimeString() : "-"}</strong>
            </div>
          </div>
        </article>
      </section>

      <section className="panel action-panel">
        <div>
          <p className="panel-label">MVP 1</p>
          <h2>Action controls</h2>
          <p className="hero-copy compact">
            Backend sekarang bisa menerima command flight mode untuk aksi yang memang didukung MAVSDK.
          </p>
        </div>
        <div className="action-chips">
          <button onClick={() => setFlightMode("FBWA")} disabled={!health.connected}>FBWA</button>
          <button onClick={() => setFlightMode("Q_HOVER")} disabled={!health.connected}>Q_HOVER</button>
          <button onClick={() => setFlightMode("Q_LAND")} disabled={!health.connected}>Q_LAND</button>
          <button onClick={() => setFlightMode("AUTO")} disabled={!health.connected}>AUTO</button>
          <button onClick={() => setFlightMode("MANUAL")} disabled={!health.connected}>MANUAL</button>
          <button onClick={() => setFlightMode("Q_STABILIZE")} disabled={!health.connected}>Q_STABILIZE</button>
          <button onClick={rebootVehicle} disabled={!health.connected || telemetry.armed}>
            Reboot
          </button>
        </div>
        <p className="hero-copy compact">Status mode: {modeStatus}</p>
      </section>
    </main>
  );
}

export default App;