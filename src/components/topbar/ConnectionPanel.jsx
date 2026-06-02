// src/components/topbar/ConnectionPanel.jsx
import React, { useEffect, useState } from 'react';
import useDroneStateStore from '../../store/droneStateStore';
import styles from './TopBar.module.css';
import { armDrone, disarmDrone, setConnection, listPorts } from '../../services/api';
import { connectWebSocket, disconnectWebSocket } from '../../services/websocket.js';


const ConnectionPanel = () => {
  const [availablePorts, setAvailablePorts] = useState([]);
  const [isManual, setIsManual] = useState(false);
  const [manualAddress, setManualAddress] = useState('');
  
  // Mengambil state dan action dari Zustand
  const isConnected = useDroneStateStore((state) => state.isConnected);
  const port = useDroneStateStore((state) => state.port);
  const setPort = useDroneStateStore((state) => state.setPort);

  const refreshPorts = async () => {
    const res = await listPorts();
    if (res.success) {
      const fetchedPorts = res.data.ports || [];
      setAvailablePorts(fetchedPorts);
      
      // FIX: If port is empty OR not in the new list (and not SITL), set it to the first found port
      const isSitl = port === "udp://:14550";
      const isInList = fetchedPorts.some(p => p.device === port);
      
      if (!isSitl && !isInList && fetchedPorts.length > 0) {
        setPort(fetchedPorts[0].device);
      } else if (!port && fetchedPorts.length === 0) {
        // Fallback to SITL if absolutely nothing found
        setPort("udp://:14550");
      }
    }
  };

  useEffect(() => {
    refreshPorts();
    // Refresh ports every 5 seconds if not connected
    const interval = setInterval(() => {
      if (!isConnected) refreshPorts();
    }, 5000);
    return () => clearInterval(interval);
  }, [isConnected]);

  const handleConnectToggle = async () => {
    if (isConnected) {
      disconnectWebSocket();
    } else {
      const targetAddress = isManual ? manualAddress : port;
      if (!targetAddress) {
        alert("Please select a port or enter an address");
        return;
      }
      console.log(`[Connection] Attempting connect to: ${targetAddress}`);
      // Kirim port terpilih ke backend terlebih dahulu
      const res = await setConnection(targetAddress);
      if (res.success) {
         connectWebSocket();
      } else {
         alert(`Gagal set port: ${res.error}`);
      }
    }
  };

  return (
    <div className={styles.connectionPanel}>
      <div className="flex flex-col gap-1">
        <div className="flex items-center gap-2">
          {!isManual ? (
            <select 
              className={styles.selectBox} 
              value={port || "udp://:14550"} 
              onChange={(e) => setPort(e.target.value)}
              disabled={isConnected}
            >
              <optgroup label="Virtual">
                <option value="udp://:14550">UDP (14550) - SITL Simulator</option>
              </optgroup>
              {availablePorts.length > 0 && (
                <optgroup label="Physical Ports">
                  {availablePorts.map((p) => (
                    <option key={p.device} value={p.device}>
                      {p.device} - {p.description.substring(0, 25)}...
                    </option>
                  ))}
                </optgroup>
              )}
            </select>
          ) : (
            <input 
              type="text"
              className={styles.selectBox}
              placeholder="e.g. serial://COM9:115200"
              value={manualAddress}
              onChange={(e) => setManualAddress(e.target.value)}
              disabled={isConnected}
            />
          )}
          
          <button 
            className="text-[10px] text-slate-400 hover:text-white transition-colors underline cursor-pointer"
            onClick={() => setIsManual(!isManual)}
            disabled={isConnected}
          >
            {isManual ? 'Use List' : 'Manual Input'}
          </button>
        </div>
      </div>

      <button 
        className={`${styles.connectBtn} ${isConnected ? styles.connected : ''}`}
        onClick={handleConnectToggle}
      >
        {isConnected ? 'DISCONNECT' : 'CONNECT'}
      </button>

      <div className={styles.statusBadge}>
        <div className={`${styles.dot} ${isConnected ? styles.active : ''}`}></div>
        <span className="font-mono">{isConnected ? 'LINK ACTIVE' : 'NO LINK'}</span>
      </div>
    </div>
  );
};

export default ConnectionPanel;
