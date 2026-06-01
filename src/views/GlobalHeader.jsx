import React, { useState } from 'react';
import useDroneStateStore from '../store/droneStateStore';
import useTelemetryStore from '../store/telemetryStore';
import { connectWebSocket, disconnectWebSocket } from '../services/websocket';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../components/ui/select';

export default function GlobalHeader({ globalTab, onGlobalTabChange, localTab, onLocalTabChange }) {
  const { isArmed, activeMode, isConnected, port, setPort } = useDroneStateStore();
  const battery = useTelemetryStore(state => state.battery);

  // MOCK DATA: Ready for future backend integration
  const availablePorts = ["udp://:14550", "/dev/ttyUSB0", "COM3", "COM4"];
  const availableBauds = ["57600", "115200", "921600"];
  const [baudRate, setBaudRate] = useState("115200");

  const handleConnectToggle = () => {
    if (isConnected) {
      disconnectWebSocket();
    } else {
      connectWebSocket(); // In a real scenario, you'd pass `port` and `baudRate` here if websocket.js needed them
    }
  };

  return (
    <header className="h-12 border-b border-slate-300 bg-white flex justify-between items-center px-4 gap-4 shrink-0 shadow-sm z-50">
      
      {/* Left Group */}
      <div className="flex items-center gap-5 shrink-0">
        <div className="flex items-center gap-2">
          
          {/* RADIX UI PORT DROPDOWN */}
          <Select value={port} onValueChange={setPort} disabled={isConnected}>
            <SelectTrigger className="h-7 min-w-[120px] px-2 py-1 text-[11px] bg-slate-50 border-slate-300 text-slate-700 font-mono shadow-inner rounded-sm">
              <SelectValue placeholder="Select Port" />
            </SelectTrigger>
            <SelectContent className="bg-white border-slate-300 shadow-lg z-[100]">
              {availablePorts.map((p) => (
                <SelectItem key={p} value={p} className="text-[11px] text-slate-700 font-mono">{p}</SelectItem>
              ))}
            </SelectContent>
          </Select>

          {/* RADIX UI BAUDRATE DROPDOWN */}
          <Select value={baudRate} onValueChange={setBaudRate} disabled={isConnected}>
            <SelectTrigger className="h-7 w-[80px] px-2 py-1 text-[11px] bg-slate-50 border-slate-300 text-slate-700 font-mono shadow-inner rounded-sm">
              <SelectValue placeholder="Baud" />
            </SelectTrigger>
            <SelectContent className="bg-white border-slate-300 shadow-lg z-[100]">
              {availableBauds.map((b) => (
                <SelectItem key={b} value={b} className="text-[11px] text-slate-700 font-mono">{b}</SelectItem>
              ))}
            </SelectContent>
          </Select>
          
          <button 
            onClick={handleConnectToggle}
            className={`${isConnected ? 'bg-red-600 hover:bg-red-700' : 'bg-emerald-600 hover:bg-emerald-700'} text-white px-3 py-1 text-[11px] font-bold rounded-sm transition-colors uppercase`}
          >
            {isConnected ? '[DISCONNECT]' : '[CONNECT]'}
          </button>
        </div>
        <div className="flex bg-slate-200 p-0.5 rounded-sm border border-slate-300 shadow-inner">
          <button onClick={() => onGlobalTabChange("fly")} className={globalTab === "fly" ? "bg-white text-emerald-700 shadow-sm font-bold px-3 py-1 text-[11px] rounded-sm transition-colors" : "text-slate-500 hover:text-slate-700 font-bold px-3 py-1 text-[11px] transition-colors"}>FLY TACTICAL</button>
          <button onClick={() => onGlobalTabChange("plan")} className={globalTab === "plan" ? "bg-white text-emerald-700 shadow-sm font-bold px-3 py-1 text-[11px] rounded-sm transition-colors" : "text-slate-500 hover:text-slate-700 font-bold px-3 py-1 text-[11px] transition-colors"}>PLAN & SETUP</button>
        </div>
      </div>

      {/* Center Group (Contextual Local Nav) */}
      <div className="flex items-center justify-center shrink-0">
        {globalTab === "plan" && (
          <div className="flex bg-slate-200 p-0.5 rounded-sm border border-slate-300 select-none shadow-inner">
            <button onClick={() => onLocalTabChange?.("mission")} className={localTab === "mission" ? "bg-blue-600 text-white font-bold h-8 px-4 rounded-sm text-[11px] flex items-center shadow-sm transition-colors" : "text-slate-500 hover:text-slate-700 font-bold px-4 py-1 text-[11px] flex items-center transition-colors"}>1. Mission Editor</button>
            <button onClick={() => onLocalTabChange?.("hardware")} className={localTab === "hardware" ? "bg-blue-600 text-white font-bold h-8 px-4 rounded-sm text-[11px] flex items-center shadow-sm transition-colors" : "text-slate-500 hover:text-slate-700 font-bold px-4 py-1 text-[11px] flex items-center transition-colors"}>2. Params & Calibration</button>
          </div>
        )}
      </div>

      {/* Right Group (Telemetry) */}
      <div className="flex items-center gap-3 font-mono text-[10px] font-bold shrink-0 whitespace-nowrap">
        <span className="text-slate-600 bg-slate-100 border border-slate-300 px-2 py-0.5 rounded-sm">
          MODE: {activeMode.toUpperCase()}
        </span>
        <span className="text-slate-600 bg-slate-100 border border-slate-300 px-2 py-0.5 rounded-sm">
          SYS: {isArmed ? "ARMED" : "DISARMED"}
        </span>
        <span className="text-slate-600">VOLTAGE: N/A</span>
        <span className={`${battery < 30 ? 'text-red-600 animate-pulse' : 'text-slate-600'}`}>BAT: {battery}%</span>
        <span className="text-slate-600">GPS: N/A</span>
        <span className="text-slate-600">LINK: N/A</span>
      </div>
    </header>
  );
}