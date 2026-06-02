// src/store/droneStateStore.js
import { create } from 'zustand';

const useDroneStateStore = create((set) => ({
  // C2 (Command & Control) State
  isArmed: false,
  activeMode: 'Q_HOVER',
  
  // Connection State
  isConnected: false,
  port: 'serial://COM9:115200',

  // Actions
  setArmed: (status) => set({ isArmed: status }),
  setFlightMode: (mode) => set({ activeMode: mode }),
  setConnectionStatus: (status) => set({ isConnected: status }),
  setPort: (newPort) => set({ port: newPort }),
}));

export default useDroneStateStore;