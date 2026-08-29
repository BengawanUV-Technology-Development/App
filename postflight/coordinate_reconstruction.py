"""Offline coordinate reconstruction adapter for synchronized detections.

The ray geometry in this module is an adaptation of
``Coordinate-Estimator/target_localization.py`` at commit ``cf1d868``.  The
reference implementation is a video/CSV experiment; it does not provide a
reusable package, camera calibration file, geodetic conversion, or safety
guards for mission data.  This adapter keeps its geometry conventions intact:

* camera vectors use the reference Blender convention ``[x, -y, -z]``;
* the default Euler rotation is ``Rx @ Ry @ Rz``;
* a ray is intersected with a horizontal ``Z = z_ground`` plane.

The adapter is deliberately post-flight only.  It consumes the output of the
existing source-time synchronization implementation and never connects to
MAVLink, changes telemetry, or sends flight commands.
"""

from __future__ import annotations

import argparse
import json
import math
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from postflight.synchronization import synchronize_detections


NOT_AVAILABLE = "NOT_AVAILABLE"
ESTIMATED_UNCALIBRATED = "ESTIMATED_UNCALIBRATED"
CALIBRATED_ESTIMATE = "CALIBRATED_ESTIMATE"

_SCHEMA_VERSION = 1
_EARTH_RADIUS_M = 6_378_137.0
_EPSILON = 1e-9
_ALTITUDE_REFERENCES = {"AGL", "RELATIVE_HOME", "AMSL", "TERRAIN_RELATIVE"}
_ATTITUDE_FRAMES = {"body", "camera_world"}
_ROTATION_ORDERS = {"XYZ", "ZYX", "YXZ", "ZXY"}

Vector3 = tuple[float, float, float]
Matrix3 = tuple[tuple[float, float, float], ...]


class CoordinateReconstructionError(ValueError):
    """Raised for invalid adapter configuration or artifact input."""


