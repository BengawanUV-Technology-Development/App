function Badge({ children, tone = "", className = "" }) {
  const classes = ["badge", tone, className].filter(Boolean).join(" ");
  return <span className={classes}>{children}</span>;
}

export default Badge;
