// src/components/topbar/ConnectionPanel.jsx
import { useEffect, useState } from 'react';
import { listPorts, setConnection } from '../../services/api';
import { connectWebSocket, disconnectWebSocket } from '../../services/websocket.js';
import useDroneStateStore from '../../store/droneStateStore';
import styles from './TopBar.module.css';


const ConnectionPanel = () => {
  const [availablePorts, setAvailablePorts] = useState([]);
  const [isManual, setIsManual] = useState(false);
  const [manualAddress, setManualAddress] = useState('');

  // Mengambil state dan action dari Zustand
  const isConnected = useDroneStateStore((state) => state.isConnected);
  const port = useDroneStateStore((state) => state.port);
  const setPort = useDroneStateStore((state) => state.setPort);
  const setConnectionPhase = useDroneStateStore((state) => state.setConnectionPhase);

  const formatPortLabel = (portValue) => {
    if (!portValue) return 'Unknown port';

    if (portValue.startsWith('serial://')) {
      const serialBody = portValue.replace('serial://', '');
      const [deviceName, baudRate] = serialBody.split(':');
      return baudRate ? `${deviceName} (${baudRate})` : deviceName;
    }

    if (portValue.startsWith('udp://')) {
      return portValue.replace('udp://', 'UDP ');
    }

    return portValue;
  };

  const normalizePortValue = (portValue) => {
    if (typeof portValue !== 'string') return '';
    if (portValue.startsWith('serial://') || portValue.startsWith('udp://')) {
      return portValue;
    }
    if (/^COM\d+$/i.test(portValue) || portValue.startsWith('/dev/')) {
      return `serial://${portValue}:115200`;
    }
    return portValue;
  };

  const getDeviceValue = (device) => normalizePortValue(device);

  const refreshPorts = async () => {
    const res = await listPorts();
    if (res.success) {
      const fetchedPorts = res.data.ports || [];
      setAvailablePorts(fetchedPorts);

      // If the current selection is not visible, keep it if it is a serial port,
      // otherwise move to the first detected physical device.
      const normalizedPort = normalizePortValue(port);
      const isInList = fetchedPorts.some((p) => getDeviceValue(p.device) === normalizedPort);
      const isSerialPort = typeof normalizedPort === 'string' && normalizedPort.startsWith('serial://');

      if (!isInList && fetchedPorts.length > 0 && !isSerialPort) {
        setPort(getDeviceValue(fetchedPorts[0].device));
      }
    }
  };

  const selectedPort = isManual ? manualAddress : normalizePortValue(port || 'serial://COM9:115200');
  const hasKnownSelection =
    availablePorts.some((p) => getDeviceValue(p.device) === selectedPort);

  useEffect(() => {
    refreshPorts();
    // Refresh ports every 5 seconds if not connected
    const interval = setInterval(() => {
      if (!isConnected) refreshPorts();
    }, 5000);
    return () => clearInterval(interval);
  }, [isConnected, port]);

  const handleConnectToggle = async () => {
    if (isConnected) {
      disconnectWebSocket();
      setConnectionPhase('DISCONNECTED');
    } else {
      const targetAddress = isManual ? manualAddress : port;
      if (!targetAddress) {
        alert("Please select a port or enter an address");
        return;
      }

      setPort(targetAddress);

      console.log(`[Connection] Attempting connect to: ${targetAddress}`);
      setConnectionPhase('CONNECTING');

      // Kirim port terpilih ke backend terlebih dahulu
      const res = await setConnection(targetAddress);
      if (res.success) {
        connectWebSocket();
        // The websocket service will handle moving to 'GETTING_PARAMS' or 'DISCONNECTED'
      } else {
        setConnectionPhase('DISCONNECTED');
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
              className="bg-slate-900 text-emerald-400 border border-slate-700 rounded-sm px-2 py-1 text-xs outline-none focus:border-emerald-500 min-w-[140px] appearance-none cursor-pointer font-mono"
              value={selectedPort}
              onChange={(e) => setPort(e.target.value)}
              disabled={isConnected}
            >
              {!isManual && selectedPort && !hasKnownSelection && (
                <option value={selectedPort} className="bg-slate-900 text-emerald-400">
                  Current: {formatPortLabel(selectedPort)}
                </option>
              )}
              <optgroup label="Virtual Link" className="bg-slate-900 text-slate-400">
                <option value="udpin://0.0.0.0:14550" className="bg-slate-900 text-emerald-400">UDP (14550) - SITL</option>
              </optgroup>
              {availablePorts.length > 0 && (
                <optgroup label="Physical Devices" className="bg-slate-900 text-slate-400">
                  {availablePorts.map((p) => (
                    <option key={p.device} value={getDeviceValue(p.device)} className="bg-slate-900 text-emerald-400">
                      {p.device.replace('serial://', '').split(':')[0]} - {(p.description || 'Unknown device').substring(0, 20)}
                    </option>
                  ))}
                </optgroup>
              )}
            </select>
          ) : (
            <input
              type="text"
              className="bg-slate-900 text-emerald-400 border border-slate-700 rounded-sm px-2 py-1 text-xs outline-none focus:border-emerald-500 min-w-[140px] font-mono"
              placeholder="serial://COM9:115200"
              value={manualAddress}
              onChange={(e) => setManualAddress(e.target.value)}
              disabled={isConnected}
            />
          )}

          <button
            className="text-[10px] text-slate-500 hover:text-emerald-400 transition-colors underline cursor-pointer font-bold tracking-tighter"
            onClick={() => setIsManual(!isManual)}
            disabled={isConnected}
          >
            {isManual ? '[ LIST ]' : '[ MANUAL ]'}
          </button>
        </div>
      </div>

      <button
        className={`px-4 py-1 rounded-sm font-bold text-xs transition-all active:scale-95 border ${isConnected
          ? 'bg-red-600/10 border-red-600 text-red-600 hover:bg-red-600 hover:text-white shadow-[0_0_10px_rgba(220,38,38,0.3)]'
          : 'bg-emerald-600/10 border-emerald-600 text-emerald-500 hover:bg-emerald-600 hover:text-white shadow-[0_0_10px_rgba(16,185,129,0.3)]'
          }`}
        onClick={handleConnectToggle}
      >
        {isConnected ? 'DISCONNECT' : 'CONNECT'}
      </button>

      <div className="flex items-center gap-2 px-3 py-1 bg-slate-900/50 border border-slate-800 rounded-full">
        <div className={`w-2 h-2 rounded-full ${isConnected ? 'bg-emerald-500 animate-pulse shadow-[0_0_8px_#10b981]' : 'bg-slate-600'}`}></div>
        <span className={`text-[10px] font-mono font-bold ${isConnected ? 'text-emerald-500' : 'text-slate-500'}`}>
          {isConnected ? 'LINK ACTIVE' : 'NO LINK'}
        </span>
      </div>
    </div>
  );
};

export default ConnectionPanel;
