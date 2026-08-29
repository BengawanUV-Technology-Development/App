import { lazy, Suspense, useState } from "react";
import Badge from "../components/common/Badge";
import AttitudeIndicator from "../components/hud/AttitudeIndicator";
import HeadingIndicator from "../components/hud/HeadingIndicator";
import BatteryMonitor from "../components/telemetry/BatteryMonitor";
import DataQuick from "../components/telemetry/DataQuick";
import EkfVibeBar from "../components/telemetry/EkfVibeBar";
import EkfVibeModal from "../components/telemetry/EkfVibeModal";
import CameraPreview from "../components/recording/CameraPreview";
import { COORDINATE_SMOKE_TEST } from "../data/coordinateSmokeTest.js";

const OperationalMap = lazy(() => import("../components/map/OperationalMap"));

function formatNumber(value, digits = 1, suffix = "") {
  return value === null || value === undefined || Number.isNaN(Number(value))
    ? "-"
    : String(Number(value).toFixed(digits)) + suffix;
}

function formatCoordinate(value, digits = 5) {
  return value === null || value === undefined ? "-" : Number(value).toFixed(digits);
}

function formatTime(value) {
  return value ? new Date(Number(value) * 1000).toLocaleTimeString() : "--:--:--";
}

function coordinateSmokeTestEnabled() {
  if (typeof window === "undefined") return false;
  return new URLSearchParams(window.location.search).get("coordinate_smoke_test") === "1";
}

function DataRow({ label, value, emphasis = false }) {
  return (
    <div className="data-row">
      <dt>{label}</dt>
      <dd className={emphasis ? "is-emphasis" : ""}>{value}</dd>
    </div>
  );
}

function PanelHeading({ eyebrow, title, trailing = null }) {
  return (
    <div className="panel-heading">
      <div>
        <p>{eyebrow}</p>
        <h2>{title}</h2>
      </div>
      {trailing}
    </div>
  );
}

