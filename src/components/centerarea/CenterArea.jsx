// src/components/centerarea/CenterArea.jsx
import React from 'react';
import useUiStore from '../../store/uiStore';
import { useMapLogic } from '../../hooks/useMapLogic'; // 1. Import Hook
import MapOverview from './MapView';
import HUDOverlay from './HUDOverlay';
import WaypointPanel from './WaypointPanel';
import styles from './CenterArea.module.css';

const CenterArea = () => {
  const isWpPanelOpen = useUiStore((state) => state.isWpPanelOpen);
  const toggleWpPanel = useUiStore((state) => state.toggleWpPanel);
  const setWpPanelOpen = useUiStore((state) => state.setWpPanelOpen);

  // 2. Panggil Hook MapLogic
  const mapLogic = useMapLogic();

  return (
    <div className={styles.container}>
      <button 
        style={{ position: 'absolute', top: '16px', left: '16px', zIndex: 30 }}
        onClick={toggleWpPanel}
      >
        Toggle WP Manager
      </button>

      {/* 3. Oper props ke Peta */}
      <MapOverview 
        waypoints={mapLogic.waypoints} 
        onMapClick={mapLogic.handleMapClick} 
      />
      
      <HUDOverlay />
      
      {/* 4. Oper props ke Panel WP */}
      <WaypointPanel 
        isOpen={isWpPanelOpen} 
        onClose={() => setWpPanelOpen(false)}
        mapLogic={mapLogic} 
      />
    </div>
  );
};

export default CenterArea;