import assert from "node:assert/strict";
import test from "node:test";

import { COORDINATE_SMOKE_TEST } from "../src/data/coordinateSmokeTest.js";
import {
  coordinateTargetCenter,
  coordinateTargetData,
  hasRenderableCoordinate,
} from "../src/components/map/coordinateData.js";
import {
  extractLatestDetection,
  extractLatestCoordinate,
  normalizeLatestVisionResponse,
} from "../src/services/visionDetection.js";

test("coordinate smoke fixture produces one map target point", () => {
  assert.equal(hasRenderableCoordinate(COORDINATE_SMOKE_TEST), true);
  assert.deepEqual(coordinateTargetCenter(COORDINATE_SMOKE_TEST), [
    COORDINATE_SMOKE_TEST.longitude,
    COORDINATE_SMOKE_TEST.latitude,
  ]);

  const featureCollection = coordinateTargetData(COORDINATE_SMOKE_TEST);
  assert.equal(featureCollection.features.length, 1);
  assert.deepEqual(featureCollection.features[0].geometry.coordinates, [
    110.8653516205431,
    -7.589893553862843,
  ]);
  assert.equal(featureCollection.features[0].properties.label, "TARGET · SMOKE");
  assert.match(featureCollection.features[0].properties.detail, /F1919/);
});

test("NOT_AVAILABLE coordinate is not rendered as a map target", () => {
  const unavailable = {
    ...COORDINATE_SMOKE_TEST,
    status: "NOT_AVAILABLE",
    latitude: null,
    longitude: null,
  };
  assert.equal(hasRenderableCoordinate(unavailable), false);
  assert.deepEqual(coordinateTargetData(unavailable), {
    type: "FeatureCollection",
    features: [],
  });
});

test("live detection response exposes only its own coordinate result", () => {
  const detection = {
    detection_id: "det-live-7",
    class_name: "pedestrian",
    frame_id: 7,
    coordinate: {
      status: "ESTIMATED_UNCALIBRATED",
      latitude: -6.2,
      longitude: 106.8,
    },
  };
  const response = {
    ok: true,
    active: true,
    mission_id: "mission-11111111-1111-4111-8111-111111111111",
    detection,
  };

  assert.deepEqual(extractLatestDetection(response), detection);
  assert.deepEqual(extractLatestCoordinate(response), detection.coordinate);
  assert.deepEqual(extractLatestCoordinate({ ok: true, active: true, detection: {
    ...detection,
    coordinate: { status: "NOT_AVAILABLE", latitude: null, longitude: null },
  } }), {
    status: "NOT_AVAILABLE",
    latitude: null,
    longitude: null,
  });
});

test("failed live detection poll clears stale target state", () => {
  const state = normalizeLatestVisionResponse({ ok: false, error: "backend offline" });

  assert.equal(state.active, false);
  assert.equal(state.detection, null);
  assert.equal(state.coordinate, null);
  assert.equal(state.error, "backend offline");
});
