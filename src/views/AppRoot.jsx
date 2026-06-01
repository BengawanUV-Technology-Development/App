import React, { useState } from "react";
import GlobalHeader from "./GlobalHeader";
import FlyView from "./FlyView"; 
import PlanView from "./PlanView";
import { useMapLogic } from "../hooks/useMapLogic"; // IMPORT THE HOOK

export default function AppRoot() {
  const [globalTab, setGlobalTab] = useState("fly");
  const [localTab, setLocalTab] = useState("mission");
  
  // INJECT HOOK HERE so waypoints survive tab switching
  const mapLogic = useMapLogic();

  return (
    <div className="h-screen w-screen overflow-hidden bg-slate-100 flex flex-col font-sans select-none relative">
      <GlobalHeader 
        globalTab={globalTab} 
        onGlobalTabChange={setGlobalTab} 
        localTab={localTab} 
        onLocalTabChange={setLocalTab} 
      />
      <main className="flex-1 w-full h-full overflow-hidden flex flex-col relative">
        {globalTab === "fly" ? (
          <FlyView mapLogic={mapLogic} /> 
        ) : (
          <PlanView activeMenu={localTab} mapLogic={mapLogic} />
        )}
      </main>
    </div>
  );
}