import assert from "node:assert/strict";
import test from "node:test";

import { COORDINATE_SMOKE_TEST } from "../src/data/coordinateSmokeTest.js";
import {
  coordinateTargetCenter,
  coordinateTargetData,
  hasRenderableCoordinate,
} from "../src/components/map/coordinateData.js";

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
