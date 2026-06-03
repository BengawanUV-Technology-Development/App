function TelemetryCard({ label, value, unit = "", color = "", icon = "" }) {
  const style = color ? { "--metric-color": color } : undefined;

  return (
    <div className="telemetry-card" style={style}>
      <div className="telemetry-card-top">
        <span>{label}</span>
        {icon ? <span aria-hidden="true">{icon}</span> : null}
      </div>
      <strong>{value}</strong>
      {unit ? <small>{unit}</small> : null}
    </div>
  );
}

export default TelemetryCard;
