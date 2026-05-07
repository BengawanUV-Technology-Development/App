// src/hooks/useMapLogic.js
import { useState, useCallback } from 'react';
import { calculateDistance } from '../utils/mapHelpers';

export const useMapLogic = () => {
  const [waypoints, setWaypoints] = useState([]);

  // Fungsi yang akan dipasang ke event click peta Leaflet
  const handleMapClick = useCallback((lat, lng) => {
    setWaypoints((prev) => [
      ...prev,
      { 
        id: Date.now(), // ID unik
        lat, 
        lng, 
        alt: 50 // Ketinggian default 50m
      }
    ]);
  }, []);

  const removeWaypoint = useCallback((index) => {
    setWaypoints((prev) => prev.filter((_, i) => i !== index));
  }, []);

  const updateWaypointAlt = useCallback((index, newAlt) => {
    setWaypoints((prev) => {
      const updated = [...prev];
      updated[index].alt = newAlt;
      return updated;
    });
  }, []);

  const clearMission = useCallback(() => {
    setWaypoints([]);
  }, []);

  // Menghitung total jarak dari semua waypoint
  const totalMissionDistance = waypoints.reduce((total, wp, index) => {
    if (index === 0) return 0;
    const prevWp = waypoints[index - 1];
    return total + calculateDistance(prevWp.lat, prevWp.lng, wp.lat, wp.lng);
  }, 0);

  return {
    waypoints,
    handleMapClick,
    removeWaypoint,
    updateWaypointAlt,
    clearMission,
    totalMissionDistance
  };
};