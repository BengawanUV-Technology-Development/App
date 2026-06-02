import React from 'react';
import MapView from '../components/centerarea/MapView';
import useDroneStateStore from '../store/droneStateStore';
import useTelemetryStore from '../store/telemetryStore';
import { armDrone, disarmDrone, setMode, rebootFCU } from '../services/api';

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
  const { isArmed, activeMode, setArmed, setFlightMode, isConnected } = useDroneStateStore();
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
    const res = await setMode(targetMode);
    if (res.success) setFlightMode(targetMode);
  };

  const handleReboot = async () => {
    await rebootFCU();
  };

  const availableModes = ['QHOVER', 'QSTABILIZE', 'FBWA', 'AUTO', 'QLAND', 'RTL'];

  return (
    <div className="flex-1 flex flex-row min-h-0 w-full overflow-hidden text-slate-900">
      
      {/* LEFT SIDEBAR - COMMAND & CONTROL */}
      <aside className="w-[260px] bg-white border-r border-slate-300 flex flex-col p-3 gap-4 overflow-y-auto shrink-0">
        
        {/* HUD - VISUAL ARTIFICIAL HORIZON */}
        <div className="h-40 w-full rounded-sm relative overflow-hidden border-2 border-slate-800 shadow-2xl flex items-center justify-center bg-[#5c3c1e]">
          {/* Sky Gradient */}
          <div 
            className="absolute inset-0 bg-gradient-to-b from-sky-400 to-sky-600 transition-transform duration-75 ease-out"
            style={{ 
              transform: `rotate(${-telemetry.roll}deg) translateY(${telemetry.pitch * 3}px) scale(2)`,
              height: '200%',
              top: '-50%'
            }}
          />
          
          {/* Pitch Ladder (Instrument Overlay) */}
          <div 
            className="absolute inset-0 z-10 transition-transform duration-75 ease-out"
            style={{ transform: `rotate(${-telemetry.roll}deg)` }}
          >
            <PitchLadder pitch={telemetry.pitch} />
          </div>

          {/* Fixed Center Mask / Aircraft Symbol */}
          <div className="absolute inset-0 flex items-center justify-center z-20 pointer-events-none">
             {/* Center Wings */}
             <div className="w-16 h-0.5 bg-amber-400 shadow-[0_0_5px_rgba(251,191,36,0.8)]" />
             <div className="w-4 h-4 border-2 border-amber-400 absolute rounded-full shadow-[0_0_5px_rgba(251,191,36,0.8)]" />
             {/* Notch top */}
             <div className="absolute top-[40%] w-0.5 h-2 bg-amber-400" />
          </div>

          {/* HUD STATUS OVERLAYS */}
          <div className="absolute top-1 left-1 flex flex-col gap-0.5 z-30">
            <span className={`text-[9px] font-bold px-1 rounded-sm shadow-sm ${isArmed ? 'bg-red-600 text-white' : 'bg-slate-700 text-slate-300'}`}>
              {isArmed ? 'ARMED' : 'DISARMED'}
            </span>
            <span className="text-[9px] font-bold px-1 bg-emerald-600 text-white rounded-sm shadow-sm">
              {activeMode}
            </span>
          </div>

          <div className="absolute bottom-1 right-1 flex flex-col items-end z-30 font-mono text-white text-[9px] drop-shadow-md">
            <span>ROLL: {telemetry.roll.toFixed(1)}°</span>
            <span>PITCH: {telemetry.pitch.toFixed(1)}°</span>
          </div>
        </div>

        {/* ARM & REBOOT WIRING */}
        <div className="flex flex-col gap-2 w-full">
          <div className="flex flex-row gap-2 h-10">
            <button 
              onClick={handleArmToggle}
              className={`flex-1 border-2 font-bold text-xs rounded-sm cursor-pointer transition-all active:scale-95 flex items-center justify-center ${
                isArmed 
                  ? 'border-red-600 text-white bg-red-600 hover:bg-red-700 shadow-inner' 
                  : 'border-red-600 text-red-600 bg-red-50 hover:bg-red-100'
              }`}
            >
              {isArmed ? ">> DISARM <<" : ">> ARM >>"}
            </button>
            <button 
              onClick={handleReboot}
              className="w-16 bg-amber-500 hover:bg-amber-600 text-white flex items-center justify-center font-bold text-[10px] rounded-sm cursor-pointer transition-all active:scale-95"
            >
              REBOOT
            </button>
          </div>
          {!isConnected && (
             <div className="text-[9px] text-red-600 font-bold animate-pulse text-center">
               ⚠️ VEHICLE DISCONNECTED - CHECK PORT
             </div>
          )}
        </div>

        {/* FLIGHT MODES WIRING */}
        <div>
          <h3 className="text-[10px] text-slate-500 font-bold mb-1 tracking-wider">FLIGHT MODES</h3>
          <div className="grid grid-cols-2 gap-2 w-full">
            {availableModes.map((mode) => (
              <button 
                key={mode}
                onClick={() => handleModeChange(mode)}
                className={`h-9 font-mono text-[10px] rounded-sm font-bold cursor-pointer flex items-center justify-center transition-all border ${
                  activeMode === mode 
                    ? 'bg-emerald-600 text-white border-emerald-700 shadow-lg' 
                    : 'bg-slate-50 text-slate-700 border-slate-300 hover:bg-slate-200'
                }`}
              >
                {mode}
              </button>
            ))}
          </div>
        </div>

        {/* MISSION PROGRESS */}
        <div className="mt-auto w-full bg-slate-800 text-slate-200 p-3 rounded-sm border border-slate-700 flex flex-col gap-1 shadow-inner">
          <span className="font-sans text-[10px] font-bold text-slate-400">MISSION PROGRESS</span>
          <span className="font-mono text-[11px] font-bold text-emerald-400">TARGET WP: 4 / 12</span>
          <span className="font-mono text-[10px] text-white">ETA: 02m 14s</span>
          <span className="font-mono text-[10px] text-slate-300">
            DIST: {(mapLogic.totalMissionDistance).toFixed(0)} m
          </span>
        </div>
      </aside>

      {/* CENTER VIEWPORT - MAP & VIDEO */}
      <div className="flex-1 flex flex-col bg-slate-800 min-w-0 border-r border-slate-300">
        {/* TOP HALF: LIVE VIDEO STREAM */}
        <div className="flex-1 relative bg-black flex items-center justify-center min-h-0 border-b-4 border-slate-900 overflow-hidden">
          <span className="font-mono text-sm text-red-500 font-bold animate-pulse">LIVE VIDEO FEED (LANDSCAPE)</span>
          <div className="absolute top-4 left-4 text-white font-mono text-[10px] drop-shadow-md bg-black/50 px-2 py-1">
            CAM 1 | 1080p 60fps | LAT: {telemetry.lat?.toFixed(5) ?? '---'} LON: {telemetry.lng?.toFixed(5) ?? '---'}
          </div>
        </div>

        {/* BOTTOM HALF: INJECTED LEAFLET MAP */}
        <div className="flex-1 relative bg-slate-200 flex items-center justify-center min-h-0">
          <MapView waypoints={mapLogic.waypoints} />
          {/* Added a subtle crosshair overlay on top of the Leaflet map to maintain original aesthetic */}
          <div className="absolute inset-0 z-10 pointer-events-none flex items-center justify-center mix-blend-difference opacity-50">
            <svg className="w-12 h-12 text-white" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1">
              <line x1="12" y1="0" x2="12" y2="24" />
              <line x1="0" y1="12" x2="24" y2="12" />
              <circle cx="12" cy="12" r="4" />
            </svg>
          </div>
        </div>
      </div>

      {/* RIGHT SIDEBAR - TELEMETRY & LOGS */}
      <aside className="w-[340px] bg-white border-l border-slate-300 flex flex-col p-3 gap-3 overflow-y-auto shrink-0">
        
        {/* NODE 1: FLUID DYNAMICS */}
        <div className="flex flex-col gap-1 border-b border-slate-200 pb-2">
          <span className="text-[10px] font-bold text-slate-500 tracking-wider">FLUID DYNAMICS</span>
          <div className="flex justify-between font-mono text-[11px]"><span>ALT (AGL)</span><span className="text-blue-700 font-bold">{telemetry.altitude.toFixed(1)} m</span></div>
          <div className="flex justify-between font-mono text-[11px]"><span>AIRSPEED</span><span className="text-amber-700 font-bold">{telemetry.airspeed?.toFixed(1) ?? '0.0'} m/s</span></div>
          <div className="flex justify-between font-mono text-[11px]"><span>GND SPEED</span><span>{telemetry.speed.toFixed(1)} m/s</span></div>
          <div className="flex justify-between font-mono text-[11px]"><span>V SPEED</span><span className={telemetry.vSpeed > 0 ? 'text-emerald-600' : 'text-red-600'}>{telemetry.vSpeed.toFixed(1)} m/s</span></div>
        </div>

        {/* NODE 2: EKF VARIANCE INNOVATION */}
        <div>
          <span className="text-[10px] font-bold text-slate-500 tracking-wider mt-1">EKF STATUS</span>
          <div className="w-full h-32 bg-[#2a2a2a] border border-slate-700 rounded-sm flex flex-row gap-2 p-2 relative select-none mt-1">
            <span className="absolute top-1 left-1/2 -translate-x-1/2 text-white font-bold text-xs">EKF Status</span>
            <div className="absolute top-[30%] left-2 right-2 border-t border-red-500 z-10"><span className="text-[8px] text-slate-300 absolute -top-3 left-0">0.8</span></div>
            <div className="absolute top-[60%] left-2 right-2 border-t border-red-500 z-10"><span className="text-[8px] text-slate-300 absolute -top-3 left-0">0.5</span></div>
            <div className="flex flex-row gap-2 w-full h-full pt-4 items-end justify-around z-0">
              {[
                { label: 'Velocity', h: '20%' }, { label: 'Position (Horiz)', h: '35%' },
                { label: 'Position (Vert)', h: '15%' }, { label: 'Compass', h: '45%' }, { label: 'Terrain', h: '10%' }
              ].map(bar => (
                <div key={bar.label} className="flex flex-col items-center gap-1 w-8 h-full justify-end">
                  <div className="w-full h-[80%] bg-gradient-to-b from-slate-400 to-slate-600 relative flex items-end">
                    <div className="w-full bg-[#a4d34f]" style={{ height: bar.h }} />
                  </div>
                  <span className="text-[8px] text-slate-300 leading-tight text-center">{bar.label}</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* NODE 3: VIBRATION MONITOR */}
        <div>
          <span className="text-[10px] font-bold text-slate-500 tracking-wider mt-1">VIBRATION STATUS</span>
          <div className="w-full h-32 bg-[#2a2a2a] border border-slate-700 rounded-sm flex flex-row p-2 relative select-none mt-1">
            <div className="absolute top-[30%] left-2 w-[55%] border-t border-red-500 z-10" />
            <div className="absolute top-[60%] left-2 w-[55%] border-t border-red-500 z-10" />
            <div className="flex flex-row gap-3 w-[60%] h-full pt-4 items-end justify-center z-0">
               {[ { label: 'X', h: '40%' }, { label: 'Y', h: '30%' }, { label: 'Z', h: '50%' }].map(bar => (
                  <div key={bar.label} className="flex flex-col items-center gap-1">
                    <div className="w-8 h-[80%] bg-gradient-to-b from-slate-400 to-slate-600 flex items-end">
                      <div className="w-full bg-[#a4d34f]" style={{ height: bar.h }} />
                    </div>
                    <span className="text-[9px] text-white">{bar.label}</span>
                  </div>
               ))}
            </div>
            <div className="flex flex-col w-[40%] h-full pl-2 justify-center gap-1">
              <span className="text-white font-bold text-xs text-center">Clipping</span>
              <div className="flex justify-between text-[9px] text-slate-300 font-mono"><span>Primary</span><span>0</span></div>
              <div className="flex justify-between text-[9px] text-slate-300 font-mono"><span>Secondary</span><span>0</span></div>
              <div className="flex justify-between text-[9px] text-slate-300 font-mono"><span>Tertiary</span><span>0</span></div>
            </div>
          </div>
        </div>

        {/* NODE 4: SYSTEM ALERTS LOG */}
        <div className="flex flex-col flex-1">
          <span className="text-[10px] font-bold text-slate-500 tracking-wider mt-1">SYSTEM ALERTS LOG</span>
          <div className="flex-1 w-full bg-slate-900 border border-slate-700 rounded-sm p-2 overflow-y-auto flex flex-col gap-0.5 shadow-inner mt-1">
            <span className="font-mono text-[10px] leading-tight break-all text-slate-400">[14:02:40] Pre-Arm: GPS Lock acquired</span>
            <span className="font-mono text-[10px] leading-tight break-all text-amber-400">[14:02:44] EKF3 lane switch active</span>
            <span className="font-mono text-[10px] leading-tight break-all text-emerald-400">[14:02:45] Armed: Executing takeoff</span>
            <span className="font-mono text-[10px] leading-tight break-all text-white">[14:03:10] Reached target altitude</span>
          </div>
        </div>
      </aside>
    </div>
  )
}