"""
MavlinkUdpAdapter – MAVLink Middleware Service menggunakan pymavlink.

Arsitektur Middleware (Decoupled):
┌─────────────────────────────────────────────────────────────────────┐
│  Mission Planner (MAVLink Mirror)                                   │
│       │ UDP forward ke udp:0.0.0.0:14551                            │
│       ▼                                                             │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  MAVLink Worker Thread  (_worker_loop)                       │   │
│  │  • mavutil.mavlink_connection() – pymavlink                  │   │
│  │  • recv_match() per-pesan MAVLink yang masuk                 │   │
│  │  • Parse & normalisasi nilai ke skema internal               │   │
│  │  • _state_lock.acquire()  → tulis ke _telemetry_state        │   │
│  └────────────────────────┬─────────────────────────────────────┘   │
│                           │ RLock (thread-safe write)               │
│                           ▼                                         │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  In-Memory Cache  (_telemetry_state, _messages_cache)        │   │
│  │  • Satu dict Python yang selalu up-to-date                   │   │
│  │  • Diupdate hanya oleh Worker Thread                         │   │
│  └────────────────────────┬─────────────────────────────────────┘   │
│                           │ RLock (thread-safe read)                │
│                           ▼                                         │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  Public API (snapshot / health / messages / mission)         │   │
│  │  • Dipanggil oleh Flask route handlers                       │   │
│  │  • Hanya membaca dari cache, tidak pernah ke MAVLink         │   │
│  └──────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘

Variabel-variabel kunci di _telemetry_state menggunakan penamaan yang
sama persis dengan MissionPlannerAdapter sehingga seluruh Flask route,
FlightRecorder, dan CoordinateEstimator tidak perlu diubah.

Konfigurasi (env vars atau constructor args):
    MAVLINK_UDP_HOST   – bind address  (default "0.0.0.0")
    MAVLINK_UDP_PORT   – UDP port      (default 14551)

Semua metode write/command sengaja dinonaktifkan (read-only adapter).
"""

from __future__ import annotations

import math
import os
import threading
import time
from collections import deque
from copy import deepcopy
from typing import Optional

try:
    from pymavlink import mavutil
    _PYMAVLINK_AVAILABLE = True
except ImportError:  # pragma: no cover
    _PYMAVLINK_AVAILABLE = False
    mavutil = None  # type: ignore[assignment]

from .telemetry_recorder import TelemetryRecorder


# ---------------------------------------------------------------------------
# Konstanta flight mode ArduPilot (digunakan untuk resolve custom_mode)
# ---------------------------------------------------------------------------

_ARDUPILOT_PLANE_MODES: dict[int, str] = {
    0: "MANUAL",       1: "CIRCLE",      2: "STABILIZE",    3: "TRAINING",
    4: "ACRO",         5: "FBWA",        6: "FBWB",         7: "CRUISE",
    8: "AUTOTUNE",     10: "AUTO",       11: "RTL",         12: "LOITER",
    13: "TAKEOFF",     14: "AVOID_ADSB", 15: "GUIDED",      17: "QSTABILIZE",
    18: "QHOVER",      19: "QLOITER",    20: "QLAND",       21: "QRTL",
    22: "QAUTOTUNE",   23: "QACRO",      24: "THERMAL",     25: "LOITER_ALT_QLAND",
}

_ARDUPILOT_COPTER_MODES: dict[int, str] = {
    0: "STABILIZE",    1: "ACRO",        2: "ALT_HOLD",     3: "AUTO",
    4: "GUIDED",       5: "LOITER",      6: "RTL",          7: "CIRCLE",
    9: "LAND",         11: "DRIFT",      13: "SPORT",       14: "FLIP",
    15: "AUTOTUNE",    16: "POSHOLD",    17: "BRAKE",       18: "THROW",
    19: "AVOID_ADSB",  20: "GUIDED_NOGPS", 21: "SMART_RTL", 22: "FLOWHOLD",
    23: "FOLLOW",      24: "ZIGZAG",
}

