import { useCallback, useEffect, useState } from "react";
import { apiGet } from "../services/api";

const POLL_INTERVAL_MS = 1000;
const STALE_AFTER_SECONDS = 3;

const initialHealth = {
  backend_online: false,
  connected: false,
  status: "DISCONNECTED",
  error: null,
  last_update: null,
  stale: true,
  gps_valid: false,
  source: "mavlink-udp-readonly",
  system_address: "udpin://127.0.0.1:14551",
};

const initialTelemetry = {
  connected: false,
  status: "DISCONNECTED",
  lat: null,
  lng: null,
  alt: null,
  alt_amsl: null,
  armed: null,
  flight_mode: null,
  battery_percent: null,
  status_text: null,
  status_text_type: null,
  roll_deg: null,
  pitch_deg: null,
  yaw_deg: null,
  heading_deg: null,
  airspeed_m_s: null,
  groundspeed_m_s: null,
  v_speed_m_s: null,
  ekf_velocity: null,
  ekf_pos_horiz: null,
  ekf_pos_vert: null,
  ekf_compass: null,
  vibration_x: null,
  vibration_y: null,
  vibration_z: null,
  last_update: null,
  error: null,
};

function hasValidPosition(lat, lng) {
  return Number.isFinite(Number(lat))
    && Number.isFinite(Number(lng))
    && !(Number(lat) === 0 && Number(lng) === 0);
}

function isStale(lastUpdate) {
  if (!lastUpdate) return true;
  return (Date.now() / 1000) - Number(lastUpdate) > STALE_AFTER_SECONDS;
}

function deriveStatusText(health) {
  if (!health.backend_online) return "Backend telemetry belum dapat diakses";
  if (health.status === "DISCONNECTED") return "MAVLink telemetry terputus";
  if (health.stale) return "Telemetry stale — menunggu heartbeat MAVLink";
  if (health.connected) return "MAVLink telemetry aktif melalui UDP 14551";
  return "Menunggu heartbeat MAVLink";
}

export function useTelemetry() {
  const [health, setHealth] = useState(initialHealth);
  const [telemetry, setTelemetry] = useState(initialTelemetry);
  const [statusText, setStatusText] = useState("Menghubungkan ke backend telemetry...");
  const [isRefreshing, setIsRefreshing] = useState(false);

  const applySnapshot = useCallback((healthData, telemetryData) => {
    const nextTelemetry = { ...initialTelemetry, ...telemetryData };
    const lastUpdate = nextTelemetry.last_update || healthData?.last_update || null;
    const backendStatus = healthData?.status || nextTelemetry.status || "DISCONNECTED";
    const stale = backendStatus === "STALE"
      || backendStatus === "DISCONNECTED"
      || isStale(lastUpdate)
      || !Boolean(healthData?.connected);
    const nextHealth = {
      ...initialHealth,
      ...healthData,
      backend_online: true,
      connected: Boolean(healthData?.connected) && !stale,
      last_update: lastUpdate,
      stale,
      gps_valid: hasValidPosition(nextTelemetry.lat, nextTelemetry.lng),
      source: nextTelemetry.source || "mavlink-udp-readonly",
      system_address: nextTelemetry.system_address || "udpin://127.0.0.1:14551",
      error: healthData?.error || nextTelemetry.error || null,
    };

    setTelemetry(nextTelemetry);
    setHealth(nextHealth);
    setStatusText(deriveStatusText(nextHealth));
  }, []);

  const refresh = useCallback(async () => {
    setIsRefreshing(true);
    try {
      const [healthResult, telemetryResult] = await Promise.all([
        apiGet("/health"),
        apiGet("/telemetry"),
      ]);

      if (!healthResult.ok || !telemetryResult.ok) {
        throw new Error(healthResult.error || telemetryResult.error || "Backend response was not ok");
      }

      applySnapshot(healthResult.data, telemetryResult.data);
      return { health: healthResult.data, telemetry: telemetryResult.data };
    } catch (error) {
      const message = String(error);
      setHealth((previous) => ({
        ...previous,
        backend_online: false,
        connected: false,
        stale: true,
        status: "DISCONNECTED",
        error: message,
      }));
      setStatusText("Backend telemetry belum dapat diakses");
      return { health: null, telemetry: null, error: message };
    } finally {
      setIsRefreshing(false);
    }
  }, [applySnapshot]);

  useEffect(() => {
    let stopped = false;
    const poll = async () => {
      if (!stopped) await refresh();
    };

    poll();
    const interval = setInterval(poll, POLL_INTERVAL_MS);
    return () => {
      stopped = true;
      clearInterval(interval);
    };
  }, [refresh]);

  return { health, telemetry, statusText, isRefreshing, refresh };
}
