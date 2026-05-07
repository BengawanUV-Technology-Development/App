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

  // Data Orientasi (Untuk Canvas HUD)
  pitch: 0,
  roll: 0,
  heading: 0,

  // Fungsi untuk mengupdate banyak data sekaligus secara efisien
  updateTelemetry: (newData) => set((state) => ({
    ...state,
    ...newData
  })),
}));

export default useTelemetryStore;