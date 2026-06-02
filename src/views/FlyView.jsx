import React from 'react';
import MapView from '../components/centerarea/MapView';
import BottomBar from '../components/bottombar/BottomBar';
import { armDrone, disarmDrone, rebootFCU, setMode } from '../services/api';
import useDroneStateStore from '../store/droneStateStore';
import useTelemetryStore from '../store/telemetryStore';

const PitchLadder = ({ pitch }) => {
  const lines = [-30, -20, -10, 0, 10, 20, 30];
  return (
    <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
      {lines.map((deg) => (
        <div 
          key={deg}
          className="absolute border-t border-white/40 flex items-center justify-center"
          style={{ 
            width: deg === 0 ? '100px' : '60px',
            transform: `translateY(${(pitch - deg) * 3}px)`,
            opacity: Math.max(0, 1 - Math.abs(pitch - deg) / 20)
          }}
        >
          {deg !== 0 && (
            <span className="absolute -left-6 text-[8px] text-white/60 font-mono">{deg}</span>
          )}
        </div>
      ))}
    </div>
  );
};

export default function FlyView({ mapLogic }) {
  const { isArmed, activeMode, setArmed, setFlightMode, isConnected, connectionPhase } = useDroneStateStore();
  const telemetry = useTelemetryStore();

  const handleArmToggle = async () => {
    if (isArmed) {
      const res = await disarmDrone();
      if (res.success) setArmed(false);
    } else {
      const res = await armDrone();
      if (res.success) setArmed(true);
    }
  };

  const handleModeChange = async (targetMode) => {
    const { setFlightMode, setChangingMode } = useDroneStateStore.getState();
    
    // Set lock
    setChangingMode(true);
    setFlightMode(targetMode); // UI update immediately
    
    const res = await setMode(targetMode);
    
    // Release lock after a short delay to allow vehicle state to propagate
    setTimeout(() => {
      setChangingMode(false);
    }, 3000);
    
    if (!res.success) {
      alert(`Gagal ganti mode: ${res.error}`);
    }
  };

  const handleReboot = async () => {
    await rebootFCU();
  };

  const availableModes = ['QHOVER', 'QSTABILIZE', 'FBWA', 'AUTO', 'QLAND', 'RTL'];

  return (
    <div className="flex-1 flex flex-col min-h-0 w-full overflow-hidden text-slate-900 relative">
      
      {/* CONNECTION PROGRESS MODAL */}
      {connectionPhase !== 'DISCONNECTED' && !isConnected && (
        <div className="absolute inset-0 z-[100] bg-black/80 flex items-center justify-center backdrop-blur-sm text-center px-4">
          <div className="bg-slate-900 border-2 border-emerald-500/50 p-8 rounded-sm shadow-[0_0_50px_rgba(16,185,129,0.2)] flex flex-col items-center gap-6 min-w-[320px]">
            <div className="relative">
              <div className="w-16 h-16 border-4 border-emerald-500/20 border-t-emerald-500 rounded-full animate-spin"></div>
            </div>
            <div className="flex flex-col items-center gap-2">
              <h2 className="text-emerald-400 font-bold tracking-widest uppercase text-sm">Link Establishment</h2>
              <p className="font-mono text-xs text-white animate-pulse">
                {connectionPhase === 'CONNECTING' ? '> Connecting...' : '> Syncing Data...'}
              </p>
            </div>
          </div>
        </div>
      )}

      {/* TOP AREA: MAIN GCS PANELS */}
      <div className="flex-1 flex flex-row min-h-0 overflow-hidden">
        {/* LEFT SIDEBAR */}
        <aside className="w-[260px] bg-white border-r border-slate-300 flex flex-col p-3 gap-4 overflow-y-auto shrink-0">
          
          {/* HUD */}
          <div className="h-40 w-full rounded-sm relative overflow-hidden border-2 border-slate-800 shadow-2xl flex items-center justify-center bg-[#5c3c1e]">
            <div 
              className="absolute inset-0 bg-gradient-to-b from-sky-400 to-sky-600 transition-transform duration-75 ease-out"
              style={{ 
                transform: `rotate(${-telemetry.roll}deg) translateY(${telemetry.pitch * 3}px) scale(2)`,
                height: '200%', top: '-50%'
              }}
            />
            <div className="absolute inset-0 z-10" style={{ transform: `rotate(${-telemetry.roll}deg)` }}>
              <PitchLadder pitch={telemetry.pitch} />
            </div>
            <div className="absolute inset-0 flex items-center justify-center z-20 pointer-events-none">
              <div className="w-16 h-0.5 bg-amber-400 shadow-[0_0_5px_rgba(251,191,36,0.8)]" />
              <div className="w-4 h-4 border-2 border-amber-400 absolute rounded-full shadow-[0_0_5px_rgba(251,191,36,0.8)]" />
            </div>
            <div className="absolute top-1 left-1 flex flex-col gap-0.5 z-30">
              <span className={`text-[9px] font-bold px-1 rounded-sm ${isArmed ? 'bg-red-600 text-white' : 'bg-slate-700 text-slate-300'}`}>
                {isArmed ? 'ARMED' : 'DISARMED'}
              </span>
              <span className="text-[9px] font-bold px-1 bg-emerald-600 text-white rounded-sm">{activeMode}</span>
            </div>
            <div className="absolute bottom-1 right-1 font-mono text-white text-[9px] drop-shadow-md">
              R: {telemetry.roll.toFixed(1)}° P: {telemetry.pitch.toFixed(1)}°
            </div>
          </div>

          {/* ARM & REBOOT */}
          <div className="flex flex-col gap-2 w-full">
            <div className="flex flex-row gap-2 h-10">
              <button onClick={handleArmToggle} className={`flex-1 border-2 font-bold text-xs rounded-sm ${isArmed ? 'bg-red-600 text-white border-red-600' : 'text-red-600 border-red-600 hover:bg-red-50'}`}>
                {isArmed ? "DISARM" : "ARM"}
              </button>
              <button onClick={handleReboot} className="w-16 bg-amber-500 text-white font-bold text-[10px] rounded-sm">REBOOT</button>
            </div>
          </div>

          {/* MODES */}
          <div>
            <h3 className="text-[10px] text-slate-500 font-bold mb-1 uppercase tracking-tighter">Flight Modes</h3>
            <div className="grid grid-cols-2 gap-2 w-full">
              {availableModes.map((mode) => (
                <button 
                  key={mode} 
                  onClick={() => handleModeChange(mode)}
                  className={`h-9 font-mono text-[10px] rounded-sm font-bold border ${activeMode === mode ? 'bg-emerald-600 text-white border-emerald-700' : 'bg-slate-50 text-slate-700 border-slate-300'}`}
                >
                  {mode}
                </button>
              ))}
            </div>
          </div>

          {/* MISSION PROGRESS */}
          <div className="mt-auto w-full bg-slate-800 text-slate-200 p-3 rounded-sm border border-slate-700 flex flex-col gap-1 shadow-inner">
            <span className="font-sans text-[10px] font-bold text-slate-400 uppercase">Mission Status</span>
            <span className="font-mono text-[11px] font-bold text-emerald-400">WP Target: 4 / 12</span>
            <span className="font-mono text-[10px] text-white">ETA: 02m 14s</span>
            <span className="font-mono text-[10px] text-slate-300">Dist: {(mapLogic.totalMissionDistance).toFixed(0)} m</span>
          </div>
        </aside>

        {/* CENTER VIEWPORT */}
        <div className="flex-1 flex flex-col bg-slate-800 min-w-0 border-r border-slate-300">
          <div className="flex-1 relative bg-black flex items-center justify-center min-h-0 border-b-4 border-slate-900">
            <span className="font-mono text-sm text-red-500 font-bold animate-pulse">LIVE VIDEO FEED</span>
            <div className="absolute top-4 left-4 text-white font-mono text-[10px] bg-black/50 px-2 py-1">
              {telemetry.lat?.toFixed(5) ?? '---'}, {telemetry.lng?.toFixed(5) ?? '---'}
            </div>
          </div>
          <div className="flex-1 relative bg-slate-200 min-h-0">
            <MapView waypoints={mapLogic.waypoints} />
            <div className="absolute inset-0 z-10 pointer-events-none flex items-center justify-center mix-blend-difference opacity-50">
              <svg className="w-12 h-12 text-white" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1">
                <line x1="12" y1="0" x2="12" y2="24" /><line x1="0" y1="12" x2="24" y2="12" /><circle cx="12" cy="12" r="4" />
              </svg>
            </div>
          </div>
        </div>

        {/* RIGHT SIDEBAR */}
        <aside className="w-[340px] bg-white border-l border-slate-300 flex flex-col p-3 gap-3 overflow-y-auto shrink-0">
          <div className="flex flex-col gap-1 border-b border-slate-200 pb-2">
            <span className="text-[10px] font-bold text-slate-500 uppercase tracking-tighter">Dynamics</span>
            <div className="flex justify-between font-mono text-[11px]"><span>ALT (AGL)</span><span className="text-blue-700 font-bold">{telemetry.altitude.toFixed(1)} m</span></div>
            <div className="flex justify-between font-mono text-[11px]"><span>AIRSPEED</span><span className="text-amber-700 font-bold">{telemetry.airspeed?.toFixed(1) ?? '0.0'} m/s</span></div>
            <div className="flex justify-between font-mono text-[11px]"><span>GND SPEED</span><span>{telemetry.speed.toFixed(1)} m/s</span></div>
          </div>

          <div className="flex flex-col flex-1 min-h-0">
            <span className="text-[10px] font-bold text-slate-500 uppercase tracking-tighter">System Alerts</span>
            <div className="flex-1 w-full bg-slate-900 border border-slate-700 rounded-sm p-2 overflow-y-auto flex flex-col gap-1 mt-1 shadow-inner">
               {telemetry.systemLogs.length === 0 ? (
                 <span className="text-[9px] text-slate-600 italic">No alerts...</span>
               ) : (
                 telemetry.systemLogs.map((log, idx) => (
                   <span key={idx} className={`font-mono text-[9px] leading-tight break-words ${log.color}`}>
                     [{log.time}] {log.text}
                   </span>
                 ))
               )}
            </div>
          </div>
        </aside>
      </div>

      {/* BOTTOM AREA */}
      <footer className="h-40 w-full bg-slate-900 border-t border-slate-700 flex flex-row shrink-0">
         <BottomBar />
      </footer>
    </div>
  )
}
