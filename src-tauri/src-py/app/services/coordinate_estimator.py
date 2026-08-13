"""Ray-to-ground-plane target geolocation: turns a detection bbox plus the
vehicle's pose at capture time into an estimated real-world lat/lon.

Math background: unproject the bbox center through the pinhole camera model
into a 3D ray in camera space, rotate that ray into the world (NED) frame
using the vehicle's attitude, intersect it with a flat ground plane at the
vehicle's current relative (AGL) altitude, then convert the resulting
north/east offset (meters) into a lat/lon delta with a flat-earth
approximation (accurate to a few cm over the few-hundred-meter ranges this
is used at).

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


def _rotation_body_to_ned(roll_deg: float, pitch_deg: float, yaw_deg: float) -> np.ndarray:
    """Standard aerospace ZYX (yaw-pitch-roll) body->NED rotation, MAVLink convention."""
    r, p, y = math.radians(roll_deg), math.radians(pitch_deg), math.radians(yaw_deg)
    cr, sr = math.cos(r), math.sin(r)
    cp, sp = math.cos(p), math.sin(p)
    cy, sy = math.cos(y), math.sin(y)
    return np.array(
        [
            [cp * cy, sr * sp * cy - cr * sy, cr * sp * cy + sr * sy],
            [cp * sy, sr * sp * sy + cr * cy, cr * sp * sy - sr * cy],
            [-sp, sr * cp, cr * cp],
        ],
        dtype=np.float64,
    )


# Fixed camera-optical-frame -> vehicle-body-frame rotation for the canonical
# "boresight straight down, top-of-image toward the nose" nadir mount: camera
# +Z (boresight) -> body +Z (down), camera +X (image right) -> body +Y
# (right), camera +Y (image down) -> body -X (toward the tail). This is the
# single most common belly-camera install; if this airframe's camera is
# mounted differently, express the difference via JETSON_CAMERA_MOUNT_*_DEG
# rather than editing this constant.
_NADIR_CAMERA_TO_BODY = np.array(
    [
        [0.0, -1.0, 0.0],
        [1.0, 0.0, 0.0],
        [0.0, 0.0, 1.0],
    ],
    dtype=np.float64,
)


class CameraCalibration:
    """Pinhole intrinsics + rigid mount offset. See module docstring for the calibration caveat."""

    def __init__(self):
        self.focal_length_mm = _env_float("JETSON_CAMERA_FOCAL_LENGTH_MM", 6.0)
        self.sensor_width_mm = _env_float("JETSON_CAMERA_SENSOR_WIDTH_MM", 6.287)
        self.mount_roll_deg = _env_float("JETSON_CAMERA_MOUNT_ROLL_DEG", 0.0)
        self.mount_pitch_deg = _env_float("JETSON_CAMERA_MOUNT_PITCH_DEG", 0.0)
        self.mount_yaw_deg = _env_float("JETSON_CAMERA_MOUNT_YAW_DEG", 0.0)
        self.is_calibrated = _env_bool("JETSON_CAMERA_CALIBRATED", False)
        self._mount_offset = _rotation_body_to_ned(self.mount_roll_deg, self.mount_pitch_deg, self.mount_yaw_deg)
        self.camera_to_body = self._mount_offset @ _NADIR_CAMERA_TO_BODY

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
    ray_cam = k_inv @ np.array([u, v, 1.0], dtype=np.float64)

    r_body_to_ned = _rotation_body_to_ned(roll_deg, pitch_deg, yaw_deg)
    ray_ned = r_body_to_ned @ calibration.camera_to_body @ ray_cam
    if ray_ned[2] <= 1e-6:
        return None  # ray points level or upward from the vehicle; never meets the ground below it
    t = altitude_agl_m / ray_ned[2]
    return t * ray_ned[0], t * ray_ned[1]


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
