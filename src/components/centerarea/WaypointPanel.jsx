// src/components/centerarea/WaypointPanel.jsx
import React from 'react';
import styles from './CenterArea.module.css';
import { formatGPS } from '../../utils/formatters'; // Import formatter
import { uploadWaypoints } from '../../services/api';

const WaypointPanel = ({ isOpen, onClose, mapLogic }) => {
  if (!isOpen) return null;

  const { waypoints, removeWaypoint, updateWaypointAlt, clearMission, totalMissionDistance } = mapLogic;

  const handleUpload = async () => {
    if (waypoints.length === 0) return alert('Misi kosong! Klik di peta untuk menambah waypoint.');
    const res = await uploadWaypoints(waypoints);
    if (res.success) alert('Misi berhasil diunggah ke FCU!');
  };

  return (
    <div className={styles.waypointPanel}>
      <div className={styles.panelHeader}>
        <h4>Waypoint Manager</h4>
        <button className={styles.closeButton} onClick={onClose}>X</button>
      </div>

      {/* Daftar Waypoint Dinamis */}
      <div style={{ maxHeight: '200px', overflowY: 'auto', marginBottom: '12px' }}>
        {waypoints.length === 0 ? (
          <p style={{ fontSize: '12px', color: '#888', fontStyle: 'italic' }}>
            Klik pada peta untuk menambahkan waypoint...
          </p>
        ) : (
          waypoints.map((wp, index) => (
            <div key={wp.id} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px', fontSize: '11px', backgroundColor: '#1a1a1a', padding: '6px', borderRadius: '4px' }}>
              
              <div className="telemetry-font">
                <span style={{ color: index === 0 ? '#76FF03' : '#00E5FF', fontWeight: 'bold', marginRight: '8px' }}>
                  {index === 0 ? 'H' : index}
                </span>
                {formatGPS(wp.lat)}, {formatGPS(wp.lng)}
              </div>

              <div style={{ display: 'flex', gap: '4px', alignItems: 'center' }}>
                {/* Input Ketinggian */}
                <input 
                  type="number" 
                  value={wp.alt}
                  onChange={(e) => updateWaypointAlt(index, Number(e.target.value))}
                  className="telemetry-font"
                  style={{ width: '40px', background: '#000', border: '1px solid #333', color: '#fff', padding: '2px 4px' }}
                />
                <span style={{ color: '#888' }}>m</span>
                
                {/* Tombol Hapus */}
                <button 
                  onClick={() => removeWaypoint(index)}
                  style={{ background: 'none', border: 'none', color: '#FF1744', cursor: 'pointer', marginLeft: '4px' }}
                >
                  ✖
                </button>
              </div>

            </div>
          ))
        )}
      </div>

      {/* Ringkasan Jarak */}
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '12px', color: '#aaa', borderTop: '1px solid #333', paddingTop: '8px', marginBottom: '8px' }}>
        <span>Total Distance:</span>
        <span className="telemetry-font">{(totalMissionDistance / 1000).toFixed(2)} km</span>
      </div>

      <div style={{ display: 'flex', gap: '8px' }}>
        <button 
          style={{ flex: 1, padding: '8px', backgroundColor: '#222', color: '#fff', border: '1px solid #444', cursor: 'pointer' }}
          onClick={clearMission}
        >
          CLEAR
        </button>
        <button 
          className="telemetry-font" 
          style={{ flex: 2, padding: '8px', backgroundColor: '#004d40', color: '#00E5FF', border: '1px solid #00E5FF', cursor: 'pointer', fontWeight: 'bold' }}
          onClick={handleUpload}
        >
          UPLOAD TO FCU
        </button>
      </div>
    </div>
  );
};

export default WaypointPanel;