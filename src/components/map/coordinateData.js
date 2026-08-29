const RENDERABLE_STATUSES = new Set([
  "ESTIMATED_UNCALIBRATED",
  "CALIBRATED_ESTIMATE",
]);

function numeric(value) {
  const result = Number(value);
  return Number.isFinite(result) ? result : null;
}

function coordinateResult(record) {
  if (record?.coordinate && typeof record.coordinate === "object") {
    return record.coordinate;
  }
  return record;
}

function isRenderableCoordinate(record) {
  const result = coordinateResult(record);
  const latitude = numeric(result?.latitude);
  const longitude = numeric(result?.longitude);
  return RENDERABLE_STATUSES.has(result?.status)
    && latitude !== null
    && longitude !== null
    && latitude >= -90
    && latitude <= 90
    && longitude >= -180
    && longitude <= 180
    && !(latitude === 0 && longitude === 0);
}

export function coordinateTargetCenter(record) {
  if (!isRenderableCoordinate(record)) return null;
  const result = coordinateResult(record);
  return [Number(result.longitude), Number(result.latitude)];
}

export function coordinateTargetData(record) {
  if (!isRenderableCoordinate(record)) {
    return { type: "FeatureCollection", features: [] };
  }

  const result = coordinateResult(record);
  const className = String(record?.class_name || result.class_name || "target");
  const confidence = numeric(record?.confidence ?? result.confidence);
  const frameId = record?.frame_id ?? result.frame_id;
  const qualificationStatus = String(
    record?.qualification_status
      || result.qualification_status
      || "UNSPECIFIED",
  );
  const smokeOnly = qualificationStatus === "NON_QUALIFICATION";
  const label = smokeOnly ? "TARGET · SMOKE" : "TARGET";
  const detail = [
    className,
    frameId === null || frameId === undefined ? null : `F${frameId}`,
    confidence === null ? null : `${(confidence * 100).toFixed(1)}%`,
  ].filter(Boolean).join(" · ");

  return {
    type: "FeatureCollection",
    features: [
      {
        type: "Feature",
        properties: {
          label,
          detail,
          status: result.status,
          qualificationStatus,
          detectionId: record?.detection_id || result.detection_id || "",
        },
        geometry: {
          type: "Point",
          coordinates: coordinateTargetCenter(record),
        },
      },
    ],
  };
}

export function hasRenderableCoordinate(record) {
  return isRenderableCoordinate(record);
}
