const groups = [
  { label: "VTOL", tone: "vtol", modes: ["Q_HOVER", "Q_LAND", "Q_STABILIZE"] },
  { label: "Fixed-Wing", tone: "primary", modes: ["FBWA", "AUTO", "MANUAL"] },
  { label: "Emergency", tone: "warning", modes: ["RTL"] },
];

function normalizeModeName(mode) {
  return String(mode || "").toUpperCase().replaceAll("_", "").replaceAll(" ", "");
}

function FlightModeGrid({ currentMode, isConnected, onSetMode }) {
  const activeMode = normalizeModeName(currentMode);

  return (
    <div className="flight-mode-grid">
      {groups.map((group) => (
        <div key={group.label} className="mode-group">
          <span>{group.label}</span>
          <div>
            {group.modes.map((mode) => {
              const isActive = activeMode === normalizeModeName(mode);
              return (
                <button
                  key={mode}
                  type="button"
                  className={`mode-button mode-${group.tone} ${isActive ? "is-active" : ""}`}
                  onClick={() => onSetMode(mode)}
                  disabled={!isConnected}
                >
                  {mode}
                </button>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}

export default FlightModeGrid;
