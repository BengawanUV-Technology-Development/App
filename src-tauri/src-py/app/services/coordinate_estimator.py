"""Ray-to-ground-plane target geolocation: turns a detection bbox plus the
vehicle's pose at capture time into an estimated real-world lat/lon.

Math background: unproject the bbox center through the pinhole camera model
into a 3D ray in camera space, rotate that ray into a Z-up world frame using
the vehicle's attitude, intersect it with a flat ground plane at the
vehicle's current relative (AGL) altitude, then convert the resulting
north/east offset (meters) into a lat/lon delta with a flat-earth
approximation (accurate to a few cm over the few-hundred-meter ranges this
is used at).

Rotation convention: the roll/pitch/yaw -> rotation-matrix step (R = Rx @ Ry
@ Rz) and the camera-frame axis flip are ported as-is from
irfan/mission-planner-vision-refactor's geotagging.py, not the aerospace
ZYX/MAVLink body->NED convention -- team decision (2026-08-14) to keep that
branch's math here for now so the two stay merge-compatible. It has not been
validated against real MAVLink telemetry; revisit if target estimates look
systematically off once real flight data is available.

IMPORTANT -- calibration status: the camera intrinsics (focal length, sensor
width) and the mount rotation default to placeholder values borrowed from
the team's Coordinate-Estimator research prototype. They have NOT been
measured against the physical Arducam or verified against its actual mount
orientation on the airframe. Every estimate this module returns is tagged
"status": "ESTIMATED_UNCALIBRATED" until JETSON_CAMERA_CALIBRATED=true is
set (which you should only do after replacing the JETSON_CAMERA_* env vars
below with real, measured values and validating against a known target).
Treat ESTIMATED_UNCALIBRATED output as "roughly in the right place", not a
number to score a competition task against.
"""

from __future__ import annotations

import math
import os
from typing import Any

import numpy as np

EARTH_RADIUS_M = 6378137.0  # WGS84 semi-major axis; flat-earth approximation.


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _rotation_world(roll_deg: float, pitch_deg: float, yaw_deg: float) -> np.ndarray:
    """R = Rx @ Ry @ Rz, ported as-is from irfan/mission-planner-vision-refactor's
    geotagging.get_rotation_matrix(). See module docstring for the convention note."""
    r, p, y = math.radians(roll_deg), math.radians(pitch_deg), math.radians(yaw_deg)
    cr, sr = math.cos(r), math.sin(r)
    cp, sp = math.cos(p), math.sin(p)
    cy, sy = math.cos(y), math.sin(y)
    rx = np.array([[1.0, 0.0, 0.0], [0.0, cr, -sr], [0.0, sr, cr]], dtype=np.float64)
    ry = np.array([[cp, 0.0, sp], [0.0, 1.0, 0.0], [-sp, 0.0, cp]], dtype=np.float64)
    rz = np.array([[cy, -sy, 0.0], [sy, cy, 0.0], [0.0, 0.0, 1.0]], dtype=np.float64)
    return rx @ ry @ rz


class CameraCalibration:
    """Pinhole intrinsics. See module docstring for the calibration caveat."""

    def __init__(self):
        self.focal_length_mm = _env_float("JETSON_CAMERA_FOCAL_LENGTH_MM", 6.0)
        self.sensor_width_mm = _env_float("JETSON_CAMERA_SENSOR_WIDTH_MM", 6.287)
        self.is_calibrated = _env_bool("JETSON_CAMERA_CALIBRATED", False)

    def intrinsics(self, image_width: int, image_height: int) -> np.ndarray:
        fx = self.focal_length_mm * (image_width / self.sensor_width_mm)
        fy = fx
        cx = image_width / 2.0
        cy = image_height / 2.0
        return np.array([[fx, 0.0, cx], [0.0, fy, cy], [0.0, 0.0, 1.0]], dtype=np.float64)


def _estimate_ground_offset_m(
    *,
    bbox_normalized_xyxy: list[float],
    image_width: int,
    image_height: int,
    roll_deg: float,
    pitch_deg: float,
    yaw_deg: float,
    altitude_agl_m: float,
    calibration: CameraCalibration,
) -> tuple[float, float] | None:
    """(north_m, east_m) offset of the target from the vehicle, or None if the ray can't reach the ground."""
    if altitude_agl_m is None or altitude_agl_m <= 0:
        return None
    u = (bbox_normalized_xyxy[0] + bbox_normalized_xyxy[2]) / 2.0 * image_width
    v = (bbox_normalized_xyxy[1] + bbox_normalized_xyxy[3]) / 2.0 * image_height
    k_inv = np.linalg.inv(calibration.intrinsics(image_width, image_height))
    ray_cv = k_inv @ np.array([u, v, 1.0], dtype=np.float64)
    # CV camera convention (+Y down, +Z forward) -> Blender-style (+Y up, +Z backward).
    ray_blender = np.array([ray_cv[0], -ray_cv[1], -ray_cv[2]], dtype=np.float64)

    ray_world = _rotation_world(roll_deg, pitch_deg, yaw_deg) @ ray_blender
    norm = np.linalg.norm(ray_world)
    if norm == 0:
        return None
    ray_world = ray_world / norm
    if ray_world[2] >= -1e-6:
        return None  # ray level or upward in this Z-up world frame; never meets the ground below it
    t = -altitude_agl_m / ray_world[2]
    east_m, north_m = t * ray_world[0], t * ray_world[1]
    return north_m, east_m


def _offset_to_latlon(lat_deg: float, lon_deg: float, north_m: float, east_m: float) -> tuple[float, float]:
    lat_rad = math.radians(lat_deg)
    delta_lat = (north_m / EARTH_RADIUS_M) * (180.0 / math.pi)
    delta_lon = (east_m / (EARTH_RADIUS_M * math.cos(lat_rad))) * (180.0 / math.pi)
    return lat_deg + delta_lat, lon_deg + delta_lon


def estimate_target_latlon(
    *,
    bbox_normalized_xyxy: list[float],
    image_width: int,
    image_height: int,
    telemetry: dict[str, Any] | None,
    calibration: CameraCalibration,
) -> dict[str, Any]:
    """Best-effort target lat/lon for one detection. Always returns a dict with a "status" key."""
    if telemetry is None:
        return {"status": "not_available", "reason": "no_telemetry_within_join_window"}

    lat, lon = telemetry.get("lat"), telemetry.get("lng")
    alt = telemetry.get("alt")
    roll, pitch, yaw = telemetry.get("roll_deg"), telemetry.get("pitch_deg"), telemetry.get("yaw_deg")
    if None in (lat, lon, alt, roll, pitch, yaw):
        return {"status": "not_available", "reason": "incomplete_telemetry_fields"}

    offset = _estimate_ground_offset_m(
        bbox_normalized_xyxy=bbox_normalized_xyxy,
        image_width=image_width,
        image_height=image_height,
        roll_deg=roll,
        pitch_deg=pitch,
        yaw_deg=yaw,
        altitude_agl_m=alt,
        calibration=calibration,
    )
    if offset is None:
        return {"status": "not_available", "reason": "ray_does_not_intersect_ground"}

    target_lat, target_lon = _offset_to_latlon(lat, lon, *offset)
    return {
        "status": "ESTIMATED" if calibration.is_calibrated else "ESTIMATED_UNCALIBRATED",
        "lat": target_lat,
        "lon": target_lon,
        "ground_plane_assumption": "flat_at_vehicle_relative_altitude",
        "telemetry_sample_age_seconds": telemetry.get("_sample_age_seconds"),
    }
