// src/components/topbar/ConnectionPanel.jsx
import React from 'react';
import useDroneStateStore from '../../store/droneStateStore';
import styles from './TopBar.module.css';
import { connectWebSocket, disconnectWebSocket } from '../../services/websocket.js';


const ConnectionPanel = () => {
  // Mengambil state dan action dari Zustand
  const isConnected = useDroneStateStore((state) => state.isConnected);
  const port = useDroneStateStore((state) => state.port);
  const setConnectionStatus = useDroneStateStore((state) => state.setConnectionStatus);
  const setPort = useDroneStateStore((state) => state.setPort);

  const handleConnectToggle = () => {
  if (isConnected) {
    disconnectWebSocket();
  } else {
    // Kita bisa mengirim port ke Flask via API terlebih dahulu jika perlu, 
    // lalu buka WebSocket
    connectWebSocket();
  }
};

  return (
    <div className={styles.connectionPanel}>
      <select 
        className={styles.selectBox} 
        value={port} 
        onChange={(e) => setPort(e.target.value)}
        disabled={isConnected}
      >
        <option value="udp://:14550">UDP (14550) - SITL</option>
        <option value="/dev/ttyUSB0">Serial (/dev/ttyUSB0)</option>
        <option value="COM3">Serial (COM3)</option>
      </select>

      <button 
        className={`${styles.connectBtn} ${isConnected ? styles.connected : ''}`}
        onClick={handleConnectToggle}
      >
        {isConnected ? 'DISCONNECT' : 'CONNECT'}
      </button>

      <div className={styles.statusBadge}>
        <div className={`${styles.dot} ${isConnected ? styles.active : ''}`}></div>
        <span>{isConnected ? 'LINK ACTIVE' : 'NO LINK'}</span>
      </div>
    </div>
  );
};

export default ConnectionPanel;
