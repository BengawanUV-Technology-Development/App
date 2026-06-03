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
  const [commandStatus, setCommandStatus] = useState("-");
  const [takeoffAlt, setTakeoffAlt] = useState("10");
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

  const executeCommand = async (path, label, body = null) => {
    try {
      setCommandStatus(`Sending ${label}...`);
      const options = { method: "POST" };
      if (body) {
        options.headers = { "Content-Type": "application/json" };
        options.body = JSON.stringify(body);
      }
      const response = await fetch(`${API_BASE}${path}`, options);
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.error || payload.message || `Gagal ${label}`);
      }
      setCommandStatus(payload.message || `${label} berhasil`);
      await fetchTelemetry();
    } catch (error) {
      setCommandStatus(String(error));
      console.error(`Error ${label}:`, error);
    }
  };

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
            <div className="hud-divider">HUD Data</div>
            <div>
              <span>Roll</span>
              <strong>{formatNumber(telemetry.roll_deg, "°")}</strong>
            </div>
            <div>
              <span>Pitch</span>
              <strong>{formatNumber(telemetry.pitch_deg, "°")}</strong>
            </div>
            <div>
              <span>Yaw</span>
              <strong>{formatNumber(telemetry.yaw_deg, "°")}</strong>
            </div>
            <div>
              <span>Heading</span>
              <strong>{formatNumber(telemetry.heading_deg, "°")}</strong>
            </div>
            <div>
              <span>Ground Speed</span>
              <strong>{formatNumber(telemetry.groundspeed_m_s, " m/s")}</strong>
            </div>
            <div>
              <span>Vertical Speed</span>
              <strong>{formatNumber(telemetry.v_speed_m_s, " m/s")}</strong>
            </div>
          </div>
        </article>
      </section>

      <section className="panel command-panel">
        <div className="panel-header">
          <div>
            <p className="panel-label">Vehicle Command</p>
            <h2>Arm, Takeoff & Land</h2>
          </div>
        </div>
        <div className="command-controls">
          <div className="command-row">
            <button onClick={() => executeCommand("/command/arm", "arm")} disabled={!health.connected || telemetry.armed}>
              Arm
            </button>
            <button onClick={() => executeCommand("/command/disarm", "disarm")} disabled={!health.connected || !telemetry.armed}>
              Disarm
            </button>
          </div>
          <div className="command-row">
            <label className="takeoff-input">
              <span>Altitude (m)</span>
              <input
                type="number"
                min="2"
                max="50"
                step="1"
                value={takeoffAlt}
                onChange={(e) => setTakeoffAlt(e.target.value)}
              />
            </label>
            <button
              onClick={() => executeCommand("/command/takeoff", "takeoff", { altitude_m: parseFloat(takeoffAlt) })}
              disabled={!health.connected || !telemetry.armed}
            >
              Takeoff
            </button>
            <button onClick={() => executeCommand("/command/land", "land")} disabled={!health.connected}>
              Land
            </button>
          </div>
          <p className="hero-copy compact">Command: {commandStatus}</p>
        </div>
      </section>

      <section className="panel action-panel">
        <div>
          <p className="panel-label">Flight Mode</p>
          <h2>Mode switching</h2>
          <p className="hero-copy compact">
            Ubah flight mode via ArduPilot direct bypass atau MAVSDK action.
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
            Reboot FC
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