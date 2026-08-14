function format(value, digits = 1) {
  return value === null || value === undefined ? "-" : Number(value).toFixed(digits);
}

function FlightDataStrip({ telemetry }) {
  return (
    <div className="flight-data-strip">
      <div>
        <span>AIRSPD</span>
        <strong>{format(telemetry.airspeed_m_s)}</strong>
        <small>M/S</small>
      </div>
      <div>
        <span>MSL</span>
        <strong>{format(telemetry.alt_amsl)}</strong>
        <small>M</small>
      </div>
      <div>
        <span>SATS</span>
        <strong>{telemetry.satellites ?? 0}</strong>
        <small>LOCK</small>
      </div>
      <div>
        <span>HDOP</span>
        <strong>{format(telemetry.gps_hdop)}</strong>
        <small>M</small>
      </div>
    </div>
  );
}

export default FlightDataStrip;
