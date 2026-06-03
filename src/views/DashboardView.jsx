import { useMemo, useState } from "react";
import ArmDisarmButton from "../components/command/ArmDisarmButton";
import FlightModeGrid from "../components/command/FlightModeGrid";
import QuickActions from "../components/command/QuickActions";
import TakeoffPanel from "../components/command/TakeoffPanel";
import Badge from "../components/common/Badge";
import AttitudeIndicator from "../components/hud/AttitudeIndicator";
import HeadingIndicator from "../components/hud/HeadingIndicator";
import { useCommand } from "../hooks/useCommand";

function formatNumber(value, digits = 1, fallback = "-") {
  return value === null || value === undefined ? fallback : Number(value).toFixed(digits);
}

function formatCoordinate(value, digits = 4) {
  return value === null || value === undefined ? "-" : Number(value).toFixed(digits);
}

function formatBattery(value) {
  return value === null || value === undefined ? "-" : `${Number(value).toFixed(0)}%`;
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
    const result = await modeCommand.execute("/command/set_flight_mode", `flight mode ${mode}`, { mode });
    const refreshed = await onRefresh();
    const actualMode = refreshed?.telemetry?.flight_mode || telemetry.flight_mode || "-";
    if (result.ok) {
      pushEvent("ok", `OK mode ${mode}: FC reports ${actualMode}`);
    } else {
      pushEvent("danger", `FAIL mode ${mode}: ${result.error || "unknown error"} (FC reports ${actualMode})`);
    }
  };

  const reboot = async () => {
    pushEvent("info", "PENDING reboot");
    const result = await modeCommand.execute("/command/reboot", "reboot");
    await onRefresh();
    pushEvent(result.ok ? "ok" : "danger", `${result.ok ? "OK" : "FAIL"} reboot: ${result.data?.message || result.error || "-"}`);
  };

  const alerts = useMemo(() => {
    const items = [
      { tone: "info", text: `Backend: ${health.status || "OFFLINE"}` },
      { tone: health.connected ? "ok" : "warn", text: health.connected ? "MAVLink active" : statusText },
      { tone: telemetry.armed ? "danger" : "info", text: telemetry.armed ? "System armed" : "System disarmed" },
    ];

    if (health.error) items.unshift({ tone: "danger", text: health.error });
    if (telemetry.error) items.unshift({ tone: "danger", text: telemetry.error });
    if (command.status !== "-") items.unshift({ tone: "info", text: command.status });
    if (modeCommand.status !== "-") items.unshift({ tone: "info", text: modeCommand.status });
    return [...eventLog, ...items].slice(0, 80);
  }, [command.status, eventLog, health.connected, health.error, health.status, modeCommand.status, statusText, telemetry.armed, telemetry.error]);

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
            onArm={() => runCommand("/command/arm", "arm")}
            onDisarm={() => runCommand("/command/disarm", "disarm")}
          />
          <QuickActions isConnected={Boolean(health.connected)} isArmed={Boolean(telemetry.armed)} onReboot={reboot} />
        </div>

        <div className="side-section">
          <div className="side-title">Flight Modes</div>
          <FlightModeGrid currentMode={telemetry.flight_mode} isConnected={Boolean(health.connected)} onSetMode={setFlightMode} />
        </div>

        <div className="side-section">
          <div className="side-title">Takeoff / Land</div>
          <TakeoffPanel
            isConnected={Boolean(health.connected)}
            isArmed={Boolean(telemetry.armed)}
            onSetTakeoffAltitude={(altitude) => runCommand("/command/set_takeoff_altitude", "set takeoff altitude", { altitude_m: altitude })}
            onTakeoff={(altitude) => runCommand("/command/takeoff", "takeoff", { altitude_m: altitude })}
            onLand={() => runCommand("/command/land", "land")}
          />
        </div>

        <div className="mission-progress-panel">
          <span>Mission Progress</span>
          <strong>Target WP: -- / --</strong>
          <small>ETA: --</small>
          <small>Dist: -- m</small>
        </div>
      </aside>

      <main className="tactical-center">
        <section className="camera-panel">
          <div className="camera-readout">
            CAM 1 | 1080p 60fps | LAT: {formatCoordinate(telemetry.lat)} LON: {formatCoordinate(telemetry.lng)}
          </div>
          <div className="camera-placeholder">LIVE VIDEO FEED PLACEHOLDER</div>
        </section>

        <section className="map-panel-tactical">
          <div className="map-crosshair" />
          <span>FLIGHT MAP VIEW PLACEHOLDER</span>
        </section>
      </main>

      <aside className="tactical-right">
        <div className="top-status-row">
          <Badge tone="warning">MODE: {telemetry.flight_mode || "-"}</Badge>
          <Badge tone={telemetry.armed ? "danger" : "success"}>SYS: {telemetry.armed ? "ARMED" : "DISARMED"}</Badge>
        </div>

        <section className="readout-panel">
          <h3>Fluid Dynamics</h3>
          <dl>
            <div><dt>ALT (AGL)</dt><dd>{formatNumber(telemetry.alt)} m</dd></div>
            <div><dt>AIRSPEED</dt><dd>{formatNumber(telemetry.airspeed_m_s)} m/s</dd></div>
            <div><dt>GND SPEED</dt><dd>{formatNumber(telemetry.groundspeed_m_s)} m/s</dd></div>
            <div><dt>V/S</dt><dd>{formatNumber(telemetry.v_speed_m_s)} m/s</dd></div>
            <div><dt>BAT</dt><dd>{formatBattery(telemetry.battery_percent)}</dd></div>
            <div><dt>GPS</dt><dd>{telemetry.lat === null || telemetry.lng === null ? "-" : "3D Fix"}</dd></div>
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
