import { useEffect, useRef, useState } from "react";
import maplibregl from "maplibre-gl";
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { API_BASE, apiGet } from "../../services/api";

const DEFAULT_CENTER = [110.8656314, -7.5532394];
const MAX_TRACK_POINTS = 1000;
// Post-flight detections are reviewed after landing (see
// docs/post-flight-detection-snapshots.md), not live, so polling this
// slowly is intentional -- it doesn't need to feel real-time.
const DETECTIONS_POLL_MS = 15000;
// Live, un-clustered detection dots (see /api/v1/live/detections) are only
// meaningful while a recording is in progress, so this polls much faster
// than the post-flight pins and stops entirely once recording ends.
const LIVE_DETECTIONS_POLL_MS = 1500;
const MODEL_SIZE_METERS = 12;
const MODEL_HEADING_OFFSET_DEG = 180;
const MODEL_BODY_COLOR = "#cffff8";
const MODEL_ACCENT_COLOR = "#00bda5";
const MODEL_EMISSIVE_COLOR = "#00b6b6";
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

function FollowIcon() {
  return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3l7 16-7-4-7 4 7-16z" /></svg>;
}

function FlatMapIcon() {
  return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 6l6-3 6 3 6-3v15l-6 3-6-3-6 3V6zm6-3v15m6-12v15" /></svg>;
}

function ThreeDIcon() {
  return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3l8 4.5v9L12 21l-8-4.5v-9L12 3zm0 0v9m8-4.5l-8 4.5-8-4.5m8 4.5v9" /></svg>;
}

function toRadians(value) {
  return THREE.MathUtils.degToRad(Number(value || 0));
}

function positionedWaypoints(mission) {
  return (mission?.waypoints || []).filter((waypoint) => waypoint.has_position && Number.isFinite(waypoint.lat) && Number.isFinite(waypoint.lng));
}

function missionRouteData(mission) {
  return {
    type: "Feature",
    properties: {},
    geometry: {
      type: "LineString",
      coordinates: positionedWaypoints(mission).map((waypoint) => [waypoint.lng, waypoint.lat]),
    },
  };
}

function missionPointData(mission) {
  return {
    type: "FeatureCollection",
    features: positionedWaypoints(mission).map((waypoint) => ({
      type: "Feature",
      properties: {
        label: String(waypoint.seq ?? waypoint.index ?? "?"),
        command: waypoint.command_name || "WP",
        alt: waypoint.alt_m === null || waypoint.alt_m === undefined ? "-" : `${Number(waypoint.alt_m).toFixed(0)} m`,
      },
      geometry: {
        type: "Point",
        coordinates: [waypoint.lng, waypoint.lat],
      },
    })),
  };
}

function currentMissionPointData(mission) {
  const waypoint = mission?.current_waypoint;
  if (!waypoint?.has_position || !Number.isFinite(waypoint.lat) || !Number.isFinite(waypoint.lng)) {
    return { type: "FeatureCollection", features: [] };
  }
  return {
    type: "FeatureCollection",
    features: [
      {
        type: "Feature",
        properties: {
          label: String(waypoint.seq ?? waypoint.index ?? "?"),
          command: waypoint.command_name || "WP",
          alt: waypoint.alt_m === null || waypoint.alt_m === undefined ? "-" : `${Number(waypoint.alt_m).toFixed(0)} m`,
        },
        geometry: {
          type: "Point",
          coordinates: [waypoint.lng, waypoint.lat],
        },
      },
    ],
  };
}

function detectionPointData(detections) {
  return {
    type: "FeatureCollection",
    features: (detections || [])
      .filter((detection) => detection.coordinate?.status && detection.coordinate.status !== "not_available")
      // Post-flight dedup (see docs/post-flight-detection-snapshots.md):
      // generate_detection_snapshots.py clusters repeat sightings of the
      // same physical target and marks the strongest one representative.
      // is_representative === false means a stronger sighting of the same
      // cluster already has a pin; null/undefined (older rows, or a
      // singleton cluster) still shows, nothing to defer to.
      .filter((detection) => detection.is_representative !== false)
      .map((detection) => ({
        type: "Feature",
        properties: {
          detectionId: detection.detection_id,
          label: detection.class || "target",
          confidence: `${Math.round(Number(detection.confidence || 0) * 100)}%`,
          uncalibrated: detection.coordinate.status === "ESTIMATED_UNCALIBRATED",
          clusterSize: Number(detection.cluster_size || 1),
        },
        geometry: {
          type: "Point",
          coordinates: [Number(detection.coordinate.lon), Number(detection.coordinate.lat)],
        },
      })),
  };
}

