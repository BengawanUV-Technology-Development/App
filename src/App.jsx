import { useEffect, useState } from "react";
import "./App.css";

const API_BASE = "http://localhost:5001";

function App() {
  const [health, setHealth] = useState({ connected: false, status: "OFFLINE", error: null, last_update: null, system_address: "-" });
  const [telemetry, setTelemetry] = useState({
    lat: null,
    lng: null,
    alt: null,
    alt_amsl: null,
    armed: null,
    flight_mode: null,
    battery_percent: null,
    roll_deg: null,
    pitch_deg: null,
    yaw_deg: null,
    heading_deg: null,
    airspeed_m_s: null,
    groundspeed_m_s: null,
    v_speed_m_s: null,
    last_update: null,
    error: null,
  });
  const [statusText, setStatusText] = useState("Menghubungkan ke backend Python...");
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [modeStatus, setModeStatus] = useState("-");
  const [missionDraft, setMissionDraft] = useState(`[
  {
    "seq": 0,
    "latitude_deg": -6.2001,
    "longitude_deg": 106.8166,
    "relative_altitude_m": 15,
    "speed_m_s": 5,
    "is_fly_through": false
  }
]`);
  const [missionStatus, setMissionStatus] = useState("-");
  const [missionProgress, setMissionProgress] = useState("-");

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
      // Clear status immediately to show something is happening
      setModeStatus("Sending reboot request...");
      setStatusText("FC is rebooting...");

      const response = await fetch(`${API_BASE}/command/reboot`, {
        method: "POST",
      });

      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.error || payload.message || "Gagal reboot vehicle");
      }

      setModeStatus("Reboot request success. Waiting for FC to reconnect...");
      // Also clear health state locally for immediate feedback
      setHealth((previous) => ({ ...previous, connected: false, status: "REBOOTING" }));

      await fetchTelemetry();
    } catch (error) {
      setModeStatus(String(error));
      console.error("Error rebooting vehicle:", error);
    }
  };

  const uploadMission = async () => {
    try {
      const waypoints = JSON.parse(missionDraft);
      const response = await fetch(`${API_BASE}/mission/upload`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ waypoints }),
      });

      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.error || payload.message || "Gagal upload mission");
      }

      setMissionStatus(payload.message || "Mission uploaded");
      await fetchTelemetry();
    } catch (error) {
      setMissionStatus(String(error));
      console.error("Error uploading mission:", error);
    }
  };

  const runMissionCommand = async (path, label) => {
    try {
      const response = await fetch(`${API_BASE}${path}`, { method: "POST" });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.error || payload.message || `Gagal ${label}`);
      }

      setMissionStatus(payload.message || `${label} requested`);
      await fetchTelemetry();
    } catch (error) {
      setMissionStatus(String(error));
      console.error(`Error ${label}:`, error);
    }
  };

  const refreshMissionProgress = async () => {
    try {
      const response = await fetch(`${API_BASE}/mission/progress`);
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.error || payload.message || "Gagal ambil progress mission");
      }

      setMissionProgress(
        payload.current === undefined || payload.total === undefined ? "-" : `${payload.current}/${payload.total}`,
      );
      setMissionStatus("Mission progress diperbarui");
    } catch (error) {
      setMissionStatus(String(error));
      console.error("Error reading mission progress:", error);
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
      if (healthData.status === "REBOOTING") {
        setStatusText("FC is rebooting...");
      } else if (healthData.connected) {
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

        <div className={`status-pill ${health.status === "REBOOTING" ? "is-rebooting" : health.connected ? "is-online" : "is-waiting"}`}>
          <span className="status-dot" />
          <div>
            <strong>{health.status === "REBOOTING" ? "Rebooting" : health.connected ? "Connected" : "Waiting"}</strong>
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
              <span>Connection Status</span>
              <strong>{health.status || "OFFLINE"}</strong>
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
          <button onClick={() => setFlightMode("Q_STABILIZE")} disabled title="Belum didukung backend">Q_STABILIZE</button>
          <button onClick={rebootVehicle} disabled={!health.connected || telemetry.armed}>
            Reboot
          </button>
        </div>
        <p className="hero-copy compact">Status mode: {modeStatus}</p>
      </section>

      <section className="panel mission-panel">
        <div className="panel-header mission-header">
          <div>
            <p className="panel-label">Mission</p>
            <h2>Upload waypoint sederhana</h2>
            <p className="hero-copy compact">
              UI ini sengaja minimal supaya backend bisa dicoba sekarang, lalu nanti frontend bisa ganti ke form yang lebih lengkap.
            </p>
          </div>
          <div className="mission-meta">
            <span>Upload: {missionStatus}</span>
            <span>Progress: {missionProgress}</span>
          </div>
        </div>

        <div className="mission-layout">
          <label className="mission-editor">
            <span>Waypoint JSON</span>
            <textarea
              value={missionDraft}
              onChange={(event) => setMissionDraft(event.target.value)}
              spellCheck={false}
            />
          </label>

          <div className="mission-actions">
            <button onClick={uploadMission} disabled={!health.connected}>Upload</button>
            <button onClick={() => runMissionCommand("/mission/start", "start mission")} disabled={!health.connected}>
              Start
            </button>
            <button onClick={() => runMissionCommand("/mission/pause", "pause mission")} disabled={!health.connected}>
              Pause
            </button>
            <button onClick={() => runMissionCommand("/mission/clear", "clear mission")} disabled={!health.connected}>
              Clear
            </button>
            <button onClick={refreshMissionProgress} disabled={!health.connected}>
              Refresh Progress
            </button>
          </div>
        </div>
      </section>
    </main>
  );
}

export default App;