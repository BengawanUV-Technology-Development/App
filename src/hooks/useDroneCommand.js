// src/hooks/useDroneCommand.js
import { useState } from 'react';
import * as api from '../services/api';
import useDroneStateStore from '../store/droneStateStore';

export const useDroneCommand = () => {
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState(null);

  // Ambil fungsi update dari Zustand untuk langsung sinkronisasi UI
  const setArmed = useDroneStateStore((state) => state.setArmed);
  const setFlightMode = useDroneStateStore((state) => state.setFlightMode);

  // Helper generik untuk mengeksekusi API
  const executeCommand = async (apiCall, onSuccessCallback) => {
    setIsLoading(true);
    setError(null);
    try {
      const response = await apiCall();
      if (response.success) {
        if (onSuccessCallback) onSuccessCallback();
        return true;
      } else {
        setError(response.error || 'Perintah ditolak oleh FCU');
        return false;
      }
    } catch (err) {
      setError('Gagal menghubungi backend');
      return false;
    } finally {
      setIsLoading(false);
    }
  };

  const toggleArm = async (currentArmedStatus) => {
    if (currentArmedStatus) {
      await executeCommand(api.disarmDrone, () => setArmed(false));
    } else {
      await executeCommand(api.armDrone, () => setArmed(true));
    }
  };

  const changeMode = async (newMode) => {
    await executeCommand(() => api.setMode(newMode), () => setFlightMode(newMode));
  };

  const triggerReboot = async () => {
    await executeCommand(api.rebootFCU);
  };

  return { 
    isLoading, 
    error, 
    toggleArm, 
    changeMode, 
    triggerReboot 
  };
};