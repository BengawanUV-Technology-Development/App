// src/store/uiStore.js
import { create } from 'zustand';

const useUiStore = create((set) => ({
  // Layout States
  isWpPanelOpen: false,

  // Actions
  toggleWpPanel: () => set((state) => ({ isWpPanelOpen: !state.isWpPanelOpen })),
  setWpPanelOpen: (status) => set({ isWpPanelOpen: status }),
}));

export default useUiStore;