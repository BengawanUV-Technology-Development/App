// src/components/centerarea/MapOverview.jsx
import React from 'react';
import { MapContainer, TileLayer, Polyline, CircleMarker, Tooltip, useMapEvents } from 'react-leaflet';
import 'leaflet/dist/leaflet.css';
import styles from './CenterArea.module.css';

// Komponen helper untuk mendeteksi klik pada peta
const MapInteraction = ({ onMapClick }) => {
  useMapEvents({
    click: (e) => {
      onMapClick(e.latlng.lat, e.latlng.lng);
    },
  });
  return null; // Komponen ini tidak me-render HTML apa pun
};

const MapView = ({ waypoints, onMapClick }) => {
  const defaultCenter = [-7.55611, 110.83167];

  // Ekstrak koordinat untuk garis (Polyline)
  const pathCoordinates = waypoints.map(wp => [wp.lat, wp.lng]);

  return (
    <div className={styles.mapLayer}>
      <MapContainer 
        center={defaultCenter} 
        zoom={14} 
        style={{ height: '100%', width: '100%' }}
        zoomControl={false}
      >
        <TileLayer
          url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
          attribution='&copy; CARTO'
        />
        
        {/* Pasang event listener klik */}
        <MapInteraction onMapClick={onMapClick} />

        {/* Gambar Garis Rute */}
        {waypoints.length > 1 && (
          <Polyline positions={pathCoordinates} color="#00E5FF" weight={2} dashArray="5, 5" />
        )}

        {/* Gambar Titik Waypoint */}
        {waypoints.map((wp, index) => (
          <CircleMarker 
            key={wp.id} 
            center={[wp.lat, wp.lng]} 
            radius={6}
            color={index === 0 ? "#76FF03" : "#00E5FF"} // Hijau untuk titik pertama (HOME), Cyan untuk sisanya
            fillOpacity={0.8}
          >
            <Tooltip direction="top" offset={[0, -10]} opacity={1} permanent>
              <span className="telemetry-font">{index === 0 ? 'HOME' : `WP${index}`}</span>
            </Tooltip>
          </CircleMarker>
        ))}
      </MapContainer>
    </div>
  );
};

export default MapView;