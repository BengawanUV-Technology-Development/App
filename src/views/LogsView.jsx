import { useMemo, useState } from "react";
import { useMissionMessages } from "../hooks/useMissionMessages";

function formatTime(value) {
  return value ? new Date(value * 1000).toLocaleTimeString() : "--:--:--";
}

function messageTone(message) {
  const normalized = String(message || "").toLowerCase();
  if (/(error|fail|failed|loss|bad|critical)/.test(normalized)) return "danger";
  if (/(warn|prearm|unhealthy|waiting|no gps|ekf)/.test(normalized)) return "warn";
  return "info";
}

function LogsView() {
  const { missionMessages, refreshMessages } = useMissionMessages();
  const [filter, setFilter] = useState("all");
  const messages = useMemo(() => (
    (missionMessages.messages || [])
      .map((item, index) => ({ item, index }))
      .filter(({ item }) => filter === "all" || messageTone(item.message) === filter)
      .sort((left, right) => {
        const timestampDifference = Number(right.item.timestamp || 0) - Number(left.item.timestamp || 0);
        return timestampDifference || right.index - left.index;
      })
      .map(({ item }) => item)
  ), [filter, missionMessages.messages]);

  return (
    <section className="logs-console-view">
      <header className="logs-console-header">
        <div>
          <p className="view-kicker">Mission Planner / Live Messages</p>
          <h1>System Message Console</h1>
          <p>Autopilot health, EKF, GPS, mission, and safety messages.</p>
        </div>
        <div className="logs-console-actions">
          {["all", "warn", "danger"].map((tone) => (
            <button key={tone} type="button" className={filter === tone ? "active" : ""} onClick={() => setFilter(tone)}>
              {tone.toUpperCase()}
            </button>
          ))}
          <button type="button" onClick={refreshMessages}>REFRESH</button>
        </div>
      </header>
      <div className="logs-console-meta">
        <span><strong>{missionMessages.count || 0}</strong> messages received</span>
        <span>Source: {missionMessages.source || "mission-planner"}</span>
        <span>Last sync: {formatTime(missionMessages.timestamp)}</span>
      </div>
      <div className="logs-console-list">
        {missionMessages.error ? <div className="console-message danger"><time>[--:--:--]</time><span>{missionMessages.error}</span></div> : null}
        {messages.map((item, index) => (
          <div key={`${item.timestamp}-${item.message}-${index}`} className={`console-message ${messageTone(item.message)}`}>
            <time>[{formatTime(item.timestamp)}]</time>
            <span>{item.message}</span>
            <small>{item.source || "mission-planner"}</small>
          </div>
        ))}
        {!missionMessages.error && messages.length === 0 ? <div className="console-empty">No messages match this filter.</div> : null}
      </div>
    </section>
  );
}

export default LogsView;