@dataclass(frozen=True)
class CameraCalibration:
    """Explicit camera model and mounting metadata.

    There is no calibration format in the reference repository.  This
    dataclass is therefore the adapter contract, not a set of default values.
    A caller must provide the actual Arducam measurements.  ``validated`` is
    intentionally opt-in; it must not be set merely because the JSON parses.
    """

    camera_id: str
    image_width: int
    image_height: int
    fx: float
    fy: float
    cx: float
    cy: float
    distortion: tuple[float, ...] = ()
    mounting_rpy_deg: tuple[float, float, float] | None = None
    validated: bool = False
    source: str | None = None

    def validate(self) -> None:
        if not isinstance(self.camera_id, str) or not self.camera_id.strip():
            raise CoordinateReconstructionError("camera_id is required")
        if (
            not isinstance(self.image_width, int)
            or isinstance(self.image_width, bool)
            or self.image_width <= 0
            or not isinstance(self.image_height, int)
            or isinstance(self.image_height, bool)
            or self.image_height <= 0
        ):
            raise CoordinateReconstructionError(
                "image dimensions must be positive integers"
            )
        for name in ("fx", "fy", "cx", "cy"):
            value = getattr(self, name)
            if not _is_finite_number(value):
                raise CoordinateReconstructionError(f"invalid camera intrinsic: {name}")
        if self.fx <= 0 or self.fy <= 0:
            raise CoordinateReconstructionError("fx and fy must be positive")
        for value in self.distortion:
            if not _is_finite_number(value):
                raise CoordinateReconstructionError("distortion coefficients must be finite")
        if self.mounting_rpy_deg is not None:
            if len(self.mounting_rpy_deg) != 3 or any(
                not _is_finite_number(value) for value in self.mounting_rpy_deg
            ):
                raise CoordinateReconstructionError(
                    "mounting_rpy_deg must contain three finite values"
                )

    @classmethod
    def from_reference_optics(
        cls,
        *,
        camera_id: str,
        image_width: int,
        image_height: int,
        focal_length_mm: float,
        sensor_width_mm: float,
        mounting_rpy_deg: tuple[float, float, float] | None = None,
        validated: bool = False,
        source: str | None = "Coordinate-Estimator reference optical parameterization",
    ) -> "CameraCalibration":
        """Build the reference model from explicit optical measurements.

        This reproduces ``fx = focal_length_mm * width / sensor_width_mm``
        and ``fy = fx`` from the source repository.  It does not claim the
        measurements are correct or perform distortion correction.
        """

        if focal_length_mm <= 0 or sensor_width_mm <= 0:
            raise CoordinateReconstructionError(
                "focal_length_mm and sensor_width_mm must be positive"
            )
        fx = focal_length_mm * (image_width / sensor_width_mm)
        calibration = cls(
            camera_id=camera_id,
            image_width=image_width,
            image_height=image_height,
            fx=fx,
            fy=fx,
            cx=image_width / 2.0,
            cy=image_height / 2.0,
            mounting_rpy_deg=mounting_rpy_deg,
            validated=validated,
            source=source,
        )
        calibration.validate()
        return calibration

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CameraCalibration":
        """Load the adapter's explicit JSON-compatible calibration contract."""

        if not isinstance(value, Mapping):
            raise CoordinateReconstructionError("calibration must be an object")
        intrinsics = value.get("intrinsics")
        if not isinstance(intrinsics, Mapping):
            intrinsics = value

        def required_number(name: str) -> float:
            return _required_finite_value(
                intrinsics.get(name), f"calibration intrinsic {name}"
            )

        distortion_value = value.get(
            "distortion_coefficients", value.get("distortion", ())
        )
        if distortion_value is None:
            distortion_value = ()
        if not isinstance(distortion_value, Sequence) or isinstance(
            distortion_value, (str, bytes)
        ):
            raise CoordinateReconstructionError(
                "distortion_coefficients must be an array"
            )

        mounting_value = value.get(
            "mounting_rpy_deg", value.get("camera_mounting_rpy_deg")
        )
        mounting: tuple[float, float, float] | None
        if mounting_value is None:
            mounting = None
        elif isinstance(mounting_value, Mapping):
            mounting = tuple(
                _required_finite_value(mounting_value.get(axis), f"mounting {axis}")
                for axis in ("roll", "pitch", "yaw")
            )  # type: ignore[assignment]
        elif isinstance(mounting_value, Sequence) and not isinstance(
            mounting_value, (str, bytes)
        ):
            if len(mounting_value) != 3:
                raise CoordinateReconstructionError(
                    "mounting_rpy_deg must contain roll, pitch, yaw"
                )
            mounting = tuple(
                _required_finite_value(item, "mounting_rpy_deg")
                for item in mounting_value
            )  # type: ignore[assignment]
        else:
            raise CoordinateReconstructionError(
                "mounting_rpy_deg must be an object or three-element array"
            )

        camera_id = value.get("camera_id")
        if not isinstance(camera_id, str) or not camera_id.strip():
            raise CoordinateReconstructionError("calibration camera_id is required")
        image_width = _required_positive_integer(value.get("image_width"), "image_width")
        image_height = _required_positive_integer(
            value.get("image_height"), "image_height"
        )
        validated = value.get("validated", value.get("calibration_validated", False))
        if not isinstance(validated, bool):
            raise CoordinateReconstructionError("calibration validated must be boolean")

        calibration = cls(
            camera_id=camera_id.strip(),
            image_width=image_width,
            image_height=image_height,
            fx=required_number("fx"),
            fy=required_number("fy"),
            cx=required_number("cx"),
            cy=required_number("cy"),
            distortion=tuple(
                _required_finite_value(item, "distortion_coefficients")
                for item in distortion_value
            ),
            mounting_rpy_deg=mounting,
            validated=validated,
            source=str(value["source"]) if value.get("source") is not None else None,
        )
        calibration.validate()
        return calibration

    @classmethod
    def from_json(cls, path: str | Path) -> "CameraCalibration":
        source = Path(path)
        if not source.is_file():
            raise CoordinateReconstructionError(
                f"calibration file does not exist: {source}"
            )
        try:
            value = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CoordinateReconstructionError(
                f"cannot read calibration file: {source}"
            ) from exc
        return cls.from_dict(value)