function liveDetectionPointData(detections) {
  return {
    type: "FeatureCollection",
    features: (detections || [])
      .filter((detection) => hasValidPosition(detection.lat, detection.lon))
      .map((detection) => ({
        type: "Feature",
        properties: {
          detectionId: detection.detection_id,
          confidence: Number(detection.confidence || 0),
          located: detection.located === true,
        },
        geometry: {
          type: "Point",
          coordinates: [Number(detection.lon), Number(detection.lat)],
        },
      })),
  };
}

function createAircraftLayer(stateRef, trackRef) {
  let map;
  let renderer;
  let loadedModel;
  let altitudeLine;
  let trackLine;
  const camera = new THREE.Camera();
  const scene = new THREE.Scene();
  const aircraftAnchor = new THREE.Group();
  const aircraftModel = new THREE.Group();
  const groundAid = new THREE.Group();

  scene.add(new THREE.HemisphereLight(0xffffff, 0x0f172a, 4.2));
  const directional = new THREE.DirectionalLight(0xffffff, 3.2);
  directional.position.set(-12, -8, 24);
  scene.add(directional);
  const rim = new THREE.DirectionalLight(0x7dd3fc, 2.8);
  rim.position.set(16, 10, 18);
  scene.add(rim);

  const shadowMaterial = new THREE.MeshBasicMaterial({
    color: 0x00b6b6,
    transparent: true,
    opacity: 0.18,
    depthWrite: false,
  });
  const shadow = new THREE.Mesh(new THREE.CircleGeometry(MODEL_SIZE_METERS * 0.62, 48), shadowMaterial);
  shadow.renderOrder = -1;
  groundAid.add(shadow);

  const ringMaterial = new THREE.MeshBasicMaterial({
    color: 0xcffff8,
    transparent: true,
    opacity: 0.62,
    side: THREE.DoubleSide,
    depthWrite: false,
  });
  const ring = new THREE.Mesh(
    new THREE.RingGeometry(MODEL_SIZE_METERS * 0.7, MODEL_SIZE_METERS * 0.78, 64),
    ringMaterial,
  );
  groundAid.add(ring);

  altitudeLine = new THREE.Line(
    new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(0, 0, 0), new THREE.Vector3(0, 0, 0)]),
    new THREE.LineBasicMaterial({ color: 0x00bda5, transparent: true, opacity: 0.85 }),
  );
  groundAid.add(altitudeLine);

  trackLine = new THREE.Line(
    new THREE.BufferGeometry(),
    new THREE.LineBasicMaterial({
      color: 0x00b6b6,
      transparent: true,
      opacity: 0.95,
      depthWrite: false,
    }),
  );
  trackLine.frustumCulled = false;
  scene.add(trackLine);

  aircraftAnchor.add(groundAid);
  aircraftAnchor.add(aircraftModel);
  scene.add(aircraftAnchor);

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
          loadedModel.updateMatrixWorld(true);
          const groundBox = new THREE.Box3().setFromObject(loadedModel);
          loadedModel.position.z -= groundBox.min.z;
          loadedModel.traverse((node) => {
            if (!node.isMesh) return;
            const sourceMaterials = Array.isArray(node.material) ? node.material : [node.material];
            const materials = sourceMaterials.map((sourceMaterial) => {
              const material = sourceMaterial.clone();
              const identity = `${node.name} ${material.name}`;
              material.color?.set(ACCENT_NAME_PATTERN.test(identity) ? MODEL_ACCENT_COLOR : MODEL_BODY_COLOR);
              if (material.emissive) {
                material.emissive.set(MODEL_EMISSIVE_COLOR);
                material.emissiveIntensity = ACCENT_NAME_PATTERN.test(identity) ? 0.18 : 0.08;
              }
              material.roughness = Math.max(Number(material.roughness ?? 0.6), 0.35);
              return material;
            });
            node.material = Array.isArray(node.material) ? materials : materials[0];
          });
          aircraftModel.add(loadedModel);
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

      const trackPoints = (trackRef.current || [])
        .map((point) => {
          const pointCoordinate = maplibregl.MercatorCoordinate.fromLngLat(
            [Number(point.lng), Number(point.lat)],
            Math.max(0, Number(point.alt || 0)),
          );
          return new THREE.Vector3(
            (pointCoordinate.x - coordinate.x) / scale,
            (pointCoordinate.y - coordinate.y) / -scale,
            (pointCoordinate.z - coordinate.z) / scale,
          );
        });
      trackLine.geometry.dispose();
      trackLine.geometry = new THREE.BufferGeometry().setFromPoints(trackPoints);
      trackLine.visible = trackPoints.length > 1;

      const altitudeMeters = Math.max(0, Number(state.alt || 0));
      groundAid.position.z = -altitudeMeters;
      const altitudeGeometry = altitudeLine.geometry;
      const altitudePositions = altitudeGeometry.attributes.position.array;
      altitudePositions[2] = 0;
      altitudePositions[5] = altitudeMeters;
      altitudeGeometry.attributes.position.needsUpdate = true;
      altitudeLine.visible = altitudeMeters > 1;

      aircraftModel.rotation.order = "ZYX";
      aircraftModel.rotation.x = toRadians(state.pitchDeg);
      aircraftModel.rotation.y = toRadians(-state.rollDeg);
      aircraftModel.rotation.z = toRadians(-(state.headingDeg + MODEL_HEADING_OFFSET_DEG));

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
      groundAid.traverse((node) => {
        node.geometry?.dispose();
        node.material?.dispose();
      });
      trackLine.geometry?.dispose();
      trackLine.material?.dispose();
      renderer?.dispose();
    },
  };
}

