import { useCallback, useEffect, useMemo, useState } from "react";
import Badge from "../components/common/Badge";
import { apiGet } from "../services/api";

function formatTime(value) {
  return value ? new Date(Number(value) * 1000).toLocaleTimeString() : "--:--:--";
}

function messageTone(item) {
  const type = String(item?.type || "").toLowerCase();
  const text = String(item?.text || "").toLowerCase();
  if (/emergency|alert|critical|error|fail/.test(type + " " + text)) return "danger";
  if (/warn|prearm|waiting|unhealthy|ekf|gps/.test(type + " " + text)) return "warn";
  return "info";
}

function LogsView() {
  const [filter, setFilter] = useState("all");
  const [feed, setFeed] = useState({
    connected: false,
    isArmable: false,
    failingChecks: [],
    messages: [],
    timestamp: null,
    error: null,
  });
  const [isRefreshing, setIsRefreshing] = useState(false);

  const refreshMessages = useCallback(async () => {
    setIsRefreshing(true);
    const response = await apiGet("/health/prearm");
    if (response.ok) {
      setFeed({
        connected: Boolean(response.data.connected),
        isArmable: Boolean(response.data.is_armable),
        failingChecks: response.data.failing_checks || [],
        messages: response.data.recent_status_texts || [],
        timestamp: Date.now() / 1000,
        error: null,
      });
    } else {
      setFeed((previous) => ({ ...previous, error: response.error }));
    }
    setIsRefreshing(false);
  }, []);

  useEffect(() => {
    refreshMessages();
  }, [refreshMessages]);

  const messages = useMemo(() => (
    feed.messages
      .filter((item) => filter === "all" || messageTone(item) === filter)
      .slice()
      .sort((left, right) => Number(right.ts || 0) - Number(left.ts || 0))
  ), [feed.messages, filter]);

  return (
    <section className="logs-view">
      <header className="logs-header">
        <div>
          <p className="view-kicker">MAVLINK STATUS / UDP 14551</p>
          <h1>Vehicle messages</h1>
          <p>STATUSTEXT and pre-arm diagnostics received from the flight controller.</p>
        </div>
        <div className="logs-header-actions">
          <Badge tone={feed.connected ? "success" : "warning"}>
            {feed.connected ? "LINK ACTIVE" : "LINK STANDBY"}
          </Badge>
          <button type="button" className="refresh-button" onClick={refreshMessages} disabled={isRefreshing}>
            {isRefreshing ? "Refreshing…" : "Refresh"}
          </button>
        </div>
      </header>

      <div className="diagnostic-summary">
        <div>
          <span>Armability</span>
          <strong className={feed.isArmable ? "is-good" : "is-muted"}>
            {feed.isArmable ? "Ready" : "Checks pending"}
          </strong>
        </div>
        <div>
          <span>Failing checks</span>
          <strong className={feed.failingChecks.length ? "is-warning" : "is-good"}>
            {feed.failingChecks.length || "None"}
          </strong>
        </div>
        <div>
          <span>Messages retained</span>
          <strong>{feed.messages.length}</strong>
        </div>
        <div>
          <span>Last sync</span>
          <strong>{formatTime(feed.timestamp)}</strong>
        </div>
      </div>

      <div className="logs-toolbar">
        <span>Filter</span>
        {["all", "warn", "danger"].map((tone) => (
          <button
            key={tone}
            type="button"
            className={filter === tone ? "is-selected" : ""}
            onClick={() => setFilter(tone)}
          >
            {tone === "all" ? "All" : tone === "warn" ? "Warnings" : "Critical"}
          </button>
        ))}
        <span className="logs-source">Receive-only diagnostic feed</span>
      </div>

      <div className="logs-list">
        {feed.error ? <div className="console-message danger"><span>{feed.error}</span></div> : null}
        {messages.map((item, index) => (
          <div key={String(item.ts) + "-" + String(item.text) + "-" + String(index)} className={"console-message " + messageTone(item)}>
            <time>{formatTime(item.ts)}</time>
            <span>{item.text}</span>
            <small>{item.type || "INFO"}</small>
          </div>
        ))}
        {!feed.error && messages.length === 0 ? (
          <div className="console-empty">
            <strong>No messages in this filter</strong>
            <span>The webapp only displays messages observed on the read-only MAVLink mirror.</span>
          </div>
        ) : null}
      </div>
    </section>
  );
}

export default LogsView;
