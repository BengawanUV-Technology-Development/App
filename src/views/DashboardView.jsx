import { lazy, Suspense, useMemo, useState } from "react";
import ArmDisarmButton from "../components/command/ArmDisarmButton";
import FlightModeGrid from "../components/command/FlightModeGrid";
import RebootButton from "../components/command/RebootButton";
import Badge from "../components/common/Badge";
import AttitudeIndicator from "../components/hud/AttitudeIndicator";
import HeadingIndicator from "../components/hud/HeadingIndicator";
import { useCommand } from "../hooks/useCommand";
import { useMission } from "../hooks/useMission";
import { useMissionMessages } from "../hooks/useMissionMessages";
import BatteryMonitor from "../components/telemetry/BatteryMonitor";
import EkfVibeBar from "../components/telemetry/EkfVibeBar";
import DataQuick from "../components/telemetry/DataQuick";
import EkfVibeModal from "../components/telemetry/EkfVibeModal";
import FlightRecorderControl from "../components/recording/FlightRecorderControl";
import CameraPreview from "../components/recording/CameraPreview";

const OperationalMap = lazy(() => import("../components/map/OperationalMap"));

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

function formatMissionItem(waypoint) {
  if (!waypoint) return "No active waypoint";
  const seq = waypoint.seq ?? waypoint.index ?? "-";
  const command = waypoint.command_name || "MISSION";
  const alt = waypoint.alt_m === null || waypoint.alt_m === undefined ? "-" : `${Number(waypoint.alt_m).toFixed(0)} m`;
  return `WP ${seq} | ${command} | ${alt}`;
}

function distanceMeters(lat1, lng1, lat2, lng2) {
  if (![lat1, lng1, lat2, lng2].every((value) => Number.isFinite(Number(value)))) return null;
  const radians = (value) => Number(value) * Math.PI / 180;
  const earthRadiusM = 6371000;
  const dLat = radians(lat2 - lat1);
  const dLng = radians(lng2 - lng1);
  const a = Math.sin(dLat / 2) ** 2
    + Math.cos(radians(lat1)) * Math.cos(radians(lat2)) * Math.sin(dLng / 2) ** 2;
  return earthRadiusM * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

function ExpandPanelIcon({ active = false }) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      {active ? (
        <path d="M9 4v5H4M15 4v5h5M9 20v-5H4M15 20v-5h5" />
      ) : (
        <path d="M9 4H4v5M15 4h5v5M9 20H4v-5M15 20h5v-5" />
      )}
    </svg>
  );
}

function normalizeModeName(mode) {
  return String(mode || "").toUpperCase().replaceAll("_", "").replaceAll(" ", "");
}

function missionMessageTone(message) {
  const normalized = String(message || "").toLowerCase();
  if (/(error|fail|failed|loss|bad|critical)/.test(normalized)) return "danger";
  if (/(warn|prearm|unhealthy|waiting|no gps|ekf)/.test(normalized)) return "warn";
  return "info";
}

