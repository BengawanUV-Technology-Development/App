import React from 'react';
import DraggableModal from '../common/DraggableModal';

function format(value, digits = 2) {
  return value === null || value === undefined ? "-" : Number(value).toFixed(digits);
}

function ProgressBar({ label, value, max, warningThreshold, dangerThreshold }) {
  const displayValue = value === null || value === undefined ? 0 : Math.max(0, Math.min(max, value));
  const percentage = (displayValue / max) * 100;
  
  let color = "var(--color-success)";
  if (displayValue >= dangerThreshold) color = "var(--color-danger)";
  else if (displayValue >= warningThreshold) color = "var(--color-warning)";

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', marginBottom: '8px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
        <span>{label}</span>
        <strong>{format(value)}</strong>
      </div>
      <div style={{ width: '100%', height: '10px', background: 'var(--color-surface, #111827)', borderRadius: '5px', overflow: 'hidden' }}>
        <div style={{ width: `${percentage}%`, height: '100%', backgroundColor: color, transition: 'width 0.3s' }} />
      </div>
    </div>
  );
}

function EkfVibeModal({ telemetry, onClose }) {
  const vibeMax = 60;
  const vibeWarn = 30;
  const vibeDanger = 45;

  const ekfMax = 1.0;
  const ekfWarn = 0.5;
  const ekfDanger = 0.8;

  return (
    <DraggableModal title="EKF & Vibration Status" onClose={onClose} initialPosition={{ x: window.innerWidth / 2 - 175, y: 100 }}>
      <div>
        <h4 style={{ fontSize: '0.85rem', marginBottom: '12px', borderBottom: '1px solid var(--color-border, rgba(148, 163, 184, 0.18))', paddingBottom: '4px' }}>
          Extended Kalman Filter (EKF)
        </h4>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '12px', fontSize: '0.85rem' }}>
          <span>Overall Status:</span>
          <strong style={{ color: telemetry.ekf_ok ? 'var(--color-success)' : 'var(--color-danger)' }}>
            {telemetry.ekf_ok === null || telemetry.ekf_ok === undefined ? "UNKNOWN" : (telemetry.ekf_ok ? "OK" : "ERROR")}
          </strong>
        </div>
        <ProgressBar label="Velocity Variance" value={telemetry.ekf_velocity_variance} max={ekfMax} warningThreshold={ekfWarn} dangerThreshold={ekfDanger} />
        <ProgressBar label="Position Variance" value={telemetry.ekf_pos_variance} max={ekfMax} warningThreshold={ekfWarn} dangerThreshold={ekfDanger} />
        <ProgressBar label="Compass Variance" value={telemetry.ekf_compass_variance} max={ekfMax} warningThreshold={ekfWarn} dangerThreshold={ekfDanger} />
      </div>

      <div style={{ marginTop: '16px' }}>
        <h4 style={{ fontSize: '0.85rem', marginBottom: '12px', borderBottom: '1px solid var(--color-border, rgba(148, 163, 184, 0.18))', paddingBottom: '4px' }}>
          Vibration Levels
        </h4>
        <ProgressBar label="Vibe X" value={telemetry.vibration_x} max={vibeMax} warningThreshold={vibeWarn} dangerThreshold={vibeDanger} />
        <ProgressBar label="Vibe Y" value={telemetry.vibration_y} max={vibeMax} warningThreshold={vibeWarn} dangerThreshold={vibeDanger} />
        <ProgressBar label="Vibe Z" value={telemetry.vibration_z} max={vibeMax} warningThreshold={vibeWarn} dangerThreshold={vibeDanger} />
      </div>
    </DraggableModal>
  );
}

export default EkfVibeModal;
