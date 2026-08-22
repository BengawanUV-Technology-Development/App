import React from "react";
import DraggableModal from "../common/DraggableModal";

function format(value, digits = 2) {
  return value === null || value === undefined || Number.isNaN(Number(value))
    ? "—"
    : Number(value).toFixed(digits);
}

function ProgressBar({ label, value, max, warningThreshold, dangerThreshold }) {
  const numericValue = value === null || value === undefined ? null : Number(value);
  const displayValue = numericValue === null ? 0 : Math.max(0, Math.min(max, numericValue));
  const percentage = (displayValue / max) * 100;
  let color = "var(--accent-success)";
  if (displayValue >= dangerThreshold) color = "var(--accent-danger)";
  else if (displayValue >= warningThreshold) color = "var(--accent-warning)";

  return (
    <div className="diagnostic-bar">
      <div className="diagnostic-bar-label">
        <span>{label}</span>
        <strong>{format(value)}</strong>
      </div>
      <div className="diagnostic-bar-track">
        <div className="diagnostic-bar-fill" style={{ width: percentage + "%", backgroundColor: color }} />
      </div>
    </div>
  );
}

function EkfVibeModal({ telemetry, onClose }) {
  const hasEkf = Boolean(telemetry.connected && telemetry.last_update);
  const ekfValue = Math.max(
    Number(telemetry.ekf_velocity || 0),
    Number(telemetry.ekf_pos_horiz || 0),
    Number(telemetry.ekf_compass || 0),
  );

  return (
    <DraggableModal title="Estimator diagnostics" onClose={onClose} initialPosition={{ x: 100, y: 100 }}>
      <section className="diagnostic-section">
        <div className="diagnostic-section-heading">
          <h3>Extended Kalman Filter</h3>
          <strong className={hasEkf ? (ekfValue < 0.8 ? "is-good" : "is-warning") : "is-muted"}>
            {hasEkf ? (ekfValue < 0.8 ? "OK" : "CHECK") : "UNKNOWN"}
          </strong>
        </div>
        <ProgressBar label="Velocity variance" value={telemetry.ekf_velocity} max={1} warningThreshold={0.5} dangerThreshold={0.8} />
        <ProgressBar label="Horizontal position" value={telemetry.ekf_pos_horiz} max={1} warningThreshold={0.5} dangerThreshold={0.8} />
        <ProgressBar label="Compass variance" value={telemetry.ekf_compass} max={1} warningThreshold={0.5} dangerThreshold={0.8} />
      </section>
      <section className="diagnostic-section">
        <div className="diagnostic-section-heading">
          <h3>Vibration</h3>
          <span>mm/s²</span>
        </div>
        <ProgressBar label="X axis" value={telemetry.vibration_x} max={60} warningThreshold={30} dangerThreshold={45} />
        <ProgressBar label="Y axis" value={telemetry.vibration_y} max={60} warningThreshold={30} dangerThreshold={45} />
        <ProgressBar label="Z axis" value={telemetry.vibration_z} max={60} warningThreshold={30} dangerThreshold={45} />
      </section>
    </DraggableModal>
  );
}

export default EkfVibeModal;
