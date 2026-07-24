import React from "react";
import "./EkfVibeBar.css";

function VerticalBar({ label, value, max, warningThreshold, dangerThreshold }) {
  const displayValue = value === null || value === undefined ? 0 : Math.max(0, Math.min(max, value));
  const percentage = (displayValue / max) * 100;
  
  let color = "var(--color-success)";
  if (displayValue >= dangerThreshold) color = "var(--color-danger)";
  else if (displayValue >= warningThreshold) color = "var(--color-warning)";

  return (
    <div className="vbar-col">
      <div className="vbar-track">
        <div className="vbar-fill" style={{ height: `${percentage}%`, backgroundColor: color }} />
      </div>
      <span className="vbar-label">{label}</span>
    </div>
  );
}

function EkfVibeBar({ telemetry, onClick }) {
  const vibeMax = 60;
  const vibeWarn = 30;
  const vibeDanger = 45;

  // Calculate EKF overall variance (max of pos, vel, compass)
  const ekfMax = 1.0;
  const ekfWarn = 0.5;
  const ekfDanger = 0.8;
  const velVar = telemetry.ekf_velocity_variance || 0;
  const posVar = telemetry.ekf_pos_variance || 0;
  const magVar = telemetry.ekf_compass_variance || 0;
  const ekfValue = Math.max(velVar, posVar, magVar);

  return (
    <div className="ekf-vibe-container" onClick={onClick} style={{ cursor: onClick ? 'pointer' : 'default' }}>
      <div className="ekf-vibe-header">
        <span>EKF / VIBE (Click for details)</span>
        <strong className={telemetry.ekf_ok ? "text-success" : "text-danger"}>
          {telemetry.ekf_ok === null || telemetry.ekf_ok === undefined ? "-" : (telemetry.ekf_ok ? "OK" : "ERROR")}
        </strong>
      </div>
      <div className="vbar-container">
        <VerticalBar label="EKF" value={ekfValue} max={ekfMax} warningThreshold={ekfWarn} dangerThreshold={ekfDanger} />
        <VerticalBar label="VIB X" value={telemetry.vibration_x} max={vibeMax} warningThreshold={vibeWarn} dangerThreshold={vibeDanger} />
        <VerticalBar label="VIB Y" value={telemetry.vibration_y} max={vibeMax} warningThreshold={vibeWarn} dangerThreshold={vibeDanger} />
        <VerticalBar label="VIB Z" value={telemetry.vibration_z} max={vibeMax} warningThreshold={vibeWarn} dangerThreshold={vibeDanger} />
      </div>
    </div>
  );
}

export default EkfVibeBar;
