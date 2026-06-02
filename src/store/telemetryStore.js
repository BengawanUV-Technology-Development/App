// src/store/telemetryStore.js
import { create } from 'zustand';

const useTelemetryStore = create((set) => ({
  // Data "The Big 6"
  altitude: 0.0,
  speed: 0.0,
  battery: 100.0,
  distToHome: 0,
  vSpeed: 0.0,
  wind: 0.0,
  statusText: '',
  statusTextType: '',
  prearmMessage: '',

  // Data Orientasi (Untuk Canvas HUD)
  pitch: 0,
  roll: 0,
  heading: 0,
  lat: 0,
  lng: 0,
  airspeed: 0,

  // EKF Status (0.0 to 1.0)
  ekf: {
    velocity: 0,
    posHoriz: 0,
    posVert: 0,
    compass: 0,
    terrain: 0
  },

  // Vibration (m/s^2)
  vibration: {
    x: 0,
    y: 0,
    z: 0,
    clipping0: 0,
    clipping1: 0,
    clipping2: 0
  },

  // System Logs History
  systemLogs: [],

  // Fungsi untuk mengupdate banyak data sekaligus secara efisien
  updateTelemetry: (newData) => set((state) => ({
    ...state,
    ...newData
  })),

  // Fungsi khusus untuk menambah log baru tanpa mereset array
  addSystemLog: (log) => set((state) => {
    // Hindari spam log yang persis sama
    if (state.systemLogs.length > 0 && state.systemLogs[0].text === log.text) {
      return state;
    }
    // Simpan maksimum 50 log terakhir
    return { systemLogs: [log, ...state.systemLogs].slice(0, 50) };
  }),
}));

export default useTelemetryStore;