@dataclass(frozen=True)
class CoordinateReconstructionConfig:
    """Conventions added by the app adapter around reference geometry."""

    rotation_order: str = "XYZ"
    camera_attitude_frame: str = "body"
    ground_plane_z_m: float = 0.0
    earth_radius_m: float = _EARTH_RADIUS_M

    def validate(self) -> None:
        if self.rotation_order not in _ROTATION_ORDERS:
            raise CoordinateReconstructionError(
                f"unsupported rotation order: {self.rotation_order}"
            )
        if self.camera_attitude_frame not in _ATTITUDE_FRAMES:
            raise CoordinateReconstructionError(
                f"unsupported camera attitude frame: {self.camera_attitude_frame}"
            )
        if not _is_finite_number(self.ground_plane_z_m):
            raise CoordinateReconstructionError("ground_plane_z_m must be finite")
        if not _is_finite_number(self.earth_radius_m) or self.earth_radius_m <= 0:
            raise CoordinateReconstructionError("earth_radius_m must be positive")


def build_intrinsic_matrix(
    width: int, height: int, focal_length: float, sensor_width: float
) -> Matrix3:
    """Reproduce the reference ``build_intrinsic_matrix`` formula."""

    if width <= 0 or height <= 0 or focal_length <= 0 or sensor_width <= 0:
        raise CoordinateReconstructionError("invalid reference camera dimensions/optics")
    fx = focal_length * (width / sensor_width)
    return (
        (float(fx), 0.0, width / 2.0),
        (0.0, float(fx), height / 2.0),
        (0.0, 0.0, 1.0),
    )


def get_rotation_matrix(
    roll_deg: float,
    pitch_deg: float,
    yaw_deg: float,
    order: str = "XYZ",
) -> Matrix3:
    """Reproduce the reference Euler rotation and its default order."""

    if order not in _ROTATION_ORDERS:
        raise CoordinateReconstructionError(f"unsupported rotation order: {order}")
    r = math.radians(float(roll_deg))
    p = math.radians(float(pitch_deg))
    y = math.radians(float(yaw_deg))

    rx: Matrix3 = (
        (1.0, 0.0, 0.0),
        (0.0, math.cos(r), -math.sin(r)),
        (0.0, math.sin(r), math.cos(r)),
    )
    ry: Matrix3 = (
        (math.cos(p), 0.0, math.sin(p)),
        (0.0, 1.0, 0.0),
        (-math.sin(p), 0.0, math.cos(p)),
    )
    rz: Matrix3 = (
        (math.cos(y), -math.sin(y), 0.0),
        (math.sin(y), math.cos(y), 0.0),
        (0.0, 0.0, 1.0),
    )
    factors = {"X": rx, "Y": ry, "Z": rz}
    result: Matrix3 = factors[order[0]]
    result = _matrix_multiply(result, factors[order[1]])
    return _matrix_multiply(result, factors[order[2]])


def unproject_pixel_to_ray(
    u: float, v: float, rotation_world: Matrix3, intrinsic_inverse: Matrix3
) -> Vector3:
    """Adapt the reference pixel-to-world ray conversion."""

    d_cam_cv = _matrix_vector(intrinsic_inverse, (float(u), float(v), 1.0))
    d_cam_blender = (d_cam_cv[0], -d_cam_cv[1], -d_cam_cv[2])
    d_world = _matrix_vector(rotation_world, d_cam_blender)
    norm = math.sqrt(sum(component * component for component in d_world))
    if not math.isfinite(norm) or norm <= _EPSILON:
        raise CoordinateReconstructionError("camera ray has zero or invalid norm")
    return tuple(component / norm for component in d_world)  # type: ignore[return-value]


