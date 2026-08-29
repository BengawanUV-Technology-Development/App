export function extractLatestDetection(response) {
  if (response?.active !== true) return null;
  return response?.detection && typeof response.detection === "object"
    ? response.detection
    : null;
}

export function extractLatestCoordinate(response) {
  const detection = extractLatestDetection(response);
  return detection?.coordinate && typeof detection.coordinate === "object"
    ? detection.coordinate
    : null;
}

export function normalizeLatestVisionResponse(response) {
  if (!response?.ok) {
    return {
      active: false,
      mission_id: null,
      detection: null,
      coordinate: null,
      latest_overlay: null,
      error: response?.error || "Vision endpoint unavailable",
    };
  }
  return {
    active: response.data?.active === true,
    mission_id: response.data?.mission_id || null,
    detection: extractLatestDetection(response.data),
    coordinate: extractLatestCoordinate(response.data),
    latest_overlay: response.data?.latest_overlay || null,
    error: null,
  };
}