function OperationalMap({ lat, lng, alt = 0, headingDeg = 0, rollDeg = 0, pitchDeg = 0, mission = null }) {
  const mountRef = useRef(null);
  const mapRef = useRef(null);
  const trackRef = useRef([]);
  const missionRef = useRef(mission);
  const followRef = useRef(false);
  const stateRef = useRef({ lat, lng, alt, headingDeg, rollDeg, pitchDeg });
  const detectionsRef = useRef([]);
  const detectionPopupRef = useRef(null);
  const liveDetectionsRef = useRef([]);
  const isRecordingRef = useRef(false);
  const [isFollowing, setIsFollowing] = useState(false);

  const setFollowing = (nextValue) => {
    followRef.current = nextValue;
    setIsFollowing(nextValue);
    const state = stateRef.current;
    if (nextValue && hasValidPosition(state.lat, state.lng)) {
      mapRef.current?.easeTo({
        center: [Number(state.lng), Number(state.lat)],
        duration: 500,
        essential: true,
      });
    }
  };

  useEffect(() => {
    stateRef.current = { lat, lng, alt, headingDeg, rollDeg, pitchDeg };
    mapRef.current?.triggerRepaint();
  }, [alt, headingDeg, lat, lng, pitchDeg, rollDeg]);

  useEffect(() => {
    missionRef.current = mission;
    const map = mapRef.current;
    if (!map?.getSource("mission-route")) return;
    map.getSource("mission-route").setData(missionRouteData(mission));
    map.getSource("mission-points").setData(missionPointData(mission));
    map.getSource("mission-current-point")?.setData(currentMissionPointData(mission));
  }, [mission]);

  useEffect(() => {
    let cancelled = false;
    const pollDetections = async () => {
      const response = await apiGet("/api/v1/postflight/detections");
      if (cancelled || !response.ok) return;
      detectionsRef.current = response.data?.detections || [];
      mapRef.current?.getSource("postflight-detections")?.setData(detectionPointData(detectionsRef.current));
    };
    pollDetections();
    const interval = setInterval(pollDetections, DETECTIONS_POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    const clearLiveDetections = () => {
      liveDetectionsRef.current = [];
      mapRef.current?.getSource("live-detections")?.setData(liveDetectionPointData([]));
    };
    const pollLiveDetections = async () => {
      const statusResponse = await apiGet("/api/v1/recordings/status");
      if (cancelled) return;
      const recording = statusResponse.ok && statusResponse.data?.recording === true;
      if (recording !== isRecordingRef.current) {
        isRecordingRef.current = recording;
        if (!recording) clearLiveDetections();
      }
      if (!recording) return;
      const response = await apiGet("/api/v1/live/detections");
      if (cancelled || !response.ok) return;
      liveDetectionsRef.current = response.data?.detections || [];
      mapRef.current?.getSource("live-detections")?.setData(liveDetectionPointData(liveDetectionsRef.current));
    };
    pollLiveDetections();
    const interval = setInterval(pollLiveDetections, LIVE_DETECTIONS_POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

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
    map.on("dragstart", () => setFollowing(false));
    map.on("load", () => {
      map.addSource("mission-route", {
        type: "geojson",
        data: missionRouteData(missionRef.current),
      });
      map.addLayer({
        id: "mission-route",
        type: "line",
        source: "mission-route",
        paint: {
          "line-color": "#00b6b6",
          "line-width": 3,
          "line-opacity": 0.86,
          "line-dasharray": [2, 1.2],
        },
      });
      map.addSource("mission-points", {
        type: "geojson",
        data: missionPointData(missionRef.current),
      });
      map.addLayer({
        id: "mission-point-halo",
        type: "circle",
        source: "mission-points",
        paint: {
          "circle-radius": 11,
          "circle-color": "rgba(0, 189, 165, 0.18)",
          "circle-stroke-color": "#00bda5",
          "circle-stroke-width": 2,
        },
      });
      map.addLayer({
        id: "mission-point-label",
        type: "symbol",
        source: "mission-points",
        layout: {
          "text-field": ["get", "label"],
          "text-size": 12,
          "text-font": ["Open Sans Bold"],
          "text-offset": [0, 0],
          "text-anchor": "center",
          "text-allow-overlap": true,
        },
        paint: {
          "text-color": "#f8fafc",
          "text-halo-color": "#0f172a",
          "text-halo-width": 1.5,
        },
      });
      map.addLayer({
        id: "mission-point-detail",
        type: "symbol",
        source: "mission-points",
        layout: {
          "text-field": ["concat", ["get", "command"], " ", ["get", "alt"]],
          "text-size": 10,
          "text-font": ["Open Sans Regular"],
          "text-offset": [0, 1.6],
          "text-anchor": "top",
          "text-allow-overlap": false,
        },
        paint: {
          "text-color": "#cffff8",
          "text-halo-color": "#0f172a",
          "text-halo-width": 1,
        },
      });
      map.addSource("mission-current-point", {
        type: "geojson",
        data: currentMissionPointData(missionRef.current),
      });
      map.addLayer({
        id: "mission-current-halo",
        type: "circle",
        source: "mission-current-point",
        paint: {
          "circle-radius": 20,
          "circle-color": "rgba(0, 189, 165, 0.16)",
          "circle-stroke-color": "#00bda5",
          "circle-stroke-width": 3,
        },
      });
      map.addLayer({
        id: "mission-current-core",
        type: "circle",
        source: "mission-current-point",
        paint: {
          "circle-radius": 7,
          "circle-color": "#00bda5",
          "circle-stroke-color": "#cffff8",
          "circle-stroke-width": 2,
        },
      });
      map.addLayer({
        id: "mission-current-label",
        type: "symbol",
        source: "mission-current-point",
        layout: {
          "text-field": ["concat", "WP ", ["get", "label"]],
          "text-size": 11,
          "text-font": ["Open Sans Bold"],
          "text-offset": [0, -2.4],
          "text-anchor": "bottom",
          "text-allow-overlap": true,
        },
        paint: {
          "text-color": "#cffff8",
          "text-halo-color": "#003b35",
          "text-halo-width": 1.5,
        },
      });
      map.addSource("postflight-detections", {
        type: "geojson",
        data: detectionPointData(detectionsRef.current),
      });
      map.addLayer({
        id: "postflight-detection-halo",
        type: "circle",
        source: "postflight-detections",
        paint: {
          "circle-radius": 12,
          "circle-color": "rgba(248, 113, 113, 0.2)",
          "circle-stroke-color": "#f87171",
          "circle-stroke-width": 2,
        },
      });
      map.addLayer({
        id: "postflight-detection-core",
        type: "circle",
        source: "postflight-detections",
        paint: {
          "circle-radius": 5,
          "circle-color": ["case", ["get", "uncalibrated"], "#fbbf24", "#f87171"],
          "circle-stroke-color": "#fff7ed",
          "circle-stroke-width": 1.5,
        },
      });
      map.addLayer({
        id: "postflight-detection-label",
        type: "symbol",
        source: "postflight-detections",
        layout: {
          "text-field": ["get", "label"],
          "text-size": 10,
          "text-font": ["Open Sans Regular"],
          "text-offset": [0, 1.3],
          "text-anchor": "top",
          "text-allow-overlap": false,
        },
        paint: {
          "text-color": "#fecaca",
          "text-halo-color": "#450a0a",
          "text-halo-width": 1,
        },
      });

      map.addSource("live-detections", {
        type: "geojson",
        data: liveDetectionPointData(liveDetectionsRef.current),
      });
      map.addLayer({
        id: "live-detection-dot",
        type: "circle",
        source: "live-detections",
        paint: {
          "circle-radius": 4,
          "circle-color": ["case", ["==", ["get", "located"], false], "#94a3b8", "#fbbf24"],
          // Raw/un-clustered noise layer: opacity carries confidence for
          // located dots, while dots that fell back to the vehicle's own
          // position (no ground-plane estimate yet) stay a fixed dim gray
          // regardless of confidence -- they're not placed, just "nearby".
          "circle-opacity": [
            "case",
            ["==", ["get", "located"], false],
            0.35,
            ["interpolate", ["linear"], ["get", "confidence"], 0, 0.15, 1, 0.95],
          ],
        },
      });

      map.on("mouseenter", "postflight-detection-core", (event) => {
        map.getCanvas().style.cursor = "pointer";
        const feature = event.features?.[0];
        if (!feature) return;
        const { detectionId, label, confidence, uncalibrated, clusterSize } = feature.properties;
        const coordinates = feature.geometry.coordinates.slice();
        const snapshotUrl = `${API_BASE}/api/v1/postflight/detections/${detectionId}/snapshot`;
        detectionPopupRef.current?.remove();
        detectionPopupRef.current = new maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 14, className: "detection-hover-popup" })
          .setLngLat(coordinates)
          .setHTML(
            `<div class="detection-hover-card">`
            + `<img src="${snapshotUrl}" alt="${label}" loading="lazy" />`
            + `<div class="detection-hover-caption">`
            + `<span class="detection-hover-label">${label}</span>`
            + `<span class="detection-hover-confidence">${confidence}</span>`
            + (Number(clusterSize) > 1
              ? `<span class="detection-hover-cluster">confirmed by ${clusterSize} sightings</span>`
              : "")
            + (uncalibrated === "true" || uncalibrated === true
              ? `<span class="detection-hover-caveat">uncalibrated estimate</span>`
              : "")
            + `</div></div>`,
          )
          .addTo(map);
      });
      map.on("mouseleave", "postflight-detection-core", () => {
        map.getCanvas().style.cursor = "";
        detectionPopupRef.current?.remove();
        detectionPopupRef.current = null;
      });

      map.addLayer(createAircraftLayer(stateRef, trackRef));

      const state = stateRef.current;
      if (hasValidPosition(state.lat, state.lng)) {
        const coordinate = { lng: Number(state.lng), lat: Number(state.lat), alt: Math.max(0, Number(state.alt || 0)) };
        trackRef.current = [coordinate];
        map.jumpTo({
          center: [coordinate.lng, coordinate.lat],
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

    const coordinate = { lng: Number(lng), lat: Number(lat), alt: Math.max(0, Number(alt || 0)) };
    const previous = trackRef.current.at(-1);
    const moved =
      !previous
      || Math.abs(previous.lng - coordinate.lng) + Math.abs(previous.lat - coordinate.lat) > 0.000001
      || Math.abs(previous.alt - coordinate.alt) > 0.5;
    if (moved) {
      trackRef.current = [...trackRef.current, coordinate].slice(-MAX_TRACK_POINTS);
      map.triggerRepaint();
    }

    if (followRef.current) {
      map.easeTo({
        center: [coordinate.lng, coordinate.lat],
        duration: 450,
        essential: true,
      });
    }
  }, [alt, lat, lng]);

  return (
    <div className="operational-map-shell">
      <div className="operational-map" ref={mountRef} />
      <div className="tactical-map-grid" aria-hidden="true" />
      <div className="map-camera-controls">
        <button className={isFollowing ? "active map-follow-button" : "map-follow-button"} type="button" title={isFollowing ? "Disable aircraft follow" : "Follow aircraft"} aria-label={isFollowing ? "Disable aircraft follow" : "Follow aircraft"} onClick={() => setFollowing(!isFollowing)}>
          <FollowIcon /><span>{isFollowing ? "Following" : "Follow"}</span>
        </button>
        <button className="icon-button" type="button" title="Flat map view" aria-label="Flat map view" onClick={() => mapRef.current?.easeTo({ pitch: 0, duration: 450 })}>
          <FlatMapIcon />
        </button>
        <button className="icon-button" type="button" title="3D map view" aria-label="3D map view" onClick={() => mapRef.current?.easeTo({ pitch: 60, duration: 450 })}>
          <ThreeDIcon />
        </button>
      </div>
    </div>
  );
}

export default OperationalMap;