def ray_ground_intersection(
    camera_position: Vector3, ray_world: Vector3, ground_plane_z: float
) -> tuple[float, float] | None:
    """Adapt the reference ray intersection with ``Z = ground_plane_z``."""

    if abs(ray_world[2]) <= _EPSILON:
        return None
    t = (ground_plane_z - camera_position[2]) / ray_world[2]
    if not math.isfinite(t) or t <= 0:
        return None
    intersection = tuple(
        camera_position[index] + t * ray_world[index] for index in range(3)
    )
    if not all(math.isfinite(value) for value in intersection):
        return None
    return intersection[0], intersection[1]


def local_xy_to_geodetic(
    origin_latitude: float,
    origin_longitude: float,
    east_m: float,
    north_m: float,
    earth_radius_m: float = _EARTH_RADIUS_M,
) -> tuple[float, float]:
    """Convert adapter-local ENU offsets to a small-distance lat/lon estimate."""

    if not all(
        _is_finite_number(value)
        for value in (
            origin_latitude,
            origin_longitude,
            east_m,
            north_m,
            earth_radius_m,
        )
    ):
        raise CoordinateReconstructionError("geodetic conversion input is invalid")
    if not -90.0 <= origin_latitude <= 90.0:
        raise CoordinateReconstructionError("origin latitude is outside [-90, 90]")
    if not -180.0 <= origin_longitude <= 180.0:
        raise CoordinateReconstructionError("origin longitude is outside [-180, 180]")
    if earth_radius_m <= 0:
        raise CoordinateReconstructionError("earth radius must be positive")
    cos_latitude = math.cos(math.radians(origin_latitude))
    if abs(cos_latitude) <= _EPSILON:
        raise CoordinateReconstructionError("longitude scale is unstable at the pole")
    latitude = origin_latitude + math.degrees(north_m / earth_radius_m)
    longitude = origin_longitude + math.degrees(
        east_m / (earth_radius_m * cos_latitude)
    )
    return latitude, longitude


