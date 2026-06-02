// src/services/websocket.js
// NOTE: Backend saat ini menggunakan HTTP Polling, bukan WebSocket murni.
// File ini bertindak sebagai bridge (penghubung) agar UI tetap sinkron.

import useDroneStateStore from '../store/droneStateStore';
import useTelemetryStore from '../store/telemetryStore';

let pollingTimer = null;
const API_URL = 'http://localhost:5001';

const MODE_ALIASES = {
  Q_HOVER: 'QHOVER',
  Q_STABILIZE: 'QSTABILIZE',
  Q_LAND: 'QLAND',
};

const normalizeFlightMode = (mode) => {
  if (typeof mode !== 'string') return null;
  const canonical = mode.trim().toUpperCase();
  const token = canonical.split('.').pop();
  return MODE_ALIASES[token] || token;
};

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
const wasConnected = useDroneStateStore.getState().isConnected;
const currentPhase = useDroneStateStore.getState().connectionPhase;

useDroneStateStore.getState().setConnectionStatus(data.connected);

// Handle Modal Phases
if (data.connected && currentPhase === 'CONNECTING') {
  useDroneStateStore.getState().setConnectionPhase('GETTING_PARAMS');
  // Simulasi loading param sebentar agar user merasa familiar (Mission Planner Style)
  setTimeout(() => {
     useDroneStateStore.getState().setConnectionPhase('DISCONNECTED');
  }, 1500);
}

if (!data.connected && currentPhase !== 'DISCONNECTED') {
   // Jika backend lapor disconnected tapi modal masih nongol (karena error timeout dsb)
   // Biarkan tetap di phase CONNECTING agar auto-retry jalan, atau reset jika fatal
}

        // --- Status Text Sync ---
        if (data.status_text && data.status_text !== useTelemetryStore.getState().statusText) {
          const timeStr = new Date().toLocaleTimeString('en-GB', { hour12: false });
          let color = 'text-slate-400';
          const textUpper = data.status_text.toUpperCase();
          
          if (textUpper.includes('ERROR') || textUpper.includes('EMERGENCY') || textUpper.includes('CRITICAL') || textUpper.includes('PREARM')) {
            color = 'text-red-400 font-bold shadow-[0_0_8px_rgba(248,113,113,0.4)]';
          } else if (textUpper.includes('WARNING') || textUpper.includes('NOTICE')) {
            color = 'text-amber-400';
          } else if (textUpper.includes('INFO') || textUpper.includes('ARMED') || textUpper.includes('DISARMED')) {
            color = 'text-emerald-400';
          }
          
          useTelemetryStore.getState().addSystemLog({ time: timeStr, text: data.status_text, color });
        }
        
        // 2. Sinkronisasi Telemetri (The Big 6 & HUD)
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
          statusText: data.status_text ?? '',
          
          ekf: {
            velocity: data.ekf_velocity ?? 0,
            posHoriz: data.ekf_pos_horiz ?? 0,
            posVert: data.ekf_pos_vert ?? 0,
            compass: data.ekf_compass ?? 0,
            terrain: data.ekf_terrain ?? 0,
          },

          vibration: {
            x: data.vibration_x ?? 0,
            y: data.vibration_y ?? 0,
            z: data.vibration_z ?? 0,
            clipping0: data.vibration_clip0 ?? 0,
            clipping1: data.vibration_clip1 ?? 0,
            clipping2: data.vibration_clip2 ?? 0,
          }
        });

        // 3. Sinkronisasi State Drone (Armed & Mode)
        if (data.armed !== undefined) {
          useDroneStateStore.getState().setArmed(data.armed);
        }
        
        if (data.flight_mode) {
          const rawMode = data.flight_mode.split('.').pop().toUpperCase().replace('_', '');
          const store = useDroneStateStore.getState();
          
          // LOCK LOGIC: Only update UI if we are NOT in the middle of a manual mode change
          if (!store.isChangingMode) {
            store.setFlightMode(rawMode);
          }
        }
        if (data.system_address) {
          useDroneStateStore.getState().setPort(data.system_address);
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
