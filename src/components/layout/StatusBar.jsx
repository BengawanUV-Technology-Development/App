function formatCoordinate(value) {
  return value === null || value === undefined ? "-" : Number(value).toFixed(5);
}

function formatTime(value) {
  if (!value) return "-";
  return new Date(value * 1000).toLocaleTimeString();
}

function batteryClass(value) {
  if (value === null || value === undefined) return "";
  if (value < 20) return "danger";
  if (value < 50) return "warning";
  return "success";
}

import Badge from "../common/Badge";

function StatusBar({ health, telemetry }) {
  const battery = telemetry?.battery_percent;
  const isConnected = Boolean(health?.connected);
  const isArmed = Boolean(telemetry?.armed);

  return (
    <footer className="status-bar">
      <div className="status-item">
        <span className={`connection-dot ${isConnected ? "is-online" : ""}`} />
        <span>{isConnected ? "Connected" : health?.status || "Offline"}</span>
      </div>
      <div className="status-item">
        <span className="status-key">BAT</span>
        <Badge tone={batteryClass(battery)}>
          {battery === null || battery === undefined ? "-" : `${battery.toFixed(1)}%`}
        </Badge>
      </div>
      <div className="status-item">
        <span className="status-key">SYS</span>
        <Badge tone={isArmed ? "danger" : "success"}>{isArmed ? "Armed" : "Disarmed"}</Badge>
      </div>
      <div className="status-item">
        <span className="status-key">MODE</span>
        <Badge>{telemetry?.flight_mode || "-"}</Badge>
      </div>
      <div className="status-item">
        <span className="status-key">GPS</span>
        <span>{formatCoordinate(telemetry?.lat)}, {formatCoordinate(telemetry?.lng)}</span>
      </div>
      <div className="status-item">
        <span className="status-key">SYNC</span>
        <span>{formatTime(telemetry?.last_update || health?.last_update)}</span>
      </div>
    </footer>
  );
}

export default StatusBar;
