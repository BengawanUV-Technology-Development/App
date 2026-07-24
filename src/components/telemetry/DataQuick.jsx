import React from "react";
import "./DataQuick.css";

function format(value, digits = 1, suffix = "") {
  return value === null || value === undefined ? "-" : `${Number(value).toFixed(digits)}${suffix}`;
}

function formatTime(seconds) {
  if (seconds === null || seconds === undefined || isNaN(seconds)) return "--:--:--";
  const s = Math.max(0, Math.floor(seconds));
  const hrs = Math.floor(s / 3600);
  const mins = Math.floor((s % 3600) / 60);
  const secs = s % 60;
  return `${hrs.toString().padStart(2, "0")}:${mins.toString().padStart(2, "0")}:${secs.toString().padStart(2, "0")}`;
}

function DataQuick({ telemetry }) {
  return (
    <div className="data-quick-container">
      <div className="data-quick-item">
        <span>GND SPEED</span>
        <strong>{format(telemetry.groundspeed_m_s, 1)} <small>m/s</small></strong>
      </div>
      <div className="data-quick-item">
        <span>DIST HOME</span>
        <strong>{format(telemetry.dist_to_home_m, 0)} <small>m</small></strong>
      </div>
      <div className="data-quick-item">
        <span>TIME (AIR)</span>
        <strong>{formatTime(telemetry.time_in_air_s)}</strong>
      </div>
      <div className="data-quick-item">
        <span>TIME (BOOT)</span>
        <strong>{formatTime(telemetry.time_since_boot_s)}</strong>
      </div>
    </div>
  );
}

export default DataQuick;
