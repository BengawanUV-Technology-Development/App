import { useEffect, useRef } from "react";
import maplibregl from "maplibre-gl";
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";

const DEFAULT_CENTER = [110.8656314, -7.5532394];
const MAX_TRACK_POINTS = 1000;
const MODEL_SIZE_METERS = 12;
const MODEL_HEADING_OFFSET_DEG = 0;
const TILE_URL = import.meta.env.VITE_MAP_TILE_URL || "https://a.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png";
const ACCENT_NAME_PATTERN = /(accent|nose|tip|tail|prop|motor|stripe|logo)/i;

const MAP_STYLE = {
  version: 8,
  sources: {
    "dark-basemap": {
      type: "raster",
      tiles: [TILE_URL],
      tileSize: 256,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/attributions">CARTO</a>',
    },
  },
  layers: [{ id: "dark-basemap", type: "raster", source: "dark-basemap" }],
};

function hasValidPosition(lat, lng) {
  return Number.isFinite(Number(lat)) && Number.isFinite(Number(lng)) && !(Number(lat) === 0 && Number(lng) === 0);
}

function toRadians(value) {
  return THREE.MathUtils.degToRad(Number(value || 0));
}

function createAircraftLayer(stateRef) {
  let map;
  let renderer;
  let loadedModel;
  const camera = new THREE.Camera();
  const scene = new THREE.Scene();
  const aircraft = new THREE.Group();

  scene.add(new THREE.HemisphereLight(0xffffff, 0x0f172a, 2.8));
  const directional = new THREE.DirectionalLight(0xffffff, 3.2);
  directional.position.set(0, -10, 20);
  scene.add(directional);
  scene.add(aircraft);

  return {
    id: "aircraft-3d",
    type: "custom",
    renderingMode: "3d",

    onAdd(mapInstance, gl) {
      map = mapInstance;
      renderer = new THREE.WebGLRenderer({
        canvas: map.getCanvas(),
        context: gl,
        antialias: true,
      });
      renderer.autoClear = false;
      renderer.outputColorSpace = THREE.SRGBColorSpace;

      new GLTFLoader().load(
        "/img/wahana.glb",
        (gltf) => {
          loadedModel = gltf.scene;
          const box = new THREE.Box3().setFromObject(loadedModel);
          const center = box.getCenter(new THREE.Vector3());
          const size = box.getSize(new THREE.Vector3());
          const maxAxis = Math.max(size.x, size.y, size.z) || 1;

          loadedModel.position.copy(center).multiplyScalar(-1);
          loadedModel.scale.setScalar(MODEL_SIZE_METERS / maxAxis);
          // glTF is Y-up while the map's world coordinates are Z-up.
          loadedModel.rotation.x = Math.PI / 2;
          loadedModel.traverse((node) => {
            if (!node.isMesh) return;
            const sourceMaterials = Array.isArray(node.material) ? node.material : [node.material];
            const materials = sourceMaterials.map((sourceMaterial) => {
              const material = sourceMaterial.clone();
              const identity = `${node.name} ${material.name}`;
              material.color?.set(ACCENT_NAME_PATTERN.test(identity) ? "#ef4444" : "#e2e8f0");
              material.roughness = Math.max(Number(material.roughness ?? 0.6), 0.35);
              return material;
            });
            node.material = Array.isArray(node.material) ? materials : materials[0];
          });
          aircraft.add(loadedModel);
          map.triggerRepaint();
        },
        undefined,
        (error) => console.warn("[tactical-map] failed to load aircraft GLB", error),
      );
    },

    render(_gl, args) {
      const state = stateRef.current;
      if (!renderer || !hasValidPosition(state.lat, state.lng)) return;

      const coordinate = maplibregl.MercatorCoordinate.fromLngLat(
        [Number(state.lng), Number(state.lat)],
        Math.max(0, Number(state.alt || 0)),
      );
      const scale = coordinate.meterInMercatorCoordinateUnits();
      const worldTransform = new THREE.Matrix4()
        .makeTranslation(coordinate.x, coordinate.y, coordinate.z)
        .scale(new THREE.Vector3(scale, -scale, scale));

      aircraft.rotation.order = "ZYX";
      aircraft.rotation.x = toRadians(state.pitchDeg);
      aircraft.rotation.y = toRadians(-state.rollDeg);
      aircraft.rotation.z = toRadians(-(state.headingDeg + MODEL_HEADING_OFFSET_DEG));

      camera.projectionMatrix = new THREE.Matrix4()
        .fromArray(args.defaultProjectionData.mainMatrix)
        .multiply(worldTransform);

      renderer.resetState();
      renderer.render(scene, camera);
    },

    onRemove() {
      if (loadedModel) {
        loadedModel.traverse((node) => {
          node.geometry?.dispose();
          const materials = Array.isArray(node.material) ? node.material : [node.material];
          materials.filter(Boolean).forEach((material) => material.dispose());
        });
      }
      renderer?.dispose();
    },
  };
}

