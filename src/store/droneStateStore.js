// src/store/droneStateStore.js
import { create } from 'zustand';

const useDroneStateStore = create((set) => ({
  // C2 (Command & Control) State
  isArmed: false,
  activeMode: 'Q_HOVER',

  // Connection State
  isConnected: false,
  connectionPhase: 'DISCONNECTED', // 'DISCONNECTED', 'CONNECTING', 'GETTING_PARAMS'
  port: 'udp://:14550',

  // UI Locks
  isChangingMode: false,

  // Actions
  setArmed: (status) => set({ isArmed: status }),
  setFlightMode: (mode) => set({ activeMode: mode }),
  setConnectionStatus: (status) => set({ isConnected: status }),
  setConnectionPhase: (phase) => set({ connectionPhase: phase }),
  setChangingMode: (status) => set({ isChangingMode: status }),
  setPort: (newPort) => set({ port: newPort }),
}));

export default useDroneStateStore;