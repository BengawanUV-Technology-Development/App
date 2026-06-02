import React, { useState, useMemo } from 'react';
import styles from './BottomBar.module.css';
import { calibrateGyro, getParameter, setParameter } from '../../services/api';
import useTelemetryStore from '../../store/telemetryStore';

// Common ArduPilot Parameters for Search & Scroll
const COMMON_PARAMS = [
  { name: "ARMING_CHECK", desc: "All Pre-arm checks bitmask" },
  { name: "FS_THR_ENABLE", desc: "Throttle Failsafe Enable" },
  { name: "FS_GND_ENABLE", desc: "Ground Failsafe Enable" },
  { name: "BATT_MONITOR", desc: "Battery Monitoring Type" },
  { name: "BATT_CAPACITY", desc: "Battery Capacity (mAh)" },
  { name: "RTL_ALT", desc: "Return to Launch Altitude" },
  { name: "WP_SPEED", desc: "Waypoint Speed (m/s)" },
  { name: "TRIM_THROTTLE", desc: "Throttle trim percentage" },
  { name: "SERVO_AUTO_TRIM", desc: "Auto trim enable" },
  { name: "SERIAL0_BAUD", desc: "USB Port Baudrate" },
  { name: "EK3_ENABLE", desc: "Enable EKF3" },
  { name: "Q_ENABLE", desc: "Enable QuadPlane" },
  { name: "Q_ASSIST_SPEED", desc: "Speed below which Q-assist kicks in" },
  { name: "Q_RTL_MODE", desc: "Q-RTL behavior" }
];

const ConfigQuick = () => {
  const [paramSearch, setParamSearch] = useState('');
  const [paramValue, setParamValue] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [showDropdown, setShowDropdown] = useState(false);
  const addLog = useTelemetryStore((state) => state.addSystemLog);

  // Filter list berdasarkan ketikan user
  const filteredParams = useMemo(() => {
    return COMMON_PARAMS.filter(p => 
      p.name.toLowerCase().includes(paramSearch.toLowerCase())
    );
  }, [paramSearch]);

  const handleGetParam = async (nameOverride) => {
    const name = nameOverride || paramSearch;
    if (!name) return;
    setIsLoading(true);
    setShowDropdown(false);
    
    const res = await getParameter(name.toUpperCase());
    setIsLoading(false);
    
    if (res.success) {
      setParamSearch(res.data.param_name);
      setParamValue(res.data.param_value);
      addLog({ 
        time: new Date().toLocaleTimeString('en-GB', { hour12: false }), 
        text: `READ ${res.data.param_name}: ${res.data.param_value}`,
        color: 'text-emerald-400'
      });
    } else {
      addLog({ 
        time: new Date().toLocaleTimeString('en-GB', { hour12: false }), 
        text: `READ ERROR: ${res.error}`,
        color: 'text-red-400'
      });
    }
  };

  const handleSetParam = async () => {
    if (!paramSearch || paramValue === '') return;
    setIsLoading(true);
    const res = await setParameter(paramSearch.toUpperCase(), paramValue);
    setIsLoading(false);
    
    if (res.success) {
      addLog({ 
        time: new Date().toLocaleTimeString('en-GB', { hour12: false }), 
        text: `SET ${paramSearch} OK`,
        color: 'text-emerald-400 font-bold'
      });
    } else {
      alert(`Error: ${res.error}`);
    }
  };

  const handleBypass = async () => {
    if (!window.confirm("Bypass RC failsafes? (Persists on FC)")) return;
    setIsLoading(true);
    await setParameter("ARMING_CHECK", 0);
    await setParameter("FS_THR_ENABLE", 0);
    setIsLoading(false);
    addLog({ 
      time: new Date().toLocaleTimeString('en-GB', { hour12: false }), 
      text: "Failsafes Bypassed", 
      color: 'text-amber-400 font-bold' 
    });
  };

  return (
    <div className="flex flex-col h-full bg-slate-900/40 p-2 gap-2 text-white border-l border-slate-800 min-w-[280px]">
      <div className="flex items-center justify-between border-b border-slate-700 pb-1">
        <span className="text-[10px] font-bold tracking-widest text-slate-500 uppercase">Parameter Explorer</span>
        {isLoading && <div className="w-1.5 h-1.5 bg-emerald-500 rounded-full animate-ping" />}
      </div>

      <div className="flex flex-col gap-1.5 relative">
        {/* Search & Read Area */}
        <div className="flex gap-1">
          <div className="flex-1 relative">
            <input 
              type="text" 
              placeholder="Search Param..."
              className="w-full bg-black/40 border border-slate-700 rounded-sm px-2 py-1 text-[10px] font-mono text-emerald-400 outline-none focus:border-emerald-500 transition-colors"
              value={paramSearch}
              onChange={(e) => {
                setParamSearch(e.target.value);
                setShowDropdown(true);
              }}
              onFocus={() => setShowDropdown(true)}
            />
            
            {/* Scrollable Dropdown List */}
            {showDropdown && (
              <div className="absolute bottom-full left-0 w-full bg-slate-800 border border-slate-600 rounded-sm mb-1 max-h-32 overflow-y-auto z-50 shadow-xl scrollbar-thin scrollbar-thumb-slate-600">
                {filteredParams.map(p => (
                  <div 
                    key={p.name}
                    className="px-2 py-1 hover:bg-slate-700 cursor-pointer flex flex-col border-b border-slate-700/50"
                    onClick={() => {
                      setParamSearch(p.name);
                      handleGetParam(p.name);
                    }}
                  >
                    <span className="text-[9px] font-bold text-emerald-400">{p.name}</span>
                    <span className="text-[7px] text-slate-400 leading-tight">{p.desc}</span>
                  </div>
                ))}
                {filteredParams.length === 0 && (
                  <div className="px-2 py-1 text-[8px] text-slate-500 italic">No matches...</div>
                )}
              </div>
            )}
          </div>
          <button 
            onClick={() => handleGetParam()}
            className="bg-slate-700 hover:bg-slate-600 px-3 rounded-sm text-[9px] font-bold uppercase transition-colors"
          >
            Read
          </button>
        </div>
        
        {/* Value & Write Area */}
        <div className="flex gap-1">
          <input 
            type="text" 
            placeholder="Value"
            className="flex-1 bg-black/40 border border-slate-700 rounded-sm px-2 py-1 text-[10px] font-mono text-white outline-none focus:border-emerald-500 transition-colors"
            value={paramValue}
            onChange={(e) => setParamValue(e.target.value)}
          />
          <button 
            onClick={handleSetParam}
            className="bg-emerald-600/30 border border-emerald-600/50 hover:bg-emerald-600 hover:text-white px-3 rounded-sm text-[9px] font-bold uppercase transition-all"
          >
            Write
          </button>
        </div>
      </div>

      <div className="mt-auto border-t border-slate-800 pt-1.5 flex flex-col gap-1">
        <div className="flex gap-1">
           <button 
            onClick={() => handleBypass()}
            className="flex-1 bg-amber-600/10 border border-amber-600/40 hover:bg-amber-600 hover:text-white text-amber-500 py-1 rounded-sm text-[8px] font-bold uppercase transition-all"
          >
            Bypass Failsafes
          </button>
          <button 
            onClick={() => setShowDropdown(!showDropdown)}
            className="bg-slate-800 px-2 rounded-sm text-[12px]"
          >
            ⚙️
          </button>
        </div>
      </div>
    </div>
  );
};

export default ConfigQuick;