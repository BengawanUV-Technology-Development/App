import React from 'react';
import { setParameter } from '../services/api'; // ADD THIS IMPORT AT THE TOP OF THE FILE IF IT ISNT THERE
import { useState } from 'react'; // ADD THIS IMPORT AT THE TOP
import { Pencil, Ruler, Navigation, Trash2 } from "lucide-react";
import MapView from '../components/centerarea/MapView';

export default function PlanView({ activeMenu, mapLogic }) {
  return (
    <div className="flex-1 w-full h-full overflow-hidden text-slate-900">
      {activeMenu === "mission" ? <MissionView mapLogic={mapLogic} /> : <HardwareView />}
    </div>
  )
}

function MissionView({ mapLogic }) {
  const [isUploading, setIsUploading] = useState(false);

  // The functional wiring for the WRITE button
  const handleWriteMission = async () => {
    if (mapLogic.waypoints.length === 0) return;
    
    setIsUploading(true);
    const res = await uploadWaypoints(mapLogic.waypoints);
    
    if (!res.success) {
      console.error("Mission Upload Failed:", res.error);
      alert(`Upload Failed: ${res.error}`); // Temporary fallback, can be replaced with a toast notification later
    } else {
      console.log("Mission uploaded successfully!");
    }
    
    setIsUploading(false);
  };

  return (
    <div className="flex w-full h-full">
      {/* Map Container */}
      <div className="w-[75%] h-full bg-slate-300 relative flex items-center justify-center border-r border-slate-400">
        
        {/* INJECTED LEAFLET MAP W/ ONCLICK */}
        <MapView waypoints={mapLogic.waypoints} onMapClick={mapLogic.handleMapClick} />
        
        {/* Floating info box */}
        <div className="absolute top-4 left-4 flex gap-4 items-start z-10 pointer-events-none">
          <div className="bg-black/80 text-white p-2 text-xs font-mono rounded-sm shadow-md">
            TOTAL DIST: {(mapLogic.totalMissionDistance / 1000).toFixed(2)} km
          </div>
        </div>

        {/* Floating Map Toolbar */}
        <div className="absolute left-4 top-1/2 -translate-y-1/2 bg-white border border-slate-400 shadow-md flex flex-col rounded-sm overflow-hidden z-10">
          <button className="h-10 w-10 flex items-center justify-center border-b border-slate-200 hover:bg-slate-100 text-slate-700">
            <Pencil className="h-4 w-4" />
          </button>
          <button className="h-10 w-10 flex items-center justify-center border-b border-slate-200 hover:bg-slate-100 text-slate-700">
            <Ruler className="h-4 w-4" />
          </button>
          <button className="h-10 w-10 flex items-center justify-center border-b border-slate-200 hover:bg-slate-100 text-slate-700">
            <Navigation className="h-4 w-4" />
          </button>
          <button onClick={mapLogic.clearMission} className="h-10 w-10 flex items-center justify-center hover:bg-red-50 text-red-600 cursor-pointer transition-colors" title="Clear Mission">
            <Trash2 className="h-4 w-4" />
          </button>
        </div>
      </div>

      {/* Waypoints Container */}
      <div className="w-[25%] h-full bg-slate-50 flex flex-col z-10 shadow-xl">
        <div className="h-10 bg-slate-800 text-white flex justify-between items-center px-3 shrink-0">
          <span className="text-xs font-bold">WAYPOINTS</span>
          
          {/* THE WIRED WRITE BUTTON */}
          <button 
            onClick={handleWriteMission}
            disabled={isUploading || mapLogic.waypoints.length === 0}
            className={`transition-colors px-3 py-1 text-xs font-bold rounded-sm ${
              isUploading || mapLogic.waypoints.length === 0 
                ? 'bg-slate-600 text-slate-400 cursor-not-allowed' 
                : 'bg-blue-600 hover:bg-blue-700 text-white shadow-inner'
            }`}
          >
            {isUploading ? 'UPLOADING...' : '[ WRITE ]'}
          </button>
        </div>

        <div className="flex-1 overflow-y-auto w-full">
          <table className="w-full text-left text-[10px] font-mono">
            <thead className="sticky top-0 bg-slate-200 shadow-sm z-10">
              <tr>
                <th className="p-2">SEQ</th>
                <th className="p-2">CMD</th>
                <th className="p-2">ALT</th>
                <th className="p-2">DEL</th>
              </tr>
            </thead>
            <tbody>
              {mapLogic.waypoints.map((wp, index) => (
                <tr key={wp.id} className="border-b border-slate-200 hover:bg-slate-100 transition-colors">
                  <td className="p-2 font-bold">{index === 0 ? 'H' : index}</td>
                  <td className="p-2">{index === 0 ? 'TAKEOFF' : 'WAYPOINT'}</td>
                  <td className="p-2">
                    <input 
                      type="text" 
                      value={wp.alt} 
                      onChange={(e) => mapLogic.updateWaypointAlt(index, Number(e.target.value))} 
                      className="w-12 border border-slate-300 text-center p-1 rounded-sm bg-white outline-none focus:border-blue-500" 
                    />
                  </td>
                  <td className="p-2">
                    <button onClick={() => mapLogic.removeWaypoint(index)} className="text-red-600 font-bold hover:text-red-800">
                      [X]
                    </button>
                  </td>
                </tr>
              ))}
              {mapLogic.waypoints.length === 0 && (
                <tr><td colSpan="4" className="p-4 text-center text-slate-400 font-sans italic">Click map to add waypoints</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}

function HardwareView() {
  // 1. Initial State (Simulating what might come from the drone)
  const initialParams = {
    Q_ENABLE: "1",
    Q_FRAME_CLASS: "1",
    Q_TRANS_FAIL: "15",
    Q_TRANSITION_MS: "3000",
    ARSPD_FBW_MIN: "12",
    ARSPD_FBW_MAX: "28"
  };

  // 2. React State for dirty tracking
  const [savedParams, setSavedParams] = useState(initialParams);
  const [currentParams, setCurrentParams] = useState(initialParams);
  const [isWriting, setIsWriting] = useState(false);

  // 3. Handle Input Changes
  const handleParamChange = (key, value) => {
    setCurrentParams(prev => ({ ...prev, [key]: value }));
  };

  // 4. The Bulk Write Logic (Option B)
  const handleWriteParams = async () => {
    setIsWriting(true);
    
    // Find only the parameters that differ from the saved state
    const dirtyKeys = Object.keys(currentParams).filter(
      key => currentParams[key] !== savedParams[key]
    );

    for (const key of dirtyKeys) {
      // Loop through and fire the legacy API call for each changed parameter
      console.log(`Writing Param -> ${key}: ${currentParams[key]}`);
      const res = await setParameter(key, currentParams[key]);
      
      if (!res.success) {
        console.error(`Failed to write ${key}`);
        // Optionally handle UI error here
      }
    }

    // Once complete, the current parameters become the new "saved" state
    setSavedParams(currentParams);
    setIsWriting(false);
  };

  // Configuration map to render the table dynamically
  const paramConfig = [
    { id: 'Q_ENABLE', desc: 'Enable QuadPlane mode' },
    { id: 'Q_FRAME_CLASS', desc: '1:Quad, 2:Hexa' },
    { id: 'Q_TRANS_FAIL', desc: 'Transition timeout (s)' },
    { id: 'Q_TRANSITION_MS', desc: 'Blend time (ms)' },
    { id: 'ARSPD_FBW_MIN', desc: 'Minimum airspeed (m/s)' },
    { id: 'ARSPD_FBW_MAX', desc: 'Maximum airspeed (m/s)' },
  ];

  return (
    <div className="flex flex-row w-full h-full p-4 gap-4 bg-slate-100 overflow-hidden">
      
      {/* LEFT HALF: Parameter List */}
      <div className="w-[50%] h-full bg-white border border-slate-300 flex flex-col shadow-sm rounded-sm">
        <div className="h-10 bg-slate-800 text-white flex justify-between items-center px-4 shrink-0">
          <span className="text-xs font-bold">ESSENTIAL PARAMETERS</span>
          <button 
            onClick={handleWriteParams}
            disabled={isWriting}
            className={`px-3 py-1 text-xs font-bold transition-colors ${
              isWriting ? 'bg-slate-500 text-slate-300' : 'bg-emerald-600 hover:bg-emerald-500 text-white shadow-inner'
            }`}
          >
            {isWriting ? 'WRITING...' : '[ WRITE PARAMS ]'}
          </button>
        </div>
        <div className="flex-1 overflow-y-auto">
          <table className="w-full text-left text-[11px] font-mono">
            <tbody>
              {paramConfig.map((param) => {
                // Determine if this specific input is "dirty" (edited but not saved)
                const isDirty = currentParams[param.id] !== savedParams[param.id];
                
                return (
                  <tr key={param.id} className="border-b border-slate-100 hover:bg-slate-50">
                    <td className="p-2 font-semibold text-slate-700">{param.id}</td>
                    <td className="p-2">
                      <input 
                        type="text" 
                        value={currentParams[param.id]} 
                        onChange={(e) => handleParamChange(param.id, e.target.value)}
                        className={`w-20 border px-1 text-center font-bold outline-none transition-colors ${
                          isDirty 
                            ? 'bg-amber-100 border-amber-500 text-amber-900' // Highlight orange if dirty
                            : 'bg-white border-slate-300 text-slate-900 focus:border-blue-500' // Normal state
                        }`} 
                      />
                    </td>
                    <td className="p-2 text-slate-500">{param.desc}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* RIGHT HALF: Calibration Deck */}
      <div className="w-[50%] h-full flex flex-col gap-4 overflow-y-auto pr-2">
        
        {/* Card 1: Compass Calibration */}
        <div className="bg-white border border-slate-300 p-4 rounded-sm flex flex-col gap-2 shrink-0">
          <h3 className="font-bold text-sm text-slate-800">Onboard Mag Calibration</h3>
          <div className="flex gap-2">
            <button className="bg-emerald-600 hover:bg-emerald-700 text-white px-4 py-1 text-xs font-bold rounded-sm transition-colors">[ Start ]</button>
            <button className="bg-slate-300 hover:bg-slate-400 text-slate-700 px-4 py-1 text-xs font-bold rounded-sm transition-colors">[ Accept ]</button>
            <button className="bg-slate-200 hover:bg-slate-300 text-slate-700 px-4 py-1 text-xs font-bold rounded-sm transition-colors">[ Cancel ]</button>
          </div>
          <div className="flex flex-col gap-2 mt-2">
            <div className="flex items-center gap-2">
              <span className="text-xs font-mono w-12 text-slate-700 font-bold">Mag 1</span>
              <div className="flex-1 h-3 bg-slate-200 rounded-sm overflow-hidden"><div className="w-[100%] h-full bg-emerald-500"></div></div>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-xs font-mono w-12 text-slate-700 font-bold">Mag 2</span>
              <div className="flex-1 h-3 bg-slate-200 rounded-sm overflow-hidden"><div className="w-[45%] h-full bg-blue-500"></div></div>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-xs font-mono w-12 text-slate-700 font-bold">Mag 3</span>
              <div className="flex-1 h-3 bg-slate-200 rounded-sm overflow-hidden"><div className="w-[0%] h-full bg-slate-300"></div></div>
            </div>
            <div className="flex items-center gap-2 mt-1">
              <span className="text-xs font-mono w-12 text-slate-700 font-bold">Fitness</span>
              <input type="text" className="w-16 border border-slate-300 px-1 text-center text-xs outline-none focus:border-blue-500 rounded-sm" defaultValue="16" />
              <span className="text-xs text-slate-500 italic">Relax fitness if calibration fails</span>
            </div>
          </div>
        </div>

        {/* Card 2: Motor Test Bench */}
        <div className="bg-slate-800 text-slate-200 border border-slate-700 p-4 rounded-sm flex flex-col gap-4 shrink-0 shadow-inner">
          <h3 className="font-bold text-sm text-white border-b border-slate-600 pb-2">Motor Test</h3>
          <div className="flex gap-4 items-center">
            <label className="text-xs flex items-center gap-2 font-mono">
              Throttle %
              <input type="text" defaultValue="5" className="w-12 text-slate-900 font-bold text-center border border-slate-400 px-1 rounded-sm outline-none" />
            </label>
            <label className="text-xs flex items-center gap-2 font-mono">
              Duration (s)
              <input type="text" defaultValue="2" className="w-12 text-slate-900 font-bold text-center border border-slate-400 px-1 rounded-sm outline-none" />
            </label>
            <span className="text-xs font-mono text-emerald-400 font-bold">Class: Quad</span>
            <span className="text-xs font-mono text-emerald-400 font-bold">Type: X</span>
          </div>
          
          <div className="flex flex-row gap-6 bg-slate-900/50 p-3 rounded-sm border border-slate-700/50">
            <div className="flex flex-col gap-2">
              {['A', 'B', 'C', 'D'].map(motor => (
                <button key={motor} className="bg-[#a4d34f] hover:bg-[#8eb843] text-slate-900 text-[10px] font-bold font-sans px-4 py-1 border border-[#7a9e39] text-center w-36 shadow-sm cursor-pointer select-none rounded-sm transition-colors uppercase">
                  [ Test motor {motor} ]
                </button>
              ))}
              <button className="bg-[#a4d34f] hover:bg-[#8eb843] text-slate-900 text-[10px] font-bold font-sans px-4 py-1 border border-[#7a9e39] text-center w-36 shadow-sm cursor-pointer select-none mt-2 rounded-sm transition-colors uppercase">
                [ Test all motors ]
              </button>
              <button className="bg-[#a4d34f] hover:bg-[#8eb843] text-slate-900 text-[10px] font-bold font-sans px-4 py-1 border border-[#7a9e39] text-center w-36 shadow-sm cursor-pointer select-none rounded-sm transition-colors uppercase">
                [ Test Sequence ]
              </button>
            </div>
            <div className="flex flex-col gap-2 text-[10px] font-mono pt-1 text-slate-300">
              <span className="flex items-center gap-2"><div className="w-2 h-2 rounded-full bg-emerald-500"></div> Motor 1, CW</span>
              <span className="flex items-center gap-2"><div className="w-2 h-2 rounded-full bg-amber-500"></div> Motor 4, CCW</span>
              <span className="flex items-center gap-2"><div className="w-2 h-2 rounded-full bg-amber-500"></div> Motor 2, CCW</span>
              <span className="flex items-center gap-2"><div className="w-2 h-2 rounded-full bg-emerald-500"></div> Motor 3, CW</span>
            </div>
            <div className="flex-1 flex items-center">
              <p className="text-[10px] text-amber-400/80 leading-relaxed font-mono border-l-2 border-amber-500/50 pl-3">
                <span className="font-bold text-amber-400 block mb-1">⚠️ WARNING:</span>
                PLEASE HOLD DOWN YOUR UAV. This tests motor functionality. Motors trigger in clockwise rotation starting front-right.
              </p>
            </div>
          </div>
        </div>

        {/* Card 3: Accelerometer Calibration */}
        <div className="bg-white border border-slate-300 p-4 rounded-sm flex justify-around items-center shrink-0">
          <div className="flex flex-col items-center gap-3">
            <span className="text-xs font-bold text-slate-700">Calibrate 3-Axis Min/Max</span>
            <button className="bg-[#a4d34f] hover:bg-[#8eb843] text-slate-900 font-bold px-6 py-1.5 text-xs border border-[#7a9e39] rounded-sm transition-colors shadow-sm">
              [ Calibrate Accel ]
            </button>
          </div>
          <div className="w-px h-12 bg-slate-200"></div>
          <div className="flex flex-col items-center gap-3">
            <span className="text-xs font-bold text-slate-700">Calibrate 1-Axis Level</span>
            <button className="bg-[#a4d34f] hover:bg-[#8eb843] text-slate-900 font-bold px-6 py-1.5 text-xs border border-[#7a9e39] rounded-sm transition-colors shadow-sm">
              [ Calibrate Level ]
            </button>
          </div>
        </div>

      </div>
    </div>
  )
}