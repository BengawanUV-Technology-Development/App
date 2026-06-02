// src/services/websocket.js
// NOTE: Backend saat ini menggunakan HTTP Polling, bukan WebSocket murni.
// File ini bertindak sebagai bridge (penghubung) agar UI tetap sinkron.

import useTelemetryStore from '../store/telemetryStore';
import useDroneStateStore from '../store/droneStateStore';

let pollingTimer = null;
const API_URL = 'http://localhost:5001';

export const connectWebSocket = () => {
  // Jika sudah jalan, jangan buat double loop
  if (pollingTimer) return;

  console.log('[Telemetry] Memulai HTTP Polling ke backend...');

  const poll = async () => {
    try {
      const response = await fetch(`${API_URL}/telemetry`);
      if (response.ok) {
        const data = await response.json();
        
        // 1. Sinkronisasi Status Koneksi Dasar
        useDroneStateStore.getState().setConnectionStatus(data.connected);
        
        // 2. Sinkronisasi Telemetri (The Big 6 & HUD)
        // Kita map field backend (alt, groundspeed_m_s, dll) ke store frontend
        useTelemetryStore.getState().updateTelemetry({
          altitude: data.alt ?? 0,
          speed: data.groundspeed_m_s ?? 0,
          battery: data.battery_percent ?? 0,
          pitch: data.pitch_deg ?? 0,
          roll: data.roll_deg ?? 0,
          heading: data.heading_deg ?? 0,
          vSpeed: data.v_speed_m_s ?? 0,
          lat: data.lat ?? 0,
          lng: data.lng ?? 0,
          airspeed: data.airspeed_m_s ?? 0,
        });

        // 3. Sinkronisasi State Drone (Armed & Mode)
        if (data.armed !== undefined) {
          useDroneStateStore.getState().setArmed(data.armed);
        }
        if (data.flight_mode !== undefined) {
          useDroneStateStore.getState().setFlightMode(data.flight_mode);
        }
      } else {
        useDroneStateStore.getState().setConnectionStatus(false);
      }
    } catch (error) {
      // Jika fetch gagal (misal server mati), set offline
      useDroneStateStore.getState().setConnectionStatus(false);
    }

    // Jalankan loop lagi setelah 200ms (5Hz)
    pollingTimer = setTimeout(poll, 200);
  };

  poll();
};

export const disconnectWebSocket = () => {
  if (pollingTimer) {
    console.log('[Telemetry] Menghentikan polling...');
    clearTimeout(pollingTimer);
    pollingTimer = null;
    useDroneStateStore.getState().setConnectionStatus(false);
  }
};
