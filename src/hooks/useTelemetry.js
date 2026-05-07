// src/hooks/useTelemetry.js
import { useEffect } from 'react';
import { connectWebSocket, disconnectWebSocket } from '../services/websocket.js';
import useDroneStateStore from '../store/droneStateStore';

export const useTelemetryConnection = () => {
  const isConnected = useDroneStateStore((state) => state.isConnected);
  const port = useDroneStateStore((state) => state.port);

  // Opsional: Jika Anda ingin WebSocket otomatis terputus saat aplikasi ditutup (unmount)
  useEffect(() => {
    return () => {
      disconnectWebSocket(); // Cleanup saat GCS ditutup
    };
  }, []);

  const toggleConnection = () => {
    if (isConnected) {
      disconnectWebSocket();
    } else {
      // Disini kita bisa mengoper 'port' ke fungsi connect jika backend membutuhkannya
      connectWebSocket(port);
    }
  };

  return { toggleConnection, isConnected, port };
};