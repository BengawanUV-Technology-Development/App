import { useCallback, useEffect, useState } from "react";
import { apiGet } from "../services/api";

const initialHealth = {
  connected: false,
  status: "OFFLINE",
  error: null,
  last_update: null,
  system_address: "-",
  mavsdk_server_port: null,
};

const initialTelemetry = {
  lat: null,
  lng: null,
  alt: null,
  alt_amsl: null,
  armed: null,
  flight_mode: null,
  battery_percent: null,
  roll_deg: null,
  pitch_deg: null,
  yaw_deg: null,
  heading_deg: null,
  airspeed_m_s: null,
  groundspeed_m_s: null,
  v_speed_m_s: null,
  last_update: null,
  error: null,
};

function deriveStatusText(health) {
  if (health.status === "REBOOTING") return "FC is rebooting...";
  if (health.connected) return "FC terhubung";
  if (health.error) return `Retrying: ${health.error}`;
  return "Backend aktif, menunggu heartbeat FC";
}

export function useTelemetry() {
  const [health, setHealth] = useState(initialHealth);
  const [telemetry, setTelemetry] = useState(initialTelemetry);
  const [statusText, setStatusText] = useState("Menghubungkan ke backend Python...");
  const [isRefreshing, setIsRefreshing] = useState(false);

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

      setHealth(healthResult.data);
      setTelemetry(telemetryResult.data);
      setStatusText(deriveStatusText(healthResult.data));
      return { health: healthResult.data, telemetry: telemetryResult.data };
    } catch (error) {
      setHealth((previous) => ({ ...previous, connected: false, error: String(error) }));
      setStatusText("Backend Python belum bisa diakses");
      console.error("Error fetching from Python:", error);
      return { health: null, telemetry: null, error: String(error) };
    } finally {
      setIsRefreshing(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, 1000);
    return () => clearInterval(interval);
  }, [refresh]);

  return { health, telemetry, statusText, isRefreshing, refresh };
}
