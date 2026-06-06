import { useEffect, useRef } from "react";
import L from "leaflet";
import { API_BASE } from "../../services/api";

const DEFAULT_CENTER = [-7.5532394, 110.8656314];
const MAX_TRACK_POINTS = 1000;
const TILE_URL = import.meta.env.VITE_MAP_TILE_URL || `${API_BASE}/api/v1/map/tiles/{z}/{x}/{y}.png`;

function hasValidPosition(lat, lng) {
  return Number.isFinite(Number(lat)) && Number.isFinite(Number(lng)) && !(Number(lat) === 0 && Number(lng) === 0);
}

function aircraftIcon(headingDeg) {
  return L.divIcon({
    className: "leaflet-aircraft-icon",
    html: `<div class="leaflet-aircraft-arrow" style="transform: rotate(${Number(headingDeg || 0)}deg)"><span></span></div>`,
    iconAnchor: [22, 22],
    iconSize: [44, 44],
  });
}

function OperationalMap({ lat, lng, headingDeg = 0 }) {
  const mountRef = useRef(null);
  const mapRef = useRef(null);
  const markerRef = useRef(null);
  const trackLayerRef = useRef(null);
  const trackRef = useRef([]);
  const hasCenteredRef = useRef(false);

  useEffect(() => {
    if (!mountRef.current || mapRef.current) return undefined;

    const map = L.map(mountRef.current, {
      center: DEFAULT_CENTER,
      zoom: 16,
      zoomControl: true,
      attributionControl: true,
    });

    L.tileLayer(TILE_URL, {
      minZoom: 2,
      maxZoom: 20,
      keepBuffer: 4,
      updateWhenIdle: false,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    }).addTo(map);

    trackLayerRef.current = L.polyline([], {
      color: "#2563eb",
      opacity: 0.9,
      weight: 3,
    }).addTo(map);

    mapRef.current = map;
    const resizeObserver = new ResizeObserver(() => map.invalidateSize({ pan: false }));
    resizeObserver.observe(mountRef.current);

    return () => {
      resizeObserver.disconnect();
      map.remove();
      mapRef.current = null;
      markerRef.current = null;
      trackLayerRef.current = null;
      trackRef.current = [];
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !hasValidPosition(lat, lng)) return;

    const position = L.latLng(Number(lat), Number(lng));
    if (!markerRef.current) {
      markerRef.current = L.marker(position, {
        icon: aircraftIcon(headingDeg),
        keyboard: false,
        zIndexOffset: 1000,
      }).addTo(map);
    } else {
      markerRef.current.setLatLng(position);
      markerRef.current.setIcon(aircraftIcon(headingDeg));
    }

    const previous = trackRef.current.at(-1);
    if (!previous || previous.distanceTo(position) >= 1) {
      trackRef.current = [...trackRef.current, position].slice(-MAX_TRACK_POINTS);
      trackLayerRef.current?.setLatLngs(trackRef.current);
    }

    if (!hasCenteredRef.current) {
      map.setView(position, 17);
      hasCenteredRef.current = true;
    } else if (!map.getBounds().pad(-0.2).contains(position)) {
      map.panTo(position);
    }
  }, [headingDeg, lat, lng]);

  return <div className="operational-map" ref={mountRef} />;
}

export default OperationalMap;
