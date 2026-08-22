import React from "react";
import "./EkfVibeBar.css";

function numeric(value) {
  return value === null || value === undefined || Number.isNaN(Number(value))
    ? null
    : Number(value);
}

function VerticalBar({ label, value, max, warningThreshold, dangerThreshold }) {
  const numericValue = numeric(value);
  const displayValue = numericValue === null ? 0 : Math.max(0, Math.min(max, numericValue));
  const percentage = (displayValue / max) * 100;

  let color = "var(--accent-success)";
  if (displayValue >= dangerThreshold) color = "var(--accent-danger)";
  else if (displayValue >= warningThreshold) color = "var(--accent-warning)";

  return (
    <div className="vbar-col">
      <div className="vbar-track">
        <div className="vbar-fill" style={{ height: percentage + "%", backgroundColor: color }} />
      </div>
      <span className="vbar-label">{label}</span>
    </div>
  );
}

function EkfVibeBar({ telemetry, onClick }) {
  const ekfValues = [
    numeric(telemetry.ekf_velocity),
    numeric(telemetry.ekf_pos_horiz),
    numeric(telemetry.ekf_compass),
  ];
  const hasEkf = Boolean(telemetry.connected && telemetry.last_update && ekfValues.some((value) => value !== null));
  const ekfValue = hasEkf ? Math.max(...ekfValues.map((value) => value || 0)) : null;
  const ekfOk = hasEkf ? ekfValue < 0.8 : null;

  const handleKeyDown = (event) => {
    if (onClick && (event.key === "Enter" || event.key === " ")) {
      event.preventDefault();
      onClick();
    }
  };

  return (
    <div
      className="ekf-vibe-container"
      onClick={onClick}
      onKeyDown={handleKeyDown}
      role={onClick ? "button" : undefined}
      tabIndex={onClick ? 0 : undefined}
    >
      <div className="ekf-vibe-header">
        <span>Estimator variance</span>
        <strong className={ekfOk === true ? "text-success" : ekfOk === false ? "text-danger" : "text-muted"}>
          {ekfOk === null ? "—" : ekfOk ? "OK" : "CHECK"}
        </strong>
      </div>
      <div className="vbar-container">
        <VerticalBar label="EKF" value={ekfValue} max={1} warningThreshold={0.5} dangerThreshold={0.8} />
        <VerticalBar label="VIB X" value={telemetry.vibration_x} max={60} warningThreshold={30} dangerThreshold={45} />
        <VerticalBar label="VIB Y" value={telemetry.vibration_y} max={60} warningThreshold={30} dangerThreshold={45} />
        <VerticalBar label="VIB Z" value={telemetry.vibration_z} max={60} warningThreshold={30} dangerThreshold={45} />
      </div>
      <span className="ekf-detail-hint">Open details</span>
    </div>
  );
}

export default EkfVibeBar;
