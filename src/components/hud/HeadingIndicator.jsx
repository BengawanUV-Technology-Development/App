const headings = [
  { deg: 0, label: "N" },
  { deg: 30, label: "30" },
  { deg: 60, label: "60" },
  { deg: 90, label: "E" },
  { deg: 120, label: "120" },
  { deg: 150, label: "150" },
  { deg: 180, label: "S" },
  { deg: 210, label: "210" },
  { deg: 240, label: "240" },
  { deg: 270, label: "W" },
  { deg: 300, label: "300" },
  { deg: 330, label: "330" },
  { deg: 360, label: "N" },
];

function HeadingIndicator({ headingDeg = 0 }) {
  const hasData = headingDeg !== null && headingDeg !== undefined;
  const heading = ((Number(headingDeg || 0) % 360) + 360) % 360;
  const offset = 240 - heading * 4;

  return (
    <div className="heading-indicator">
      <svg viewBox="0 0 480 72" role="img" aria-label="Heading indicator">
        <rect x="0" y="0" width="480" height="72" rx="8" fill="rgba(15,23,42,0.92)" />
        <g transform={`translate(${hasData ? offset : 240} 0)`}>
          {headings.map((item) => (
            <g key={`${item.deg}-${item.label}`} transform={`translate(${item.deg * 4} 0)`}>
              <line x1="0" x2="0" y1="14" y2="30" stroke="#94a3b8" strokeWidth="2" />
              <text x="0" y="52" textAnchor="middle" fill="#f8fafc" fontSize="14" fontFamily="JetBrains Mono">
                {item.label}
              </text>
            </g>
          ))}
        </g>
        <polygon points="240,8 232,22 248,22" fill="#fbbf24" />
      </svg>
      <strong>{hasData ? `${heading.toFixed(0).padStart(3, "0")}°` : "---"}</strong>
    </div>
  );
}

export default HeadingIndicator;