class CoordinateReconstructionAdapter:
    """Convert one synchronized detection into a safe coordinate result."""

    def __init__(
        self,
        calibration: CameraCalibration | None,
        *,
        config: CoordinateReconstructionConfig | None = None,
    ) -> None:
        self.calibration = calibration
        self.config = config or CoordinateReconstructionConfig()
        self._configuration_error: str | None = None
        try:
            self.config.validate()
            if self.calibration is None:
                raise CoordinateReconstructionError("camera calibration is missing")
            self.calibration.validate()
        except CoordinateReconstructionError as exc:
            self._configuration_error = str(exc)

    def reconstruct(
        self,
        synchronized_detection: Mapping[str, Any],
        *,
        altitude_reference: str | None = None,
        camera_attitude_frame: str | None = None,
    ) -> dict[str, Any]:
        """Return a coordinate result without allowing unsafe fallbacks.

        The input must be one output record from
        :func:`postflight.synchronization.synchronize_detections`.  In
        particular, ``telemetry_sync_status`` must be exactly
        ``"synchronized"``; prototype/synthetic clock artifacts are rejected.
        ``altitude_reference`` is an explicit caller declaration.  Only AGL is
        accepted by the flat-ground model.
        """

        base = self._base_result(synchronized_detection)
        if self._configuration_error:
            return self._unavailable(base, "INVALID_CONFIGURATION", self._configuration_error)

        if synchronized_detection.get("telemetry_sync_status") != "synchronized":
            return self._unavailable(
                base,
                "TELEMETRY_NOT_SYNCHRONIZED",
                "coordinate reconstruction requires a real synchronized detection",
            )

        try:
            bbox = _normalized_bbox(synchronized_detection, self.calibration)
            base["bbox_xyxy_normalized"] = list(bbox)
            self._validate_identity(synchronized_detection)
            if (
                self.calibration.camera_id
                and synchronized_detection.get("camera_id")
                and synchronized_detection.get("camera_id") != self.calibration.camera_id
            ):
                raise CoordinateReconstructionError(
                    "detection camera_id does not match calibration camera_id"
                )

            telemetry = synchronized_detection.get("telemetry")
            if not isinstance(telemetry, Mapping):
                telemetry = {}
            latitude = _first_number(synchronized_detection, telemetry, "latitude")
            longitude = _first_number(synchronized_detection, telemetry, "longitude")
            roll = _first_number(
                synchronized_detection, telemetry, "roll", "roll_deg"
            )
            pitch = _first_number(
                synchronized_detection, telemetry, "pitch", "pitch_deg"
            )
            yaw = _first_number(synchronized_detection, telemetry, "yaw", "yaw_deg")
            if None in (latitude, longitude, roll, pitch, yaw):
                raise CoordinateReconstructionError("complete UAV attitude/position is missing")

            declared_reference = altitude_reference or _first_string(
                synchronized_detection, telemetry, "altitude_reference"
            )
            if declared_reference is None:
                raise CoordinateReconstructionError(
                    "altitude reference is missing; AGL must be declared explicitly"
                )
            declared_reference = declared_reference.upper()
            if declared_reference not in _ALTITUDE_REFERENCES:
                raise CoordinateReconstructionError(
                    f"unsupported altitude reference: {declared_reference}"
                )
            if declared_reference != "AGL":
                raise CoordinateReconstructionError(
                    "flat-ground estimator requires AGL; AMSL/relative-home is not AGL"
                )

            # ``relative_altitude``/``altitude`` may be relative to home or
            # AMSL-derived; neither is proof of terrain-relative AGL.  Only
            # an explicitly named AGL field is safe for this flat-ground
            # intersection.
            altitude = _first_number(
                synchronized_detection,
                telemetry,
                "altitude_agl_m",
            )
            if altitude is None or altitude <= 0:
                raise CoordinateReconstructionError(
                    "positive explicit altitude_agl_m is missing"
                )

            attitude_frame = camera_attitude_frame or self.config.camera_attitude_frame
            if attitude_frame not in _ATTITUDE_FRAMES:
                raise CoordinateReconstructionError(
                    f"unsupported camera attitude frame: {attitude_frame}"
                )
            rotation_world = get_rotation_matrix(
                roll,
                pitch,
                yaw,
                self.config.rotation_order,
            )
            if attitude_frame == "body":
                if self.calibration.mounting_rpy_deg is None:
                    raise CoordinateReconstructionError(
                        "camera mounting extrinsics are missing for body attitude"
                    )
                rotation_body_camera = get_rotation_matrix(
                    *self.calibration.mounting_rpy_deg,
                    self.config.rotation_order,
                )
                rotation_world = _matrix_multiply(rotation_world, rotation_body_camera)

            intrinsic_inverse = _invert_intrinsic_matrix(self.calibration)
            u = ((bbox[0] + bbox[2]) / 2.0) * self.calibration.image_width
            v = ((bbox[1] + bbox[3]) / 2.0) * self.calibration.image_height
            ray_world = unproject_pixel_to_ray(
                u,
                v,
                rotation_world,
                intrinsic_inverse,
            )
            camera_position = (
                0.0,
                0.0,
                self.config.ground_plane_z_m + altitude,
            )
            local_xy = ray_ground_intersection(
                camera_position,
                ray_world,
                self.config.ground_plane_z_m,
            )
            if local_xy is None:
                raise CoordinateReconstructionError(
                    "camera ray does not intersect the forward ground plane"
                )
            east_m, north_m = local_xy
            target_latitude, target_longitude = local_xy_to_geodetic(
                latitude,
                longitude,
                east_m,
                north_m,
                self.config.earth_radius_m,
            )
            distance_m = math.hypot(east_m, north_m)
            bearing_deg = math.degrees(math.atan2(east_m, north_m)) % 360.0
            base.update(
                {
                    "latitude": target_latitude,
                    "longitude": target_longitude,
                    "local_offset_east_m": east_m,
                    "local_offset_north_m": north_m,
                    "distance_m": distance_m,
                    "bearing_deg": bearing_deg,
                    "pixel_center": [u, v],
                    "altitude_reference": declared_reference,
                    "altitude_m": altitude,
                    "rotation_order": self.config.rotation_order,
                    "camera_attitude_frame": attitude_frame,
                    "ground_plane_assumption": "flat_z_plane",
                    "calibration_validated": self.calibration.validated,
                }
            )
            base["status"] = (
                CALIBRATED_ESTIMATE
                if self._is_calibrated_ready(attitude_frame)
                else ESTIMATED_UNCALIBRATED
            )
            if base["status"] == ESTIMATED_UNCALIBRATED:
                base["reason"] = self._uncalibrated_reason(attitude_frame)
            return base
        except (CoordinateReconstructionError, KeyError, TypeError, ValueError) as exc:
            return self._unavailable(base, "INVALID_RECONSTRUCTION_INPUT", str(exc))

    def reconstruct_record(
        self,
        synchronized_detection: Mapping[str, Any],
        *,
        altitude_reference: str | None = None,
        camera_attitude_frame: str | None = None,
    ) -> dict[str, Any]:
        """Append a coordinate result without overwriting UAV telemetry fields."""

        result = self.reconstruct(
            synchronized_detection,
            altitude_reference=altitude_reference,
            camera_attitude_frame=camera_attitude_frame,
        )
        output = dict(synchronized_detection)
        output["coordinate"] = result
        output["coordinate_status"] = result["status"]
        return output

    def _is_calibrated_ready(self, attitude_frame: str) -> bool:
        if self.calibration is None or not self.calibration.validated:
            return False
        if any(abs(value) > _EPSILON for value in self.calibration.distortion):
            # The reference algorithm has no distortion correction.
            return False
        if attitude_frame == "body" and self.calibration.mounting_rpy_deg is None:
            return False
        return True

    def _uncalibrated_reason(self, attitude_frame: str) -> str:
        if self.calibration is None:
            return "camera calibration is missing"
        if not self.calibration.validated:
            return "camera calibration is present but not validated"
        if any(abs(value) > _EPSILON for value in self.calibration.distortion):
            return "reference geometry does not correct non-zero distortion"
        if attitude_frame == "body" and self.calibration.mounting_rpy_deg is None:
            return "camera mounting extrinsics are missing"
        return "calibration quality is not fully qualified"

    @staticmethod
    def _validate_identity(record: Mapping[str, Any]) -> None:
        for field in ("mission_id", "frame_id", "capture_utc_ns"):
            value = record.get(field)
            if field == "mission_id" and not isinstance(value, str):
                raise CoordinateReconstructionError("mission_id is missing")
            if field == "frame_id" and (
                not isinstance(value, int) or isinstance(value, bool) or value < 0
            ):
                raise CoordinateReconstructionError("frame_id is invalid")
            if field == "capture_utc_ns" and (
                not isinstance(value, int) or isinstance(value, bool) or value <= 0
            ):
                raise CoordinateReconstructionError("capture_utc_ns is invalid")

    def _base_result(self, record: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "schema_version": _SCHEMA_VERSION,
            "record_type": "coordinate_estimate",
            "status": NOT_AVAILABLE,
            "reason": None,
            "mission_id": record.get("mission_id"),
            "detection_id": record.get("detection_id"),
            "capture_epoch": record.get("capture_epoch"),
            "frame_id": record.get("frame_id"),
            "capture_utc_ns": record.get("capture_utc_ns"),
            "latitude": None,
            "longitude": None,
            "local_offset_east_m": None,
            "local_offset_north_m": None,
            "distance_m": None,
            "bearing_deg": None,
            "pixel_center": None,
            "bbox_xyxy_normalized": None,
            "altitude_reference": None,
            "altitude_m": None,
            "rotation_order": self.config.rotation_order,
            "camera_attitude_frame": self.config.camera_attitude_frame,
            "ground_plane_assumption": "flat_z_plane",
            "calibration_validated": (
                self.calibration.validated if self.calibration is not None else False
            ),
        }

    @staticmethod
    def _unavailable(
        result: dict[str, Any], code: str, reason: str
    ) -> dict[str, Any]:
        result["status"] = NOT_AVAILABLE
        result["error_code"] = code
        result["reason"] = reason
        return result