# MAV_TYPE – kelompok fixed-wing / VTOL → pakai tabel Plane
_PLANE_MAV_TYPES: frozenset[int] = frozenset({1, 11, 12, 13, 14, 19, 20, 21, 22})

# MAV_STATE – kendaraan aktif / kritis → dianggap connected
_MAV_STATE_ACTIVE   = 4
_MAV_STATE_CRITICAL = 5

# Base mode flag – armed
_MAV_MODE_FLAG_SAFETY_ARMED = 0x80

# EKF_STATUS_REPORT flags – semua posisi/velocity check lulus
_EKF_HEALTHY_MASK = 0x1F

# STATUSTEXT severity labels (untuk logging)
_STATUSTEXT_SEVERITY: dict[int, str] = {
    0: "EMERGENCY", 1: "ALERT", 2: "CRITICAL", 3: "ERROR",
    4: "WARNING",   5: "NOTICE", 6: "INFO",    7: "DEBUG",
}

# Pesan yang "berisik" dan akan di-suppress dari log terminal
_QUIET_MSG_TYPES: frozenset[str] = frozenset({
    "HEARTBEAT", "ATTITUDE", "VFR_HUD", "GLOBAL_POSITION_INT",
    "GPS_RAW_INT", "GPS2_RAW", "RAW_IMU", "SCALED_IMU2",
    "SCALED_IMU3", "SERVO_OUTPUT_RAW", "RC_CHANNELS",
    "RC_CHANNELS_RAW", "AHRS", "AHRS2", "AHRS3",
    "SENSOR_OFFSETS", "SYSTEM_TIME", "MEMINFO",
    "TERRAIN_REPORT", "LOCAL_POSITION_NED",
    "NAV_CONTROLLER_OUTPUT", "WIND",
})

# ---------------------------------------------------------------------------
# Skema telemetry state (nama variabel identik dg MissionPlannerAdapter)
# ---------------------------------------------------------------------------

def _empty_telemetry_state() -> dict:
    """
    In-memory state yang diisi oleh MAVLink Worker Thread.

    Penamaan kunci **identik** dengan output _normalize() di
    mission_planner_adapter.py sehingga semua consumer (FlightRecorder,
    CoordinateEstimator, dll.) tidak perlu diubah.
    """
    return {
        # ── Koneksi & status ──────────────────────────────────────────────
        "connected":              False,
        "status":                 "BRIDGE_OFFLINE",
        "state_valid":            False,

        # ── Posisi GPS ────────────────────────────────────────────────────
        "lat":                    None,   # derajat (float)
        "lng":                    None,   # derajat (float)
        "alt":                    None,   # meter relatif terhadap home (float)
        "alt_amsl":               None,   # meter AMSL (float)

        # ── Kendaraan ─────────────────────────────────────────────────────
        "armed":                  None,   # bool
        "flight_mode":            None,   # str e.g. "FBWA"

        # ── Baterai ───────────────────────────────────────────────────────
        "battery_percent":        None,   # 0–100 (int/float)
        "battery_voltage_v":      None,   # volt (float)
        "battery_current_a":      None,   # ampere (float)

        # ── Attitude ──────────────────────────────────────────────────────
        "roll_deg":               None,   # derajat (float)
        "pitch_deg":              None,   # derajat (float)
        "yaw_deg":                None,   # derajat (float)
        "heading_deg":            None,   # 0–360 (float)

        # ── Kecepatan ─────────────────────────────────────────────────────
        "airspeed_m_s":           None,   # m/s (float)
        "groundspeed_m_s":        None,   # m/s (float)
        "v_speed_m_s":            None,   # m/s, positif = naik (float)

        # ── GPS detail ────────────────────────────────────────────────────
        "gps_status":             None,   # fix type 0–6 (int)
        "gps_hdop":               None,   # HDOP (float)
        "satellites":             None,   # jumlah satelit (int)

        # ── Status terbang ────────────────────────────────────────────────
        "dist_to_home_m":         None,   # meter (float)
        "time_in_air_s":          None,   # detik (float)
        "time_since_boot_s":      None,   # detik sejak boot (float)

        # ── EKF ───────────────────────────────────────────────────────────
        "ekf_ok":                 None,   # bool
        "ekf_flags":              None,   # bitmask raw (int)
        "ekf_velocity_variance":  None,   # float
        "ekf_pos_variance":       None,   # float
        "ekf_compass_variance":   None,   # float

        # ── Vibrasi ───────────────────────────────────────────────────────
        "vibration_x":            None,   # float
        "vibration_y":            None,   # float
        "vibration_z":            None,   # float

        # ── Meta ──────────────────────────────────────────────────────────
        "last_update":            None,   # unix timestamp (float)
        "error":                  None,   # pesan error terakhir (str | None)
        "source":                 "mavlink-udp",
    }


