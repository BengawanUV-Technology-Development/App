function format(value, digits = 1) {
  return value === null || value === undefined ? "-" : Number(value).toFixed(digits);
}

function FlightDataStrip({ telemetry }) {
  return (
    <div className="flight-data-strip">
      <div>
        <span>ALT</span>
        <strong>{format(telemetry.alt)}</strong>
        <small>REL M</small>
      </div>
      <div>
        <span>MSL</span>
        <strong>{format(telemetry.alt_amsl)}</strong>
        <small>M</small>
      </div>
      <div>
        <span>GND</span>
        <strong>{format(telemetry.groundspeed_m_s)}</strong>
        <small>M/S</small>
      </div>
      <div>
        <span>V/S</span>
        <strong>{format(telemetry.v_speed_m_s)}</strong>
        <small>M/S</small>
      </div>
    </div>
  );
}

export default FlightDataStrip;