def run_coordinate_reconstruction(
    synchronized_detections_path: str | Path,
    output_path: str | Path,
    calibration: CameraCalibration,
    *,
    config: CoordinateReconstructionConfig | None = None,
    altitude_reference: str | None = None,
    camera_attitude_frame: str | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Process synchronized detection JSONL without touching source artifacts."""

    source = Path(synchronized_detections_path)
    destination = Path(output_path)
    if not source.is_file():
        raise CoordinateReconstructionError(
            f"synchronized detections file does not exist: {source}"
        )
    if destination.exists() and not overwrite:
        raise CoordinateReconstructionError(
            f"refusing to overwrite coordinate output: {destination}"
        )
    records = _read_jsonl(source)
    adapter = CoordinateReconstructionAdapter(calibration, config=config)
    output_records = [
        adapter.reconstruct_record(
            record,
            altitude_reference=altitude_reference,
            camera_attitude_frame=camera_attitude_frame,
        )
        for record in records
    ]
    destination.parent.mkdir(parents=True, exist_ok=True)
    _write_jsonl(destination, output_records)
    counts: dict[str, int] = {}
    for record in output_records:
        status = record["coordinate"]["status"]
        counts[status] = counts.get(status, 0) + 1
    return {
        "ok": True,
        "detections": len(output_records),
        "status_counts": counts,
        "output_path": str(destination),
    }


def run_coordinate_reconstruction_from_artifacts(
    detections_path: str | Path,
    frames_path: str | Path,
    telemetry_path: str | Path,
    output_path: str | Path,
    calibration: CameraCalibration,
    *,
    expected_mission_id: str | None = None,
    config: CoordinateReconstructionConfig | None = None,
    altitude_reference: str | None = None,
    camera_attitude_frame: str | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Resolve frame/time/state with existing sync, then reconstruct offline."""

    with tempfile.TemporaryDirectory(prefix="buv-coordinate-sync-") as temp_dir:
        synchronized_path = Path(temp_dir) / "synchronized-detections.jsonl"
        sync_report = synchronize_detections(
            detections_path,
            frames_path,
            telemetry_path,
            synchronized_path,
            expected_mission_id=expected_mission_id,
            require_complete_state=True,
        )
        reconstruction_report = run_coordinate_reconstruction(
            synchronized_path,
            output_path,
            calibration,
            config=config,
            altitude_reference=altitude_reference,
            camera_attitude_frame=camera_attitude_frame,
            overwrite=overwrite,
        )
    return {
        "ok": True,
        "synchronization": sync_report,
        "reconstruction": reconstruction_report,
    }


def _normalized_bbox(
    record: Mapping[str, Any], calibration: CameraCalibration
) -> tuple[float, float, float, float]:
    value: Any = record.get("bbox_xyxy_normalized")
    if value is None:
        value = record.get("bbox")
        if isinstance(value, Mapping):
            value = value.get("xyxy_normalized", value.get("xyxy"))
    if value is None and record.get("bbox_xyxy") is not None:
        # The explicit pixel field is accepted only because its name makes the
        # unit unambiguous; the output remains canonical normalized XYXY.
        pixel = _four_numbers(record["bbox_xyxy"], "bbox_xyxy")
        value = (
            pixel[0] / calibration.image_width,
            pixel[1] / calibration.image_height,
            pixel[2] / calibration.image_width,
            pixel[3] / calibration.image_height,
        )
    normalized = _four_numbers(value, "bbox")
    if not all(0.0 <= coordinate <= 1.0 for coordinate in normalized):
        raise CoordinateReconstructionError("normalized bbox must be in [0, 1]")
    if normalized[2] <= normalized[0] or normalized[3] <= normalized[1]:
        raise CoordinateReconstructionError("bbox must have positive width and height")
    return normalized  # type: ignore[return-value]


def _four_numbers(value: Any, name: str) -> tuple[float, float, float, float]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise CoordinateReconstructionError(f"{name} must be a four-element array")
    if len(value) != 4:
        raise CoordinateReconstructionError(f"{name} must be a four-element array")
    numbers = tuple(float(item) for item in value)
    if not all(_is_finite_number(item) for item in numbers):
        raise CoordinateReconstructionError(f"{name} must contain finite numbers")
    return numbers  # type: ignore[return-value]


def _first_number(
    top: Mapping[str, Any], nested: Mapping[str, Any], *names: str
) -> float | None:
    for name in names:
        for source in (top, nested):
            value = source.get(name)
            if _is_finite_number(value):
                return float(value)
    return None


def _first_string(
    top: Mapping[str, Any], nested: Mapping[str, Any], *names: str
) -> str | None:
    for name in names:
        for source in (top, nested):
            value = source.get(name)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _invert_intrinsic_matrix(calibration: CameraCalibration) -> Matrix3:
    # The reference K is upper triangular.  Keeping this explicit also avoids
    # pulling NumPy into the telemetry-only backend.
    return (
        (1.0 / calibration.fx, 0.0, -calibration.cx / calibration.fx),
        (0.0, 1.0 / calibration.fy, -calibration.cy / calibration.fy),
        (0.0, 0.0, 1.0),
    )


def _matrix_multiply(left: Matrix3, right: Matrix3) -> Matrix3:
    return tuple(
        tuple(
            sum(left[row][index] * right[index][column] for index in range(3))
            for column in range(3)
        )
        for row in range(3)
    )  # type: ignore[return-value]


def _matrix_vector(matrix: Matrix3, vector: Vector3) -> Vector3:
    return tuple(
        sum(matrix[row][index] * vector[index] for index in range(3))
        for row in range(3)
    )  # type: ignore[return-value]


def _is_finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _required_finite_value(value: Any, name: str) -> float:
    if not _is_finite_number(value):
        raise CoordinateReconstructionError(f"{name} must be finite")
    return float(value)


def _required_positive_integer(value: Any, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise CoordinateReconstructionError(f"{name} must be a positive integer")
    return value


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise CoordinateReconstructionError(
                    f"invalid JSON at {path}:{line_number}"
                ) from exc
            if not isinstance(record, dict):
                raise CoordinateReconstructionError(
                    f"record at {path}:{line_number} is not an object"
                )
            records.append(record)
    return records


def _write_jsonl(path: Path, records: Iterable[Mapping[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("synchronized_detections_jsonl", type=Path)
    parser.add_argument("output_jsonl", type=Path)
    parser.add_argument("--calibration", required=True, type=Path)
    parser.add_argument(
        "--altitude-reference",
        choices=sorted(_ALTITUDE_REFERENCES),
        help="explicitly declare the altitude field semantics; only AGL can estimate",
    )
    parser.add_argument(
        "--attitude-frame",
        choices=sorted(_ATTITUDE_FRAMES),
        help="declare whether telemetry attitude is body or camera-world attitude",
    )
    parser.add_argument(
        "--rotation-order",
        choices=sorted(_ROTATION_ORDERS),
        default="XYZ",
    )
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        calibration = CameraCalibration.from_json(args.calibration)
        report = run_coordinate_reconstruction(
            args.synchronized_detections_jsonl,
            args.output_jsonl,
            calibration,
            config=CoordinateReconstructionConfig(
                rotation_order=args.rotation_order,
                camera_attitude_frame=args.attitude_frame or "body",
            ),
            altitude_reference=args.altitude_reference,
            camera_attitude_frame=args.attitude_frame,
            overwrite=args.overwrite,
        )
    except CoordinateReconstructionError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        return 1
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
