import { useState } from "react";

function TakeoffPanel({ isConnected, isArmed, onTakeoff, onLand, onSetTakeoffAltitude }) {
  const [altitude, setAltitude] = useState("10");
  const parsedAltitude = Number.parseFloat(altitude);

  return (
    <div className="takeoff-panel">
      <label className="takeoff-input">
        <span>Altitude (m)</span>
        <input
          type="number"
          min="2"
          max="50"
          step="1"
          value={altitude}
          onChange={(event) => setAltitude(event.target.value)}
        />
      </label>
      <button type="button" onClick={() => onSetTakeoffAltitude(parsedAltitude)} disabled={!isConnected || Number.isNaN(parsedAltitude)}>
        Set Alt
      </button>
      <button type="button" onClick={() => onTakeoff(parsedAltitude)} disabled={!isConnected || !isArmed || Number.isNaN(parsedAltitude)}>
        Takeoff
      </button>
      <button type="button" className="button-ghost" onClick={onLand} disabled={!isConnected}>
        Land
      </button>
    </div>
  );
}

export default TakeoffPanel;
