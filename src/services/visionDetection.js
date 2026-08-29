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
