import React, { useEffect } from 'react';
import { MapContainer, TileLayer, Polyline, CircleMarker, Tooltip, useMapEvents, useMap } from 'react-leaflet';
import 'leaflet/dist/leaflet.css';

// 1. The Fix: This forces Leaflet to recalculate its size after the Tailwind layout renders
const MapResizer = () => {
  const map = useMap();
  useEffect(() => {
    const timer = setTimeout(() => {
      map.invalidateSize();
    }, 100);
    return () => clearTimeout(timer);
  }, [map]);
  return null;
};

const MapInteraction = ({ onMapClick }) => {
  useMapEvents({
    click: (e) => {
      onMapClick?.(e.latlng.lat, e.latlng.lng);
    },
  });
  return null;
};

const MapView = ({ waypoints = [], onMapClick }) => {
  const defaultCenter = [-7.55611, 110.83167];
  const pathCoordinates = waypoints.map(wp => [wp.lat, wp.lng]);

  return (
    // Explicit sizing context for Leaflet
    <div className="absolute inset-0 z-0 bg-slate-900">
      <MapContainer 
        center={defaultCenter} 
        zoom={14} 
        style={{ height: '100%', width: '100%' }}
        zoomControl={false}
      >
        <MapResizer /> {/* Injected the fix here */}
        <TileLayer
          url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
          attribution='&copy; CARTO'
        />
        
        <MapInteraction onMapClick={onMapClick} />

        {waypoints.length > 1 && (
          <Polyline positions={pathCoordinates} color="#00E5FF" weight={2} dashArray="5, 5" />
        )}

        {waypoints.map((wp, index) => (
          <CircleMarker 
            key={wp.id} 
            center={[wp.lat, wp.lng]} 
            radius={6}
            color={index === 0 ? "#76FF03" : "#00E5FF"} 
            fillOpacity={0.8}
          >
            <Tooltip direction="top" offset={[0, -10]} opacity={1} permanent>
              <span className="font-mono text-xs text-slate-800">{index === 0 ? 'HOME' : `WP${index}`}</span>
            </Tooltip>
          </CircleMarker>
        ))}
      </MapContainer>
    </div>
  );
};

export default MapView;