import TelemetryCard from "./TelemetryCard";

function formatNumber(value, digits = 1) {
  return value === null || value === undefined ? "-" : Number(value).toFixed(digits);
}

function batteryColor(value) {
  if (value === null || value === undefined) return "";
  if (value < 20) return "var(--accent-danger)";
  if (value < 50) return "var(--accent-warning)";
  return "var(--accent-success)";
}

function TelemetryGrid({ telemetry }) {
  const gps =
    telemetry.lat === null || telemetry.lat === undefined || telemetry.lng === null || telemetry.lng === undefined
      ? "-"
      : `${Number(telemetry.lat).toFixed(5)}, ${Number(telemetry.lng).toFixed(5)}`;

  return (
    <div className="telemetry-grid">
      <TelemetryCard label="Altitude" value={formatNumber(telemetry.alt)} unit="m" icon="ALT" />
      <TelemetryCard label="AMSL Alt" value={formatNumber(telemetry.alt_amsl)} unit="m" icon="MSL" />
      <TelemetryCard label="Ground Speed" value={formatNumber(telemetry.groundspeed_m_s)} unit="m/s" icon="GS" />
      <TelemetryCard label="V Speed" value={formatNumber(telemetry.v_speed_m_s)} unit="m/s" icon="VS" />
      <TelemetryCard
        label="Battery"
        value={telemetry.battery_percent === null || telemetry.battery_percent === undefined ? "-" : telemetry.battery_percent.toFixed(1)}
        unit="%"
        color={batteryColor(telemetry.battery_percent)}
        icon="BAT"
      />
      <TelemetryCard label="Heading" value={formatNumber(telemetry.heading_deg ?? telemetry.yaw_deg, 0)} unit="deg" icon="HDG" />
      <TelemetryCard label="GPS" value={gps} icon="GPS" />
    </div>
  );
}

export default TelemetryGrid;
