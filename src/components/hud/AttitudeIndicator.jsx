function clamp(value, min, max) {
  return Math.min(Math.max(value, min), max);
}

function AttitudeIndicator({ rollDeg = 0, pitchDeg = 0 }) {
  const hasData = rollDeg !== null && rollDeg !== undefined && pitchDeg !== null && pitchDeg !== undefined;
  const roll = Number(rollDeg || 0);
  const pitch = clamp(Number(pitchDeg || 0), -30, 30);
  const pitchOffset = pitch * 3;
  const ladder = [-30, -20, -10, 10, 20, 30];

  return (
    <svg className="attitude-indicator" viewBox="0 0 280 280" role="img" aria-label="Attitude indicator">
      <defs>
        <clipPath id="attitude-clip">
          <circle cx="140" cy="140" r="132" />
        </clipPath>
        <linearGradient id="sky-gradient" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stopColor="#0ea5e9" />
          <stop offset="100%" stopColor="#7dd3fc" />
        </linearGradient>
        <linearGradient id="ground-gradient" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stopColor="#92400e" />
          <stop offset="100%" stopColor="#451a03" />
        </linearGradient>
      </defs>

      <circle cx="140" cy="140" r="136" fill="#020617" stroke="rgba(148,163,184,0.45)" strokeWidth="4" />
      {hasData ? (
        <g clipPath="url(#attitude-clip)">
          <g transform={`rotate(${-roll} 140 140) translate(0 ${pitchOffset})`}>
            <rect x="-80" y="-120" width="440" height="260" fill="url(#sky-gradient)" />
            <rect x="-80" y="140" width="440" height="300" fill="url(#ground-gradient)" />
            <line x1="-80" x2="360" y1="140" y2="140" stroke="#f8fafc" strokeWidth="3" />
            {ladder.map((mark) => {
              const y = 140 - mark * 3;
              return (
                <g key={mark}>
                  <line x1="100" x2="128" y1={y} y2={y} stroke="#f8fafc" strokeWidth="2" />
                  <line x1="152" x2="180" y1={y} y2={y} stroke="#f8fafc" strokeWidth="2" />
                  <text x="86" y={y + 4} fill="#f8fafc" fontSize="11" textAnchor="middle">{Math.abs(mark)}</text>
                  <text x="194" y={y + 4} fill="#f8fafc" fontSize="11" textAnchor="middle">{Math.abs(mark)}</text>
                </g>
              );
            })}
          </g>
        </g>
      ) : (
        <g>
          <circle cx="140" cy="140" r="128" fill="#111827" />
          <text x="140" y="136" textAnchor="middle" fill="#94a3b8" fontSize="14" fontFamily="JetBrains Mono">
            NO ATTITUDE
          </text>
          <text x="140" y="158" textAnchor="middle" fill="#64748b" fontSize="11" fontFamily="JetBrains Mono">
            CONNECT FC
          </text>
        </g>
      )}

      <g stroke="#fbbf24" strokeWidth="4" strokeLinecap="round" fill="none">
        <line x1="82" x2="122" y1="140" y2="140" />
        <line x1="158" x2="198" y1="140" y2="140" />
        <polyline points="122,140 140,154 158,140" />
      </g>
      <circle cx="140" cy="140" r="4" fill="#fbbf24" />
      <text x="140" y="264" textAnchor="middle" className="hud-readout">
        {hasData ? `ROLL ${roll.toFixed(0)} / PITCH ${pitch.toFixed(0)}` : "ROLL - / PITCH -"}
      </text>
    </svg>
  );
}

export default AttitudeIndicator;
