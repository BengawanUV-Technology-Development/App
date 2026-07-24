import React from "react";
import "./BatteryMonitor.css";

function BatteryMonitor({ percent, voltage, current }) {
  const displayPercent = percent === null || percent === undefined ? 0 : Math.max(0, Math.min(100, percent));
  const isCritical = displayPercent < 20;
  const isWarning = displayPercent < 40;

  let batteryColor = "var(--color-success)";
  if (isCritical) batteryColor = "var(--color-danger)";
  else if (isWarning) batteryColor = "var(--color-warning)";

  return (
    <div className="battery-monitor">
      <div className="battery-header">
        <span>BATTERY</span>
        <strong>{percent === null || percent === undefined ? "-" : `${displayPercent.toFixed(0)}%`}</strong>
      </div>
      <div className="battery-bar-container">
        <div 
          className="battery-bar-fill" 
          style={{ 
            width: `${displayPercent}%`, 
            backgroundColor: batteryColor 
          }} 
        />
      </div>
      <div className="battery-details">
        <span>{voltage === null || voltage === undefined ? "-" : `${Number(voltage).toFixed(1)} V`}</span>
        <span>{current === null || current === undefined ? "-" : `${Number(current).toFixed(1)} A`}</span>
      </div>
    </div>
  );
}

export default BatteryMonitor;
