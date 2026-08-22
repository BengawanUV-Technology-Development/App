function clamp(value, min, max) {
  return Math.min(Math.max(value, min), max);
}

function AttitudeIndicator({ rollDeg = 0, pitchDeg = 0 }) {
  const hasData = rollDeg !== null && rollDeg !== undefined && pitchDeg !== null && pitchDeg !== undefined;
  const roll = Number(rollDeg || 0);
  const pitch = clamp(Number(pitchDeg || 0), -30, 30);
  const pitchOffset = pitch * 2.4;
  const ladder = [-30, -20, -10, 10, 20, 30];

  return (
    <svg className="attitude-indicator attitude-indicator-digital" viewBox="0 0 280 220" role="img" aria-label="Digital attitude indicator">
      <defs>
        <clipPath id="attitude-clip">
          <rect x="8" y="8" width="264" height="176" rx="5" />
        </clipPath>
        <pattern id="ahi-grid" width="24" height="24" patternUnits="userSpaceOnUse">
          <path d="M 24 0 L 0 0 0 24" fill="none" stroke="#00bda5" strokeOpacity="0.12" strokeWidth="1" />
        </pattern>
      </defs>

      <rect x="5" y="5" width="270" height="182" rx="7" fill="#03100e" stroke="rgba(207,255,248,0.22)" strokeWidth="2" />
      <rect x="8" y="8" width="264" height="176" rx="5" fill="url(#ahi-grid)" />
      {hasData ? (
        <g clipPath="url(#attitude-clip)">
          <g transform={`rotate(${-roll} 140 96) translate(0 ${pitchOffset})`}>
            <line x1="-80" x2="360" y1="96" y2="96" stroke="#cffff8" strokeWidth="2" />
            {ladder.map((mark) => {
              const y = 96 - mark * 2.4;
              return (
                <g key={mark}>
                  <line x1="106" x2="130" y1={y} y2={y} stroke="#00bda5" strokeWidth="1.5" />
                  <line x1="150" x2="174" y1={y} y2={y} stroke="#00bda5" strokeWidth="1.5" />
                  <text x="92" y={y + 4} fill="#00bda5" fontSize="9" textAnchor="middle">{Math.abs(mark)}</text>
                  <text x="188" y={y + 4} fill="#00bda5" fontSize="9" textAnchor="middle">{Math.abs(mark)}</text>
                </g>
              );
            })}
          </g>
        </g>
      ) : (
        <g>
          <text x="140" y="91" textAnchor="middle" fill="#cffff8" fontSize="14" fontFamily="JetBrains Mono">
            NO ATTITUDE
          </text>
          <text x="140" y="111" textAnchor="middle" fill="#00bda5" fontSize="11" fontFamily="JetBrains Mono">
            CONNECT FC
          </text>
        </g>
      )}

      <g stroke="#cffff8" strokeWidth="3" strokeLinecap="round" fill="none">
        <line x1="88" x2="124" y1="96" y2="96" />
        <line x1="156" x2="192" y1="96" y2="96" />
        <polyline points="124,96 140,106 156,96" />
      </g>
      <path d="M 140 13 l -5 9 h 10 z" fill="#00bda5" />
      <circle cx="140" cy="96" r="3" fill="#00bda5" />
      <text x="140" y="210" textAnchor="middle" className="hud-readout">
        {hasData ? `ROLL ${roll.toFixed(0)} / PITCH ${pitch.toFixed(0)}` : "ROLL - / PITCH -"}
      </text>
    </svg>
  );
}

export default AttitudeIndicator;
