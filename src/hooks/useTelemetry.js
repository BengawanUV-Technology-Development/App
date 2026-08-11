import { useCallback, useEffect, useRef, useState } from "react";
import { apiGet, webSocketUrl } from "../services/api";

const initialHealth = {
  connected: false,
  status: "OFFLINE",
  error: null,
  last_update: null,
  stale: true,
  gps_valid: false,
  bridge: null,
  websocket: "DISCONNECTED",
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
  if (health.websocket === "RECONNECTING") return "WebSocket reconnecting...";
  if (!health.bridge?.online) return "Mission Planner bridge offline";
  if (health.stale) return "Mission Planner telemetry stale";
  if (health.connected) return "Mission Planner telemetry active";
  return "Mission Planner connected, waiting for vehicle";
}

export function useTelemetry() {
  const [health, setHealth] = useState(initialHealth);
  const [telemetry, setTelemetry] = useState(initialTelemetry);
  const [statusText, setStatusText] = useState("Menghubungkan ke backend Python...");
  const [isRefreshing, setIsRefreshing] = useState(false);
  const socketRef = useRef(null);
  const reconnectTimerRef = useRef(null);

  const updateWebSocketStatus = useCallback((websocket) => {
    setHealth((previous) => {
      const nextHealth = { ...previous, websocket };
      setStatusText(deriveStatusText(nextHealth));
      return nextHealth;
    });
  }, []);

  const applySnapshot = useCallback((snapshot, websocket = null) => {
    if (!snapshot?.telemetry) return;
    setTelemetry(snapshot.telemetry);
    setHealth((previous) => {
      const nextHealth = {
        connected: Boolean(snapshot.telemetry.connected) && !snapshot.stale,
        status: snapshot.telemetry.status,
        error: snapshot.telemetry.error,
        last_update: snapshot.telemetry.last_update,
        stale: snapshot.stale,
        gps_valid: snapshot.gps_valid,
        bridge: snapshot.bridge,
        source: snapshot.telemetry.source,
        websocket: websocket || previous.websocket,
      };
      setStatusText(deriveStatusText(nextHealth));
      return nextHealth;
    });
  }, []);

  const refresh = useCallback(async () => {
    setIsRefreshing(true);
    try {
      const [healthResult, telemetryResult] = await Promise.all([
        apiGet("/api/v1/health"),
        apiGet("/api/v1/telemetry"),
      ]);

      if (!healthResult.ok || !telemetryResult.ok) {
        throw new Error(healthResult.error || telemetryResult.error || "Backend response was not ok");
      }

      applySnapshot(telemetryResult.data);
      return { health: healthResult.data, telemetry: telemetryResult.data.telemetry };
    } catch (error) {
      setHealth((previous) => ({ ...previous, connected: false, error: String(error) }));
      setStatusText("Backend Python belum bisa diakses");
      console.error("Error fetching from Python:", error);
      return { health: null, telemetry: null, error: String(error) };
    } finally {
      setIsRefreshing(false);
    }
  }, [applySnapshot]);

  useEffect(() => {
    let stopped = false;

    const connect = () => {
      if (stopped) return;
      updateWebSocketStatus("CONNECTING");
      const socket = new WebSocket(webSocketUrl("/api/v1/events"));
      socketRef.current = socket;

      socket.onopen = () => {
        updateWebSocketStatus("CONNECTED");
      };
      socket.onmessage = (event) => {
        const message = JSON.parse(event.data);
        if (message.type === "telemetry.updated") {
          applySnapshot(message.data, "CONNECTED");
        }
      };
      socket.onclose = () => {
        if (stopped) return;
        updateWebSocketStatus("RECONNECTING");
        reconnectTimerRef.current = setTimeout(connect, 1500);
      };
      socket.onerror = () => socket.close();
    };

    refresh();
    connect();
    const fallbackInterval = setInterval(() => {
      if (socketRef.current?.readyState !== WebSocket.OPEN) refresh();
    }, 2000);

    return () => {
      stopped = true;
      clearInterval(fallbackInterval);
      clearTimeout(reconnectTimerRef.current);
      socketRef.current?.close();
    };
  }, [applySnapshot, refresh, updateWebSocketStatus]);

  return { health, telemetry, statusText, isRefreshing, refresh };
}
