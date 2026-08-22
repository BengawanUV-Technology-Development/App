import React from "react";
import "./BatteryMonitor.css";

function BatteryMonitor({ percent }) {
  const hasValue = percent !== null && percent !== undefined && !Number.isNaN(Number(percent));
  const displayPercent = hasValue ? Math.max(0, Math.min(100, Number(percent))) : 0;
  const isCritical = hasValue && displayPercent < 20;
  const isWarning = hasValue && displayPercent < 40;

  let batteryColor = "var(--accent-success)";
  if (isCritical) batteryColor = "var(--accent-danger)";
  else if (isWarning) batteryColor = "var(--accent-warning)";

  return (
    <div className="battery-monitor">
      <div className="battery-header">
        <span>Remaining</span>
        <strong>{hasValue ? displayPercent.toFixed(0) + "%" : "—"}</strong>
      </div>
      <div className="battery-bar-container">
        <div
          className="battery-bar-fill"
          style={{ width: displayPercent + "%", backgroundColor: batteryColor }}
        />
      </div>
      <div className="battery-details">
        <span>{hasValue ? "SYS_STATUS" : "Waiting for battery telemetry"}</span>
        <span>{hasValue ? (isCritical ? "Critical" : isWarning ? "Low" : "Nominal") : "—"}</span>
      </div>
    </div>
  );
}

export default BatteryMonitor;
