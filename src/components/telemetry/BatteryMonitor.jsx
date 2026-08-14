import React from "react";
import "./BatteryMonitor.css";

function SingleBattery({ label, percent, voltage, current }) {
  const displayPercent = percent === null || percent === undefined ? 0 : Math.max(0, Math.min(100, percent));
  const isCritical = displayPercent < 20;
  const isWarning = displayPercent < 40;

  let batteryColor = "var(--color-success)";
  if (isCritical) batteryColor = "var(--color-danger)";
  else if (isWarning) batteryColor = "var(--color-warning)";

  return (
    <div className="single-battery">
      <div className="battery-header">
        <span>{label}</span>
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

function BatteryMonitor({ telemetry }) {
  const hasBat2 = (telemetry.battery2_voltage_v || 0) > 0;
  
  return (
    <div className={`battery-monitor ${hasBat2 ? 'dual-battery' : ''}`}>
      <SingleBattery 
        label={hasBat2 ? "BATTERY 1" : "BATTERY"} 
        percent={telemetry.battery_percent} 
        voltage={telemetry.battery_voltage_v} 
        current={telemetry.battery_current_a} 
      />
      {hasBat2 && (
        <SingleBattery 
          label="BATTERY 2" 
          percent={telemetry.battery2_percent} 
          voltage={telemetry.battery2_voltage_v} 
          current={telemetry.battery2_current_a} 
        />
      )}
    </div>
  );
}

export default BatteryMonitor;