function DashboardView({ health, telemetry, statusText, isRefreshing, onRefresh }) {
  const command = useCommand();
  const modeCommand = useCommand();
  const missionCommand = useCommand();
  const { mission, refreshMission } = useMission();
  const { missionMessages } = useMissionMessages();
  const [eventLog, setEventLog] = useState([]);
  const [selectedWaypointSeq, setSelectedWaypointSeq] = useState("1");
  const [centerMode, setCenterMode] = useState("balanced");
  const [isEkfModalOpen, setIsEkfModalOpen] = useState(false);

  const pushEvent = (tone, text) => {
    setEventLog((items) => [{ tone, text, ts: Date.now() / 1000 }, ...items].slice(0, 40));
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
    refreshMission();
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

  const startMission = async () => {
    const checks = [
      { ok: Boolean(health.connected), message: "Mission Planner telemetry belum aktif" },
      { ok: Boolean(health.gps_valid), message: "GPS belum valid" },
      { ok: Number(mission.count || 0) > 0, message: "Mission/waypoint belum terbaca" },
      { ok: Boolean(telemetry.armed), message: "Vehicle belum armed" },
    ];
    const failed = checks.filter((check) => !check.ok).map((check) => check.message);
    if (failed.length > 0) {
      pushEvent("warn", `MISSION HOLD: ${failed.join(", ")}`);
      return;
    }

    const currentMode = telemetry.flight_mode || "-";
    if (normalizeModeName(currentMode) === "AUTO") {
      pushEvent("ok", `MISSION already AUTO: ${formatMissionItem(mission.current_waypoint)}`);
      return;
    }

    pushEvent("info", `PENDING start mission AUTO from ${currentMode}`);
    const result = await missionCommand.execute("/api/v1/commands/set-flight-mode", "start mission AUTO", { mode: "AUTO" });
    const refreshed = await onRefresh();
    await refreshMission();
    const actualMode = refreshed?.telemetry?.flight_mode || telemetry.flight_mode || "-";
    if (result.ok) {
      pushEvent("ok", `OK start mission: FC reports ${actualMode}`);
    } else {
      pushEvent("danger", `FAIL start mission: ${result.error || "unknown error"} (FC reports ${actualMode})`);
    }
  };

  const setCurrentWaypoint = async (seq, label = null) => {
    const nextSeq = Number(seq);
    if (!Number.isInteger(nextSeq) || nextSeq < 0) {
      pushEvent("warn", "SET WP HOLD: waypoint harus angka 0 atau lebih");
      return;
    }
    if (Number(mission.count || 0) <= 0) {
      pushEvent("warn", "SET WP HOLD: mission belum terbaca");
      return;
    }
    if (nextSeq >= Number(mission.count || 0)) {
      pushEvent("warn", `SET WP HOLD: WP ${nextSeq} di luar range 0-${Number(mission.count || 0) - 1}`);
      return;
    }

    const commandLabel = label || `set WP ${nextSeq}`;
    pushEvent("info", `PENDING ${commandLabel}`);
    const result = await missionCommand.execute("/api/v1/commands/set-current-waypoint", commandLabel, { seq: nextSeq });
    await onRefresh();
    await refreshMission();
    if (result.ok) {
      pushEvent("ok", `OK ${commandLabel}: ${result.data?.message || `WP ${nextSeq}`}`);
    } else {
      pushEvent("danger", `FAIL ${commandLabel}: ${result.error || "unknown error"}`);
    }
  };

  const alerts = useMemo(() => {
    const mpItems = (missionMessages.messages || []).map((item) => ({
      tone: missionMessageTone(item.message),
      text: `MP: ${item.message}`,
      ts: item.timestamp || missionMessages.timestamp,
    }));
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
    if (missionCommand.status !== "-") items.unshift({ tone: "info", text: missionCommand.status });
    if (missionMessages.error) items.unshift({ tone: "warn", text: `MP messages: ${missionMessages.error}` });
    return [...eventLog, ...items, ...mpItems].slice(0, 80);
  }, [command.status, eventLog, health.connected, health.error, health.status, missionCommand.status, missionMessages.error, missionMessages.messages, missionMessages.timestamp, modeCommand.status, statusText, telemetry.armed, telemetry.error]);

  const hasGps = telemetry.lat !== null && telemetry.lat !== undefined && telemetry.lng !== null && telemetry.lng !== undefined;
  const missionPrecheck = [
    { label: "Link aktif", ok: Boolean(health.connected) },
    { label: "GPS valid", ok: Boolean(health.gps_valid) },
    { label: "Mission loaded", ok: Number(mission.count || 0) > 0 },
    { label: "Vehicle armed", ok: Boolean(telemetry.armed) },
  ];
  const missionReady = missionPrecheck.every((check) => check.ok);
  const selectableWaypoints = (mission.waypoints || []).filter((waypoint) => waypoint.error === null || waypoint.error === undefined);
  const activeWaypoint = mission.current_waypoint;
  const waypointDistance = activeWaypoint?.has_position
    ? distanceMeters(telemetry.lat, telemetry.lng, activeWaypoint.lat, activeWaypoint.lng)
    : null;

  return (
    <section className="tactical-layout">
      <aside className="tactical-left">
        <div className="mini-pfd">
          <AttitudeIndicator rollDeg={telemetry.roll_deg} pitchDeg={telemetry.pitch_deg} />
          <HeadingIndicator headingDeg={telemetry.heading_deg ?? telemetry.yaw_deg} />
        </div>

        <div className="side-title-row">
          <div>
            <span>Vehicle Control</span>
            <strong>{telemetry.flight_mode || "STANDBY"}</strong>
          </div>
          <Badge tone={telemetry.armed ? "danger" : "success"}>{telemetry.armed ? "ARMED" : "SAFE"}</Badge>
        </div>

        <div className="side-actions primary-actions">
          <ArmDisarmButton
            isArmed={Boolean(telemetry.armed)}
            isConnected={Boolean(health.connected)}
            onArm={() => runCommand("/api/v1/commands/arm", "arm")}
            onDisarm={() => runCommand("/api/v1/commands/disarm", "disarm")}
          />
          <button type="button" className="mission-start-button" onClick={startMission} disabled={!health.connected || missionCommand.isLoading}>
            START AUTO
          </button>
        </div>

        <div className="mission-progress-panel">
          <div className="mission-panel-heading">
            <span>Mission Progress</span>
            <small className={missionReady ? "mission-ready-dot" : "mission-hold-dot"}>{missionReady ? "READY" : "HOLD"}</small>
          </div>
          <div className="mission-distance-readout">
            <span>Distance to waypoint {activeWaypoint?.seq ?? activeWaypoint?.index ?? "-"}</span>
            <strong>{waypointDistance === null ? "-" : Math.round(waypointDistance)} <small>m</small></strong>
          </div>
          <small>{formatMissionItem(activeWaypoint)}</small>
          <small>Mission items: {mission.count || 0} | Positioned: {mission.positioned_count || 0}</small>
          <small>Last sync: {formatTime(mission.timestamp)}</small>
          {mission.error ? <small className="mission-progress-error">{mission.error}</small> : null}
        </div>

        <details className="advanced-controls">
          <summary>Advanced Controls</summary>
          <div className="advanced-controls-body">
            <div className="side-section">
              <div className="side-title">Flight Modes</div>
              <FlightModeGrid currentMode={telemetry.flight_mode} isConnected={Boolean(health.connected)} onSetMode={setFlightMode} />
            </div>
            <div className="mission-precheck-row">
              {missionPrecheck.map((check) => (
                <small key={check.label} className={check.ok ? "precheck-ok" : "precheck-warn"}>
                  <span>{check.ok ? "OK" : "WAIT"}</span>
                  {check.label}
                </small>
              ))}
            </div>
            <div className="mission-control-row">
              <button type="button" className="mission-refresh-button" onClick={refreshMission} disabled={!health.connected}>
                REFRESH WP
              </button>
              <RebootButton
                isConnected={Boolean(health.connected)}
                isArmed={Boolean(telemetry.armed)}
                onReboot={() => runCommand("/api/v1/commands/reboot", "reboot FC")}
              />
            </div>
            <div className="mission-setwp-row">
              <select
                value={selectedWaypointSeq}
                onChange={(event) => setSelectedWaypointSeq(event.target.value)}
                disabled={!health.connected || selectableWaypoints.length === 0}
              >
                {selectableWaypoints.length === 0 ? (
                  <option value="1">No WP</option>
                ) : (
                  selectableWaypoints.map((waypoint) => {
                    const seq = waypoint.seq ?? waypoint.index;
                    return (
                      <option key={seq} value={seq}>
                        WP {seq} {waypoint.command_name ? `- ${waypoint.command_name}` : ""}
                      </option>
                    );
                  })
                )}
              </select>
              <button type="button" onClick={() => setCurrentWaypoint(selectedWaypointSeq)} disabled={!health.connected || missionCommand.isLoading}>
                SET WP
              </button>
              <button type="button" onClick={() => setCurrentWaypoint(1, "restart WP1")} disabled={!health.connected || missionCommand.isLoading || Number(mission.count || 0) <= 1}>
                RESTART WP1
              </button>
            </div>
          </div>
        </details>
      </aside>

      <main className={`tactical-center center-${centerMode}`}>
        <section className="camera-panel vision-panel">
          <div className="panel-command-bar">
            <span>Camera 01</span>
            <button className="icon-button" type="button" title={centerMode === "camera" ? "Restore balanced layout" : "Focus camera panel"} aria-label={centerMode === "camera" ? "Restore balanced layout" : "Focus camera panel"} onClick={() => setCenterMode(centerMode === "camera" ? "balanced" : "camera")}>
              <ExpandPanelIcon active={centerMode === "camera"} />
            </button>
          </div>
          <div className="camera-readout">
            JETSON ORIN SUPER | CAM 1 | SAR DETECTION | LAT {formatCoordinate(telemetry.lat, 5)} LON {formatCoordinate(telemetry.lng, 5)}
          </div>
          <CameraPreview />
        </section>

        <section className="map-panel-tactical sar-map-panel">
          <div className="panel-command-bar map-command-bar">
            <span>Tactical map</span>
            <button className="icon-button" type="button" title={centerMode === "map" ? "Restore balanced layout" : "Focus map panel"} aria-label={centerMode === "map" ? "Restore balanced layout" : "Focus map panel"} onClick={() => setCenterMode(centerMode === "map" ? "balanced" : "map")}>
              <ExpandPanelIcon active={centerMode === "map"} />
            </button>
          </div>
          <Suspense fallback={<div className="map-grid-overlay" />}>
            <OperationalMap
              lat={telemetry.lat}
              lng={telemetry.lng}
              alt={telemetry.alt}
              headingDeg={telemetry.heading_deg ?? telemetry.yaw_deg}
              rollDeg={telemetry.roll_deg}
              pitchDeg={telemetry.pitch_deg}
              mission={mission}
            />
          </Suspense>
          <div className="map-coordinate-strip">
            <strong>{hasGps ? `${formatCoordinate(telemetry.lat, 6)}, ${formatCoordinate(telemetry.lng, 6)}` : "GPS LOCK PENDING"}</strong>
            <span>HDG {formatNumber(telemetry.heading_deg ?? telemetry.yaw_deg, 0)} | ALT {formatNumber(telemetry.alt)} m | {formatMissionItem(mission.current_waypoint)}</span>
          </div>
        </section>
      </main>

      <aside className="tactical-right">
        <div className="top-status-row">
          <Badge tone="warning">MODE: {telemetry.flight_mode || "-"}</Badge>
          <Badge tone={telemetry.armed ? "danger" : "success"}>SYS: {telemetry.armed ? "ARMED" : "DISARMED"}</Badge>
        </div>

        <FlightRecorderControl onEvent={pushEvent} />

        <DataQuick telemetry={telemetry} />
        <BatteryMonitor percent={telemetry.battery_percent} voltage={telemetry.battery_voltage_v} current={telemetry.battery_current_a} />
        <EkfVibeBar telemetry={telemetry} onClick={() => setIsEkfModalOpen(true)} />

        <section className="readout-panel">
          <h3>Flight Data</h3>
          <dl>
            <div><dt>MODE</dt><dd>{telemetry.flight_mode || "-"}</dd></div>
            <div><dt>ALT (AGL)</dt><dd>{formatNumber(telemetry.alt)} m</dd></div>
            <div><dt>V/S</dt><dd>{formatNumber(telemetry.v_speed_m_s)} m/s</dd></div>
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
            <div><dt>STREAM</dt><dd>VRX / EASYCAP</dd></div>
            <div><dt>DETECTIONS</dt><dd>NOT CONNECTED</dd></div>
          </dl>
          <div className="vision-detection-summary">
            <span>Live preview <strong>ACTIVE</strong></span>
            <span>Frame-aligned recording <strong>READY</strong></span>
          </div>
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
      
      {isEkfModalOpen && (
        <EkfVibeModal 
          telemetry={telemetry} 
          onClose={() => setIsEkfModalOpen(false)} 
        />
      )}
    </section>
  );
}

export default DashboardView;
