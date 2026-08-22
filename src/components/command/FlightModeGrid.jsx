/**
 * FlightModeGrid
 *
 * Grid tombol untuk memilih flight mode.
 * Saat `readOnly={true}`, semua tombol dinonaktifkan — tidak ada API call.
 */
const groups = [
  { label: "VTOL", tone: "vtol", modes: ["Q_HOVER", "Q_LAND", "Q_STABILIZE"] },
  { label: "Fixed-Wing", tone: "primary", modes: ["FBWA", "AUTO", "MANUAL"] },
  { label: "Emergency", tone: "warning", modes: ["RTL"] },
];

function normalizeModeName(mode) {
  return String(mode || "").toUpperCase().replaceAll("_", "").replaceAll(" ", "");
}

function FlightModeGrid({ currentMode, isConnected, onSetMode, readOnly = false }) {
  const activeMode = normalizeModeName(currentMode);

  return (
    <div className="flight-mode-grid">
      {groups.map((group) => (
        <div key={group.label} className="mode-group">
          <span>{group.label}</span>
          <div>
            {group.modes.map((mode) => {
              const isActive = activeMode === normalizeModeName(mode);
              const isDisabled = readOnly || !isConnected;
              return (
                <button
                  key={mode}
                  type="button"
                  className={`mode-button mode-${group.tone} ${isActive ? "is-active" : ""}`}
                  onClick={() => !readOnly && onSetMode(mode)}
                  disabled={isDisabled}
                  title={readOnly ? "Command dinonaktifkan – mode read-only (UDP mirror)" : undefined}
                  aria-disabled={isDisabled}
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