function DashboardView({ health, telemetry, statusText, isRefreshing, onRefresh }) {
  const [isEkfModalOpen, setIsEkfModalOpen] = useState(false);
  const hasGps = health.gps_valid && telemetry.lat !== null && telemetry.lng !== null;
  const linkActive = Boolean(health.backend_online && health.connected && !health.stale);
  const latestMessage = telemetry.status_text || health.error || statusText;
  const latestMessageTone = String(telemetry.status_text_type || "").toLowerCase();
  const messageIsWarning = /warn|critical|error|alert|emergency/.test(latestMessageTone)
    || Boolean(health.error);
  const showCoordinateSmokeTest = coordinateSmokeTestEnabled();
  const coordinateResult = showCoordinateSmokeTest ? COORDINATE_SMOKE_TEST : null;

  return (
    <section className="operations-view">
      <header className="operations-header">
        <div>
          <p className="view-kicker">LIVE TELEMETRY / UDP 14551</p>
          <h1>Operations overview</h1>
          <p className="operations-lede">
            A quiet read-only view of the aircraft state. QGroundControl remains the sole owner of flight commands.
          </p>
        </div>
        <div className="operations-header-actions">
          <Badge tone={linkActive ? "success" : "warning"}>
            <span className="badge-dot" />
            {linkActive ? "TELEMETRY LIVE" : "WAITING FOR LINK"}
          </Badge>
          <button
            type="button"
            className="refresh-button"
            onClick={onRefresh}
            disabled={isRefreshing}
          >
            {isRefreshing ? "Refreshing…" : "Refresh"}
          </button>
        </div>
      </header>

      <div className="read-only-banner" role="note">
        <span className="notice-symbol" aria-hidden="true">i</span>
        <div>
          <strong>Telemetry mirror only</strong>
          <span>Webapp membaca salinan MAVLink dari UDP 14551. Gunakan QGroundControl di UDP 14550 untuk arm, mode, mission, dan parameter.</span>
        </div>
        <Badge>READ ONLY</Badge>
      </div>

      <section className="camera-stream-card" aria-label="Live camera preview">
        <div className="camera-stream-heading">
          <PanelHeading eyebrow="Vision / H.264 RTP" title="Live camera" trailing={<Badge tone="info">CSI / ANALOG</Badge>} />
        </div>
        <div className="camera-stream-body">
          <CameraPreview />
        </div>
      </section>

      <div className="operations-grid">
        <aside className="operations-rail">
          <section className="telemetry-panel attitude-panel">
            <PanelHeading
              eyebrow="Aircraft attitude"
              title="Orientation"
              trailing={<span className="panel-live-mark">{linkActive ? "LIVE" : "—"}</span>}
            />
            <div className="pfd-stack">
              <AttitudeIndicator rollDeg={telemetry.roll_deg} pitchDeg={telemetry.pitch_deg} />
              <HeadingIndicator headingDeg={telemetry.heading_deg ?? telemetry.yaw_deg} />
            </div>
          </section>

          <section className="telemetry-panel">
            <PanelHeading eyebrow="Vehicle state" title="Status" />
            <dl className="data-list">
              <DataRow label="Mode" value={telemetry.flight_mode || "STANDBY"} emphasis />
              <DataRow
                label="System"
                value={telemetry.armed ? "ARMED" : telemetry.armed === false ? "DISARMED" : "—"}
                emphasis={Boolean(telemetry.armed)}
              />
              <DataRow label="Link" value={health.status || "OFFLINE"} />
              <DataRow label="GPS" value={hasGps ? "Position valid" : "No position"} />
            </dl>
          </section>

          <section className="telemetry-panel">
            <PanelHeading eyebrow="Position" title="Coordinates" />
            <dl className="data-list">
              <DataRow label="Latitude" value={formatCoordinate(telemetry.lat)} />
              <DataRow label="Longitude" value={formatCoordinate(telemetry.lng)} />
              <DataRow label="Relative altitude" value={formatNumber(telemetry.alt, 1, " m")} />
              <DataRow label="Altitude AMSL" value={formatNumber(telemetry.alt_amsl, 1, " m")} />
            </dl>
          </section>
        </aside>

        <section className="map-card">
          <div className="map-card-header">
            <PanelHeading
              eyebrow="Live position"
              title="Aircraft map"
              trailing={(
                <>
                  <Badge tone="info">3D AIRCRAFT</Badge>
                  {coordinateResult ? <Badge tone="warning">TARGET DOT · SMOKE</Badge> : null}
                </>
              )}
            />
            <span className={hasGps ? "map-lock-state is-ready" : "map-lock-state"}>
              {hasGps ? "GPS position valid" : "Waiting for GPS"}
            </span>
          </div>
          <div className="map-card-body">
            <Suspense fallback={<div className="map-loading-state">Loading map renderer…</div>}>
              <OperationalMap
                lat={telemetry.lat}
                lng={telemetry.lng}
                alt={telemetry.alt}
                headingDeg={telemetry.heading_deg ?? telemetry.yaw_deg}
                rollDeg={telemetry.roll_deg}
                pitchDeg={telemetry.pitch_deg}
                mission={null}
                coordinate={coordinateResult}
                focusCoordinate={showCoordinateSmokeTest}
              />
            </Suspense>
          </div>
          <div className="map-card-footer">
            <div>
              <span className="footer-label">Position</span>
              <strong>{hasGps ? formatCoordinate(telemetry.lat, 6) + ", " + formatCoordinate(telemetry.lng, 6) : "No GPS fix"}</strong>
            </div>
            <div>
              <span className="footer-label">Heading</span>
              <strong>{formatNumber(telemetry.heading_deg ?? telemetry.yaw_deg, 0, "°")}</strong>
            </div>
            <div>
              <span className="footer-label">Track</span>
              <strong>Receive-only</strong>
            </div>
          </div>
          {coordinateResult ? (
            <div className="coordinate-smoke-note" role="status">
              Smoke fixture: pedestrian F1919 · synthetic clock alignment · assumed AGL 10 m · NON-QUALIFICATION
            </div>
          ) : null}
        </section>

        <aside className="data-column">
          <section className="telemetry-panel">
            <PanelHeading eyebrow="Flight data" title="Quick readout" />
            <DataQuick telemetry={telemetry} />
          </section>

          <section className="telemetry-panel">
            <PanelHeading eyebrow="Power" title="Battery" />
            <BatteryMonitor percent={telemetry.battery_percent} />
          </section>

          <section className="telemetry-panel">
            <PanelHeading
              eyebrow="Estimator health"
              title="EKF & vibration"
              trailing={<span className="panel-action-hint">Details</span>}
            />
            <EkfVibeBar telemetry={telemetry} onClick={() => setIsEkfModalOpen(true)} />
          </section>

          <section className="telemetry-panel">
            <PanelHeading eyebrow="Link details" title="Transport" />
            <dl className="data-list">
              <DataRow label="Source" value="MAVLink UDP" />
              <DataRow label="Listen port" value="14551" emphasis />
              <DataRow label="Commands" value="Disabled" />
              <DataRow label="Last update" value={formatTime(telemetry.last_update || health.last_update)} />
            </dl>
          </section>
        </aside>
      </div>

      <section className={messageIsWarning ? "latest-message-panel is-warning" : "latest-message-panel"} aria-live="polite">
        <div className="latest-message-label">
          <span className="message-indicator" />
          <span>Latest vehicle message</span>
        </div>
        <p>{latestMessage}</p>
        <time>{formatTime(telemetry.last_update || health.last_update)}</time>
      </section>

      {isEkfModalOpen ? (
        <EkfVibeModal telemetry={telemetry} onClose={() => setIsEkfModalOpen(false)} />
      ) : null}
    </section>
  );
}

export default DashboardView;
