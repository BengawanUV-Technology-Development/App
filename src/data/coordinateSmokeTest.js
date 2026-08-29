// Derived from the real pedestrian detection at frame 1919 and the
// previously captured prototype telemetry. The altitude and synchronized
// status below are deliberately smoke-only assumptions; this is not flight
// qualification evidence and must never be used as a production data source.
export const COORDINATE_SMOKE_TEST = Object.freeze({
  schema_version: 1,
  record_type: "coordinate_estimate",
  status: "ESTIMATED_UNCALIBRATED",
  reason: "Smoke-only display fixture; source telemetry used synthetic clock alignment",
  mission_id: "mission-3c0ae2c8-d8e2-449e-9f68-7604eae0ac9f",
  detection_id: "mission-3c0ae2c8-d8e2-449e-9f68-7604eae0ac9f:1919:0",
  capture_epoch: 1,
  frame_id: 1919,
  capture_utc_ns: 1786522995160932352,
  class_id: 0,
  class_name: "pedestrian",
  confidence: 0.7204331159591675,
  bbox_xyxy_normalized: [
    0.7467085520426432,
    0.9296379937065973,
    0.7787148157755533,
    0.9996799045138889,
  ],
  latitude: -7.589893553862843,
  longitude: 110.8653516205431,
  local_offset_east_m: -2.9218544484796167,
  local_offset_north_m: 2.598880100416127,
  distance_m: 3.9104234034742404,
  bearing_deg: 311.65189496529086,
  altitude_m: 10.0,
  altitude_reference: "AGL",
  camera_attitude_frame: "camera_world",
  rotation_order: "XYZ",
  calibration_validated: false,
  qualification_status: "NON_QUALIFICATION",
  source_telemetry_status: "prototype_synthetic_clock_aligned",
  smoke_altitude_assumption_m: 10.0,
});