function OperationalMap({ lat, lng, alt = 0, headingDeg = 0, rollDeg = 0, pitchDeg = 0 }) {
  const mountRef = useRef(null);
  const mapRef = useRef(null);
  const trackRef = useRef([]);
  const stateRef = useRef({ lat, lng, alt, headingDeg, rollDeg, pitchDeg });

  useEffect(() => {
    stateRef.current = { lat, lng, alt, headingDeg, rollDeg, pitchDeg };
    mapRef.current?.triggerRepaint();
  }, [alt, headingDeg, lat, lng, pitchDeg, rollDeg]);

  useEffect(() => {
    if (!mountRef.current || mapRef.current) return undefined;

    const map = new maplibregl.Map({
      container: mountRef.current,
      style: MAP_STYLE,
      center: DEFAULT_CENTER,
      zoom: 17,
      pitch: 60,
      bearing: 0,
      attributionControl: true,
      antialias: true,
      maxPitch: 75,
    });

    map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), "top-left");
    map.on("load", () => {
      map.addSource("aircraft-track", {
        type: "geojson",
        data: { type: "Feature", properties: {}, geometry: { type: "LineString", coordinates: [] } },
      });
      map.addLayer({
        id: "aircraft-track",
        type: "line",
        source: "aircraft-track",
        paint: {
          "line-color": "#38bdf8",
          "line-width": 4,
          "line-opacity": 0.9,
        },
      });
      map.addLayer(createAircraftLayer(stateRef));

      const state = stateRef.current;
      if (hasValidPosition(state.lat, state.lng)) {
        const coordinate = [Number(state.lng), Number(state.lat)];
        trackRef.current = [coordinate];
        map.getSource("aircraft-track")?.setData({
          type: "Feature",
          properties: {},
          geometry: { type: "LineString", coordinates: trackRef.current },
        });
        map.jumpTo({
          center: coordinate,
          bearing: Number(state.headingDeg || 0),
          pitch: 60,
        });
      }
    });

    mapRef.current = map;
    return () => {
      map.remove();
      mapRef.current = null;
      trackRef.current = [];
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !hasValidPosition(lat, lng)) return;

    const coordinate = [Number(lng), Number(lat)];
    const previous = trackRef.current.at(-1);
    const moved = !previous || Math.abs(previous[0] - coordinate[0]) + Math.abs(previous[1] - coordinate[1]) > 0.000001;
    if (moved) {
      trackRef.current = [...trackRef.current, coordinate].slice(-MAX_TRACK_POINTS);
      const source = map.getSource("aircraft-track");
      source?.setData({
        type: "Feature",
        properties: {},
        geometry: { type: "LineString", coordinates: trackRef.current },
      });
    }

    map.easeTo({
      center: coordinate,
      bearing: Number(headingDeg || 0),
      pitch: 60,
      duration: 450,
      essential: true,
    });
  }, [headingDeg, lat, lng]);

  return <div className="operational-map" ref={mountRef} />;
}

export default OperationalMap;