# ---------------------------------------------------------------------------
# Adapter utama
# ---------------------------------------------------------------------------

class MavlinkUdpAdapter:
    """
    MAVLink Middleware Adapter – read-only, pymavlink-based.

    Menyediakan API yang identik dengan MissionPlannerAdapter lama sehingga
    seluruh Flask routes (api_v1.py) dan service lain tidak perlu diubah.

    Pola penggunaan::

        adapter = MavlinkUdpAdapter()
        adapter.start()              # jalankan MAVLink Worker Thread
        ...
        snap = adapter.snapshot()    # Flask route membaca dari cache
        h    = adapter.health()
        msgs = adapter.messages()
    """

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        stale_after_seconds: float = 3.0,
        reconnect_delay_seconds: float = 2.0,
        recv_timeout_seconds:  float = 1.0,
    ) -> None:
        self.host    = host or os.getenv("MAVLINK_UDP_HOST", "0.0.0.0")
        self.port    = port or int(os.getenv("MAVLINK_UDP_PORT", "14551"))
        self.stale_after_seconds      = stale_after_seconds
        self.reconnect_delay_seconds  = reconnect_delay_seconds
        self.recv_timeout_seconds     = recv_timeout_seconds

        # Dipakai oleh startup banner & health endpoint (kompatibel dg lama)
        self.base_url = f"udp://{self.host}:{self.port}"

        # ── In-memory telemetry cache (ditulis Worker, dibaca HTTP layer) ──
        self._state_lock   = threading.RLock()
        self._telemetry_state: dict = _empty_telemetry_state()
        self._version:     int  = 0
        self._last_success_at: Optional[float] = None
        self._worker_error: Optional[str] = None

        # ── In-memory messages cache (STATUSTEXT) ─────────────────────────
        self._messages_lock  = threading.RLock()
        self._messages_cache: deque[dict] = deque(maxlen=80)

        # ── Telemetry recorder (JSONL + ring-buffer untuk CoordinateEstimator)
        self.telemetry_recorder = TelemetryRecorder()

        # ── Background worker thread ───────────────────────────────────────
        self._worker_thread: Optional[threading.Thread] = None

        # ── Internal state yang di-track lintas pesan ─────────────────────
        self._mav_type: Optional[int] = None   # dari HEARTBEAT

    # =======================================================================
    # PUBLIC API  (identik dengan MissionPlannerAdapter – tidak boleh diubah)
    # =======================================================================

    def start(self) -> None:
        """Jalankan MAVLink Worker Thread (background, daemon)."""
        if self._worker_thread and self._worker_thread.is_alive():
            return
        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            daemon=True,
            name="mavlink-udp-worker",
        )
        self._worker_thread.start()

    def snapshot(self) -> dict:
        """
        Baca snapshot telemetry dari in-memory cache (thread-safe).

        HTTP layer **hanya boleh** memanggil metode ini, tidak boleh
        mengakses _telemetry_state secara langsung.
        """
        with self._state_lock:
            now   = time.time()
            state = deepcopy(self._telemetry_state)
            last_success_at  = self._last_success_at
            worker_error     = self._worker_error
            version          = self._version

        stale = (
            last_success_at is None
            or (now - last_success_at) > self.stale_after_seconds
        )
        worker_online = worker_error is None and last_success_at is not None

        # Terapkan status staleness ke salinan state
        if stale:
            state["status"] = "STALE" if worker_online else "BRIDGE_OFFLINE"
            state["error"]  = worker_error or "MAVLink UDP telemetry is stale"

        # Validasi posisi GPS
        lat        = state.get("lat")
        lng        = state.get("lng")
        gps_status = state.get("gps_status")
        gps_valid  = (
            not stale
            and lat is not None
            and lng is not None
            and not (float(lat) == 0.0 and float(lng) == 0.0)
            and (gps_status is None or int(gps_status) >= 3)
        )

        return {
            "ok":        True,
            "timestamp": now,
            "version":   version,
            "stale":     stale,
            "gps_valid": gps_valid,
            "bridge": {
                "online":          worker_online,
                "url":             self.base_url,
                "last_poll_at":    last_success_at,
                "last_success_at": last_success_at,
                "error":           worker_error,
            },
            "telemetry": state,
        }

    def health(self) -> dict:
        """Return health/status kompatibel dengan MissionPlannerAdapter."""
        s = self.snapshot()
        t = s["telemetry"]
        return {
            "ok":          True,
            "timestamp":   s["timestamp"],
            "status":      t["status"],
            "connected":   bool(t["connected"]) and not s["stale"],
            "stale":       s["stale"],
            "gps_valid":   s["gps_valid"],
            "last_update": t["last_update"],
            "error":       t["error"],
            "source":      "mavlink-udp-adapter",
            "bridge":      s["bridge"],
        }

    def mission(self) -> dict:
        """
        Data misi tidak tersedia via UDP mirror (read-only).

        Mengembalikan payload kosong yang valid secara schema agar
        endpoint /api/v1/mission tetap bisa merespons.
        """
        return {
            "ok":               True,
            "timestamp":        time.time(),
            "source":           "mavlink-udp (mission data not available)",
            "count":            0,
            "positioned_count": 0,
            "current_seq":      None,
            "current_waypoint": None,
            "waypoints":        [],
        }

    def messages(self) -> dict:
        """Return recent STATUSTEXT messages dari in-memory cache."""
        with self._messages_lock:
            msgs = list(self._messages_cache)
        return {
            "ok":              True,
            "timestamp":       time.time(),
            "source":          "mavlink-udp",
            "count":           len(msgs),
            "messages":        msgs,
            "sources_checked": [f"udp:{self.port}"],
        }

    def send_command(self, command: str, payload: dict) -> tuple[dict, int]:  # noqa: ARG002
        """
        Perintah dinonaktifkan – adapter ini read-only.

        Semua endpoint POST command sudah di-comment di api_v1.py.
        Metode ini sengaja dipertahankan agar tipe-hint kompatibel.
        """
        raise NotImplementedError(
            f"MavlinkUdpAdapter bersifat read-only; "
            f"command '{command}' tidak didukung. "
            "Gunakan Mission Planner atau channel MAVLink yang terpisah."
        )

    # =======================================================================
    # MAVLINK WORKER THREAD  (background – satu-satunya yang menulis ke cache)
    # =======================================================================

    def _worker_loop(self) -> None:
        """
        MAVLink Worker Thread – loop utama.

        Terhubung ke UDP socket via pymavlink, menerima pesan satu per satu
        lewat recv_match(), lalu mendispatch ke handler masing-masing yang
        memperbarui in-memory cache (_telemetry_state).

        Saat koneksi putus / error, thread tidur sebentar lalu mencoba
        tersambung kembali secara otomatis.
        """
        if not _PYMAVLINK_AVAILABLE:
            msg = "pymavlink tidak terinstall. Jalankan: pip install pymavlink"
            print(f"[mavlink-worker] FATAL: {msg}", flush=True)
            with self._state_lock:
                self._worker_error = msg
            return

        conn_str = f"udpin:{self.host}:{self.port}"
        print(f"[mavlink-worker] Memulai listener pada {conn_str}", flush=True)

        while True:
            conn = None
            try:
                # ── Buat koneksi pymavlink ─────────────────────────────────
                conn = mavutil.mavlink_connection(
                    conn_str,
                    source_system=255,   # GCS sysid
                    source_component=0,
                    input=True,
                    dialect="ardupilotmega",
                )
                print(f"[mavlink-worker] Socket terbuka – menunggu paket MAVLink…", flush=True)

                with self._state_lock:
                    self._worker_error = f"Menunggu paket MAVLink pada {conn_str}…"

                # ── Receive loop ───────────────────────────────────────────
                while True:
                    msg = conn.recv_match(
                        type=None,               # terima semua tipe pesan
                        blocking=True,
                        timeout=self.recv_timeout_seconds,
                    )
                    if msg is None:
                        # timeout – tidak ada paket masuk, cek staleness
                        with self._state_lock:
                            if self._last_success_at is None:
                                self._worker_error = (
                                    f"Belum ada paket MAVLink pada {conn_str}…"
                                )
                        continue

                    msg_type = msg.get_type()
                    if msg_type == "BAD_DATA":
                        continue

                    # ── Dispatch ke handler yang sesuai ───────────────────
                    self._dispatch(msg_type, msg)

                    # ── Rekam telemetri ke TelemetryRecorder ──────────────
                    snapshot_for_recorder = None
                    with self._state_lock:
                        if self._telemetry_state.get("connected"):
                            snapshot_for_recorder = deepcopy(self._telemetry_state)
                    if snapshot_for_recorder is not None:
                        self.telemetry_recorder.record(
                            snapshot_for_recorder, now=time.time()
                        )

            except Exception as exc:
                err_msg = f"Worker error: {exc}"
                print(f"[mavlink-worker] {err_msg}", flush=True)
                with self._state_lock:
                    self._worker_error = err_msg
            finally:
                if conn is not None:
                    try:
                        conn.close()
                    except Exception:
                        pass

            print(
                f"[mavlink-worker] Reconnect dalam {self.reconnect_delay_seconds}s…",
                flush=True,
            )
            time.sleep(self.reconnect_delay_seconds)

    # =======================================================================
    # MESSAGE HANDLERS  (dipanggil dari Worker Thread, menulis ke _state_lock)
    # =======================================================================

    def _dispatch(self, msg_type: str, msg) -> None:
        """Route pesan MAVLink ke handler yang sesuai."""
        handler = self._MSG_HANDLERS.get(msg_type)
        if handler is None:
            return
        try:
            handler(self, msg)
        except Exception as exc:
            # Jangan crash worker karena satu pesan rusak
            print(f"[mavlink-worker] Error parse {msg_type}: {exc}", flush=True)

    def _handle_heartbeat(self, msg) -> None:
        """
        HEARTBEAT (MSG ID 0) – sumber utama armed, flight_mode, connected.

        Diproses setiap ~1 Hz dari FC.
        """
        mav_type      = int(msg.type)
        base_mode     = int(msg.base_mode)
        custom_mode   = int(msg.custom_mode)
        system_status = int(msg.system_status)

        self._mav_type = mav_type
        armed          = bool(base_mode & _MAV_MODE_FLAG_SAFETY_ARMED)
        connected      = system_status in (_MAV_STATE_ACTIVE, _MAV_STATE_CRITICAL)
        flight_mode    = self._resolve_flight_mode(mav_type, custom_mode)

        with self._state_lock:
            self._telemetry_state["armed"]       = armed
            self._telemetry_state["flight_mode"] = flight_mode
            self._telemetry_state["connected"]   = connected
            self._telemetry_state["state_valid"] = True
            self._telemetry_state["status"]      = (
                "RUNNING" if connected else "VEHICLE_DISCONNECTED"
            )
            self._telemetry_state["source"]      = "mavlink-udp"
            self._bump_cache_version()

    def _handle_sys_status(self, msg) -> None:
        """
        SYS_STATUS (MSG ID 1) – baterai (fallback jika BATTERY_STATUS absen).
        """
        voltage_mv  = int(msg.voltage_battery)        # mV
        current_ca  = int(msg.current_battery)        # 10 mA, -1 = unknown
        battery_pct = int(msg.battery_remaining)      # %, -1 = unknown

        with self._state_lock:
            if voltage_mv > 0:
                self._telemetry_state["battery_voltage_v"] = round(voltage_mv / 1000.0, 3)
            if current_ca >= 0:
                self._telemetry_state["battery_current_a"] = round(current_ca / 100.0, 3)
            if battery_pct >= 0:
                self._telemetry_state["battery_percent"] = battery_pct
            self._bump_cache_version()

    def _handle_gps_raw_int(self, msg) -> None:
        """
        GPS_RAW_INT (MSG ID 24) – posisi GPS, fix type, HDOP, sats.

        Nilai lat/lng dalam degE7 (int), dikonversi ke derajat float.
        """
        lat_degE7 = int(msg.lat)
        lon_degE7 = int(msg.lon)
        fix_type  = int(msg.fix_type)
        sats      = int(msg.satellites_visible)
        eph       = int(msg.eph)  # HDOP * 100, 65535 = unknown

        lat  = lat_degE7 / 1e7 if lat_degE7 != 0 else None
        lng  = lon_degE7 / 1e7 if lon_degE7 != 0 else None
        hdop = round(eph / 100.0, 2) if eph < 0xFFFF else None

        with self._state_lock:
            self._telemetry_state["lat"]        = lat
            self._telemetry_state["lng"]        = lng
            self._telemetry_state["gps_status"] = fix_type
            self._telemetry_state["gps_hdop"]   = hdop
            self._telemetry_state["satellites"] = sats if sats < 255 else None
            self._bump_cache_version()

    def _handle_attitude(self, msg) -> None:
        """
        ATTITUDE (MSG ID 30) – roll/pitch/yaw dalam radian, dikonversi ke derajat.
        """
        roll_deg  = round(math.degrees(float(msg.roll)),  3)
        pitch_deg = round(math.degrees(float(msg.pitch)), 3)
        yaw_deg   = round(math.degrees(float(msg.yaw)),   3)
        heading   = round(yaw_deg % 360, 3)
        t_boot_s  = int(msg.time_boot_ms) / 1000.0

        with self._state_lock:
            self._telemetry_state["roll_deg"]          = roll_deg
            self._telemetry_state["pitch_deg"]         = pitch_deg
            self._telemetry_state["yaw_deg"]           = yaw_deg
            self._telemetry_state["heading_deg"]       = heading
            self._telemetry_state["time_since_boot_s"] = round(t_boot_s, 3)
            self._bump_cache_version()

    def _handle_global_position_int(self, msg) -> None:
        """
        GLOBAL_POSITION_INT (MSG ID 33) – lat/lng/alt dan heading kompass.

        Lat/lng dalam degE7, alt dalam mm.  Ini sumber posisi primer untuk
        CoordinateEstimator karena juga membawa relative altitude (AGL).
        """
        lat_degE7   = int(msg.lat)
        lon_degE7   = int(msg.lon)
        alt_mm      = int(msg.alt)          # AMSL, mm
        rel_alt_mm  = int(msg.relative_alt) # relatif home, mm
        hdg_cdeg    = int(msg.hdg)          # heading 0–35999 cdeg, 65535=unknown

        lat      = lat_degE7 / 1e7  if lat_degE7 != 0 else None
        lng      = lon_degE7 / 1e7  if lon_degE7 != 0 else None
        alt_amsl = round(alt_mm / 1000.0, 3)   if alt_mm != 0 else None
        alt_rel  = round(rel_alt_mm / 1000.0, 3)
        heading  = round(hdg_cdeg / 100.0, 1)  if hdg_cdeg < 36000 else None

        t_boot_s = int(msg.time_boot_ms) / 1000.0

        with self._state_lock:
            # lat/lng dari GLOBAL_POSITION_INT dipakai sebagai override
            # (lebih sering update daripada GPS_RAW_INT di sebagian FC)
            if lat is not None:
                self._telemetry_state["lat"]      = lat
            if lng is not None:
                self._telemetry_state["lng"]      = lng
            self._telemetry_state["alt"]          = alt_rel
            self._telemetry_state["alt_amsl"]     = alt_amsl
            if heading is not None:
                self._telemetry_state["heading_deg"] = heading
            self._telemetry_state["time_since_boot_s"] = round(t_boot_s, 3)
            self._bump_cache_version()

    def _handle_vfr_hud(self, msg) -> None:
        """
        VFR_HUD (MSG ID 74) – airspeed, groundspeed, climb rate.
        """
        airspeed    = round(float(msg.airspeed), 3)
        groundspeed = round(float(msg.groundspeed), 3)
        climb       = round(float(msg.climb), 3)
        heading     = int(msg.heading)    # derajat integer 0–359

        with self._state_lock:
            self._telemetry_state["airspeed_m_s"]   = airspeed
            self._telemetry_state["groundspeed_m_s"] = groundspeed
            self._telemetry_state["v_speed_m_s"]    = climb
            if 0 <= heading < 360:
                self._telemetry_state["heading_deg"] = float(heading)
            self._bump_cache_version()

    def _handle_battery_status(self, msg) -> None:
        """
        BATTERY_STATUS (MSG ID 147) – lebih akurat dari SYS_STATUS untuk
        setup multi-sel karena melaporkan voltase per-sel.
        """
        # voltages adalah array uint16[10], sentinel = 65535
        voltages_mv = [
            v for v in (msg.voltages or [])
            if isinstance(v, int) and v < 0xFFFF
        ]
        total_mv    = sum(voltages_mv) if voltages_mv else None
        current_ca  = int(msg.current_battery)   # 10 mA, -1 unknown
        battery_pct = int(msg.battery_remaining)  # %, -1 unknown

        with self._state_lock:
            if total_mv is not None:
                self._telemetry_state["battery_voltage_v"] = round(total_mv / 1000.0, 3)
            if current_ca >= 0:
                self._telemetry_state["battery_current_a"] = round(current_ca / 100.0, 3)
            if battery_pct >= 0:
                self._telemetry_state["battery_percent"] = battery_pct
            self._bump_cache_version()

    def _handle_statustext(self, msg) -> None:
        """
        STATUSTEXT (MSG ID 253) – pesan teks dari FC (peringatan, info, dsb).

        Disimpan ke _messages_cache, tidak ke _telemetry_state.
        """
        severity = int(msg.severity)
        text     = str(msg.text).rstrip("\x00").strip()
        if not text:
            return
        entry = {
            "timestamp": time.time(),
            "message":   text,
            "severity":  _STATUSTEXT_SEVERITY.get(severity, str(severity)),
            "source":    f"udp:{self.port}",
        }
        with self._messages_lock:
            self._messages_cache.append(entry)
        print(
            f"[mavlink-worker] STATUSTEXT [{entry['severity']}] {text}",
            flush=True,
        )

    def _handle_ekf_status_report(self, msg) -> None:
        """
        EKF_STATUS_REPORT (MSG ID 193, ArduPilot-specific).

        Flags bitmask:
          Bit 0 = velocity check passed
          Bit 1 = position horiz check passed
          Bit 2 = position vert check passed
          Bit 3 = const pos check passed (disarmed)
          Bit 4 = terrain alt check passed
        """
        flags     = int(msg.flags)
        ekf_ok    = bool(flags & _EKF_HEALTHY_MASK)
        vel_var   = round(float(msg.velocity_variance),      4)
        pos_h_var = round(float(msg.pos_horiz_variance),     4)
        comp_var  = round(float(msg.compass_variance),       4)

        with self._state_lock:
            self._telemetry_state["ekf_ok"]               = ekf_ok
            self._telemetry_state["ekf_flags"]            = flags
            self._telemetry_state["ekf_velocity_variance"]= vel_var
            self._telemetry_state["ekf_pos_variance"]     = pos_h_var
            self._telemetry_state["ekf_compass_variance"] = comp_var
            self._bump_cache_version()

    def _handle_vibration(self, msg) -> None:
        """VIBRATION (MSG ID 241)."""
        with self._state_lock:
            self._telemetry_state["vibration_x"] = round(float(msg.vibration_x), 4)
            self._telemetry_state["vibration_y"] = round(float(msg.vibration_y), 4)
            self._telemetry_state["vibration_z"] = round(float(msg.vibration_z), 4)
            self._bump_cache_version()

    def _handle_nav_controller_output(self, msg) -> None:
        """
        NAV_CONTROLLER_OUTPUT (MSG ID 62) – wp_dist sebagai dist_to_home_m
        ketika kendaraan tidak terbang dalam mode yang mengembalikan
        distToHome secara langsung.
        """
        wp_dist = float(msg.wp_dist)
        with self._state_lock:
            self._telemetry_state["dist_to_home_m"] = round(wp_dist, 2)
            self._bump_cache_version()

    # -----------------------------------------------------------------------
    # Dispatch table  (msg_type string → handler)
    # -----------------------------------------------------------------------

    _MSG_HANDLERS: dict = {}  # diisi di bawah setelah definisi class

    # =======================================================================
    # INTERNAL HELPERS
    # =======================================================================

    def _resolve_flight_mode(self, mav_type: int, custom_mode: int) -> str:
        """Konversi custom_mode integer ke nama mode string ArduPilot."""
        if mav_type in _PLANE_MAV_TYPES:
            return _ARDUPILOT_PLANE_MODES.get(custom_mode, f"MODE_{custom_mode}")
        return _ARDUPILOT_COPTER_MODES.get(custom_mode, f"MODE_{custom_mode}")

    def _bump_cache_version(self) -> None:
        """
        Perbarui metadata cache.

        **Harus dipanggil saat sudah memegang self._state_lock.**
        Setiap kali handler menulis ke _telemetry_state, version dinaikkan
        dan last_success_at di-reset agar staleness check bekerja dengan benar.
        """
        now = time.time()
        self._last_success_at                    = now
        self._worker_error                       = None
        self._telemetry_state["last_update"]     = now
        self._telemetry_state["error"]           = None
        self._version                           += 1


# ---------------------------------------------------------------------------
# Pasang dispatch table setelah class terdefinisi
# (tidak bisa inline karena referensi ke metode instance)
# ---------------------------------------------------------------------------

MavlinkUdpAdapter._MSG_HANDLERS = {
    "HEARTBEAT":              MavlinkUdpAdapter._handle_heartbeat,
    "SYS_STATUS":             MavlinkUdpAdapter._handle_sys_status,
    "GPS_RAW_INT":            MavlinkUdpAdapter._handle_gps_raw_int,
    "ATTITUDE":               MavlinkUdpAdapter._handle_attitude,
    "GLOBAL_POSITION_INT":    MavlinkUdpAdapter._handle_global_position_int,
    "VFR_HUD":                MavlinkUdpAdapter._handle_vfr_hud,
    "BATTERY_STATUS":         MavlinkUdpAdapter._handle_battery_status,
    "STATUSTEXT":             MavlinkUdpAdapter._handle_statustext,
    "EKF_STATUS_REPORT":      MavlinkUdpAdapter._handle_ekf_status_report,
    "VIBRATION":              MavlinkUdpAdapter._handle_vibration,
    "NAV_CONTROLLER_OUTPUT":  MavlinkUdpAdapter._handle_nav_controller_output,
}
