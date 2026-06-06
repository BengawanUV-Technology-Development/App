import { lazy, Suspense, useMemo, useState } from "react";
import ArmDisarmButton from "../components/command/ArmDisarmButton";
import FlightModeGrid from "../components/command/FlightModeGrid";
import Badge from "../components/common/Badge";
import AttitudeIndicator from "../components/hud/AttitudeIndicator";
import HeadingIndicator from "../components/hud/HeadingIndicator";
import { useCommand } from "../hooks/useCommand";

const AircraftModel3D = lazy(() => import("../components/map/AircraftModel3D"));

function formatNumber(value, digits = 1, fallback = "-") {
  return value === null || value === undefined ? fallback : Number(value).toFixed(digits);
}

function formatCoordinate(value, digits = 4) {
  return value === null || value === undefined ? "-" : Number(value).toFixed(digits);
}

function formatBattery(value) {
  return value === null || value === undefined ? "-" : `${Number(value).toFixed(0)}%`;
}

function formatAttitude(value) {
  return value === null || value === undefined ? "-" : `${Number(value).toFixed(1)} deg`;
}

function formatTime(value) {
  return value ? new Date(value * 1000).toLocaleTimeString() : "--:--:--";
}

function DashboardView({ health, telemetry, statusText, isRefreshing, onRefresh }) {
  const command = useCommand();
  const modeCommand = useCommand();
  const [eventLog, setEventLog] = useState([]);

  const pushEvent = (tone, text) => {
    setEventLog((items) => [{ tone, text, ts: Date.now() / 1000 }, ...items].slice(0, 80));
  };

  const runCommand = async (path, label, body = null) => {
    pushEvent("info", `PENDING ${label}`);
    const result = await command.execute(path, label, body);
    const refreshed = await onRefresh();
    if (result.ok) {
      pushEvent("ok", `OK ${label}: ${result.data?.message || "accepted"}`);
    } else {
      pushEvent("danger", `FAIL ${label}: ${result.error || "unknown error"}`);
    }
    if (refreshed?.error) {
      pushEvent("warn", `Refresh after ${label}: ${refreshed.error}`);
    }
  };

  const setFlightMode = async (mode) => {
    const beforeMode = telemetry.flight_mode || "-";
    pushEvent("info", `PENDING mode ${mode} (current ${beforeMode})`);
    const result = await modeCommand.execute("/api/v1/commands/set-flight-mode", `flight mode ${mode}`, { mode });
    const refreshed = await onRefresh();
    const actualMode = refreshed?.telemetry?.flight_mode || telemetry.flight_mode || "-";
    if (result.ok) {
      pushEvent("ok", `OK mode ${mode}: FC reports ${actualMode}`);
    } else {
      pushEvent("danger", `FAIL mode ${mode}: ${result.error || "unknown error"} (FC reports ${actualMode})`);
    }
  };

  const alerts = useMemo(() => {
    const items = [
      { tone: "info", text: `Backend: ${health.status || "OFFLINE"}` },
      { tone: health.connected ? "ok" : "warn", text: health.connected ? "Mission Planner telemetry active" : statusText },
      { tone: telemetry.armed ? "danger" : "info", text: telemetry.armed ? "System armed" : "System disarmed" },
      { tone: health.gps_valid ? "ok" : "warn", text: health.gps_valid ? "GPS position valid" : "Waiting for valid GPS position" },
    ];

    if (health.error) items.unshift({ tone: "danger", text: health.error });
    if (telemetry.error) items.unshift({ tone: "danger", text: telemetry.error });
    if (command.status !== "-") items.unshift({ tone: "info", text: command.status });
    if (modeCommand.status !== "-") items.unshift({ tone: "info", text: modeCommand.status });
    return [...eventLog, ...items].slice(0, 80);
  }, [command.status, eventLog, health.connected, health.error, health.status, modeCommand.status, statusText, telemetry.armed, telemetry.error]);

  const hasGps = telemetry.lat !== null && telemetry.lat !== undefined && telemetry.lng !== null && telemetry.lng !== undefined;

  return (
    <section className="tactical-layout">
      <aside className="tactical-left">
        <div className="mini-pfd">
          <AttitudeIndicator rollDeg={telemetry.roll_deg} pitchDeg={telemetry.pitch_deg} />
          <HeadingIndicator headingDeg={telemetry.heading_deg ?? telemetry.yaw_deg} />
        </div>

        <div className="side-actions">
          <ArmDisarmButton
            isArmed={Boolean(telemetry.armed)}
            isConnected={Boolean(health.connected)}
            onArm={() => runCommand("/api/v1/commands/arm", "arm")}
            onDisarm={() => runCommand("/api/v1/commands/disarm", "disarm")}
          />
        </div>

        <div className="side-section">
          <div className="side-title">Flight Modes</div>
          <FlightModeGrid currentMode={telemetry.flight_mode} isConnected={Boolean(health.connected)} onSetMode={setFlightMode} />
        </div>

        <div className="mission-progress-panel">
          <span>Showcase Scope</span>
          <strong>FC + Telemetry: {health.connected ? "LIVE" : "STANDBY"}</strong>
          <small>Parameter tuning: Mission Planner</small>
          <small>Vision payload: Jetson Orin Super</small>
        </div>
      </aside>

      <main className="tactical-center">
        <section className="camera-panel vision-panel">
          <div className="camera-readout">
            JETSON ORIN SUPER | CAM 1 | SAR DETECTION | LAT {formatCoordinate(telemetry.lat, 5)} LON {formatCoordinate(telemetry.lng, 5)}
          </div>
          <div className="vision-frame">
            <div className="flood-zone flood-zone-a" />
            <div className="flood-zone flood-zone-b" />
            <div className="detection-box detection-primary">
              <span>VICTIM CANDIDATE</span>
              <strong>0.87</strong>
            </div>
            <div className="detection-box detection-secondary">
              <span>DEBRIS / RAFT</span>
              <strong>0.64</strong>
            </div>
            <div className="vision-reticle" />
            <div className="vision-caption">LIVE VIDEO FEED PLACEHOLDER</div>
          </div>
        </section>

        <section className="map-panel-tactical sar-map-panel">
          <div className="map-grid-overlay" />
          <div className="map-route">
            <i />
            <i />
            <i />
          </div>
          <div className="map-poi victim-poi">
            <span />
          </div>
          <div className="aircraft-marker" aria-label="Aircraft attitude marker">
            <Suspense fallback={<div className="aircraft-model-loading" />}>
              <AircraftModel3D
                headingDeg={telemetry.heading_deg ?? telemetry.yaw_deg}
                rollDeg={telemetry.roll_deg}
                pitchDeg={telemetry.pitch_deg}
              />
            </Suspense>
          </div>
          <div className="map-coordinate-strip">
            <strong>{hasGps ? `${formatCoordinate(telemetry.lat, 6)}, ${formatCoordinate(telemetry.lng, 6)}` : "GPS LOCK PENDING"}</strong>
            <span>HDG {formatNumber(telemetry.heading_deg ?? telemetry.yaw_deg, 0)} | ALT {formatNumber(telemetry.alt)} m</span>
          </div>
        </section>
      </main>

      <aside className="tactical-right">
        <div className="top-status-row">
          <Badge tone="warning">MODE: {telemetry.flight_mode || "-"}</Badge>
          <Badge tone={telemetry.armed ? "danger" : "success"}>SYS: {telemetry.armed ? "ARMED" : "DISARMED"}</Badge>
        </div>

        <section className="readout-panel">
          <h3>Flight Controller</h3>
          <dl>
            <div><dt>MODE</dt><dd>{telemetry.flight_mode || "-"}</dd></div>
            <div><dt>ALT (AGL)</dt><dd>{formatNumber(telemetry.alt)} m</dd></div>
            <div><dt>GND SPEED</dt><dd>{formatNumber(telemetry.groundspeed_m_s)} m/s</dd></div>
            <div><dt>V/S</dt><dd>{formatNumber(telemetry.v_speed_m_s)} m/s</dd></div>
            <div><dt>BAT</dt><dd>{formatBattery(telemetry.battery_percent)}</dd></div>
            <div><dt>GPS</dt><dd>{hasGps ? "3D Fix" : "-"}</dd></div>
          </dl>
        </section>

        <section className="readout-panel">
          <h3>Telemetry / Controller</h3>
          <dl>
            <div><dt>ROLL</dt><dd>{formatAttitude(telemetry.roll_deg)}</dd></div>
            <div><dt>PITCH</dt><dd>{formatAttitude(telemetry.pitch_deg)}</dd></div>
            <div><dt>YAW</dt><dd>{formatAttitude(telemetry.yaw_deg)}</dd></div>
            <div><dt>HEADING</dt><dd>{formatAttitude(telemetry.heading_deg)}</dd></div>
            <div><dt>LINK</dt><dd>{health.connected ? "ACTIVE" : "STANDBY"}</dd></div>
            <div><dt>RC</dt><dd>MONITORING</dd></div>
          </dl>
        </section>

        <section className="readout-panel vision-status-panel">
          <h3>Vision Payload</h3>
          <dl>
            <div><dt>DEVICE</dt><dd>JETSON ORIN</dd></div>
            <div><dt>MODEL</dt><dd>SAR DETECT</dd></div>
            <div><dt>STREAM</dt><dd>PLACEHOLDER</dd></div>
            <div><dt>DETECTIONS</dt><dd>2 CANDIDATES</dd></div>
          </dl>
        </section>

        <section className="alerts-panel">
          <h3>System Alerts Log</h3>
          <div className="alerts-list">
            {alerts.map((alert, index) => (
              <div key={`${alert.text}-${index}`} className={`alert-line ${alert.tone}`}>
                <time>[{formatTime(alert.ts || health.last_update || telemetry.last_update)}]</time>
                <span>{alert.text}</span>
              </div>
            ))}
            <div className="alert-line info">
              <time>[--:--:--]</time>
              <span>Camera/map placeholders ready</span>
            </div>
          </div>
        </section>
      </aside>
    </section>
  );
}

export default DashboardView;
