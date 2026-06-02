// src/services/api.js

const API_BASE_URL = 'http://localhost:5001'; // Sesuaikan dengan port Flask (5001)

// Helper function untuk mengirim request
const sendRequest = async (endpoint, method = 'POST', payload = null) => {
  try {
    const options = {
      method,
      headers: {
        'Content-Type': 'application/json',
      },
    };

    if (payload) {
      options.body = JSON.stringify(payload);
    }

    const response = await fetch(`${API_BASE_URL}${endpoint}`, options);
    const data = await response.json();

    // Backend Python mengembalikan field "ok": true/false
    if (!response.ok || (data && data.ok === false)) {
      throw new Error(data.error || data.message || 'Permintaan ke backend gagal');
    }

    return { success: true, data };
  } catch (error) {
    console.error(`[API Error] ${endpoint}:`, error.message);
    return { success: false, error: error.message };
  }
};

// --- Daftar Fungsi API ---

export const armDrone = () => {
  return sendRequest('/command/arm', 'POST');
};

export const disarmDrone = () => {
  return sendRequest('/command/disarm', 'POST');
};

export const setMode = (modeName) => {
  // Endpoint backend: /command/set_flight_mode
  return sendRequest('/command/set_flight_mode', 'POST', { mode: modeName });
};

export const uploadWaypoints = (waypoints) => {
  // Transformasi data agar sesuai dengan schema MissionItem di MAVSDK
  const formattedWaypoints = waypoints.map((wp, index) => ({
    latitude_deg: wp.lat,
    longitude_deg: wp.lng,
    relative_altitude_m: wp.alt,
    seq: index
  }));

  return sendRequest('/mission/upload', 'POST', { waypoints: formattedWaypoints });
};

export const rebootFCU = () => {
  return sendRequest('/command/reboot', 'POST');
};

export const calibrateGyro = () => {
  // Sesuaikan jika endpoint kalibrasi sudah diimplementasikan di backend
  return sendRequest('/command/calibrate-gyro', 'POST');
};

export const setParameter = (paramId, paramValue) => {
  return sendRequest('/config/param', 'POST', { id: paramId, value: paramValue });
};

export const setConnection = (address) => {
  return sendRequest('/command/connection', 'POST', { address });
};