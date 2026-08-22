import React from "react";
import "./DataQuick.css";

function format(value, digits = 1, suffix = "") {
  return value === null || value === undefined || Number.isNaN(Number(value))
    ? "-"
    : String(Number(value).toFixed(digits)) + suffix;
}

function DataQuick({ telemetry }) {
  return (
    <div className="data-quick-container">
      <div className="data-quick-item">
        <span>Airspeed</span>
        <strong>{format(telemetry.airspeed_m_s, 1, " m/s")}</strong>
      </div>
      <div className="data-quick-item">
        <span>Ground speed</span>
        <strong>{format(telemetry.groundspeed_m_s, 1, " m/s")}</strong>
      </div>
      <div className="data-quick-item">
        <span>Relative altitude</span>
        <strong>{format(telemetry.alt, 1, " m")}</strong>
      </div>
      <div className="data-quick-item">
        <span>Vertical speed</span>
        <strong>{format(telemetry.v_speed_m_s, 1, " m/s")}</strong>
      </div>
    </div>
  );
}

export default DataQuick;
