#!/usr/bin/env python3
"""Publish an always-on CSI/EasyCAP preview as H.264/RTP over UDP.

The recording agent and this service share ``preview_source_file``.  While a
recording pipeline is active, this service pauses so the recording pipeline is
the sole RTP sender.  Once recording finishes, the always-on preview resumes.
"""

from __future__ import annotations

import os
import signal
import time
from pathlib import Path

import gi

gi.require_version("Gst", "1.0")
gi.require_version("GLib", "2.0")
from gi.repository import GLib, Gst


def env_int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


class CameraStreamService:
    def __init__(self) -> None:
        self.target_host = os.getenv("JETSON_STREAM_TARGET_HOST", "100.114.81.87")
        self.target_port = env_int("JETSON_VIDEO_PORT", 5000)
        self.payload_type = env_int("JETSON_VIDEO_PAYLOAD_TYPE", 96)
        self.network_width = env_int("JETSON_NETWORK_WIDTH", 960)
        self.network_height = env_int("JETSON_NETWORK_HEIGHT", 540)
        self.network_fps = float(os.getenv("JETSON_NETWORK_FPS", "15"))
        self.network_bitrate = env_int("JETSON_NETWORK_BITRATE_KBPS", 2000)
        self.sensor_id = env_int("JETSON_SENSOR_ID", 0)
        self.easycap_device = os.getenv(
            "JETSON_EASYCAP_DEVICE",
            "/dev/v4l/by-id/usb-ARKMICRO_USB2.0_PC_CAMERA-video-index0",
        )
        self.easycap_width = env_int("JETSON_EASYCAP_WIDTH", 640)
        self.easycap_height = env_int("JETSON_EASYCAP_HEIGHT", 480)
        self.easycap_fps = float(os.getenv("JETSON_EASYCAP_FPS", "30"))
        self.preview_source_file = Path(
            os.getenv(
                "JETSON_PREVIEW_SOURCE_FILE",
                "/media/bengawan/nopal-ssd1/flight-recordings/.preview-source",
            )
        )
        self.recording_active_file = Path(
            os.getenv(
                "JETSON_RECORDING_ACTIVE_FILE",
                "/media/bengawan/nopal-ssd1/flight-recordings/.recording-agent.active.json",
            )
        )
        self.stop_requested = False
        self.pipeline = None
        self.loop = None
        self.selector = None
        self.active_source = None

    def source(self) -> str:
        try:
            value = self.preview_source_file.read_text(encoding="utf-8").strip().lower()
        except OSError:
            return "digital"
        if value == "analog" and Path(self.easycap_device).exists():
            return "analog"
        return "digital"

    def recording_active(self) -> bool:
        return self.recording_active_file.exists()

    def pipeline_description(self) -> str:
        fps_caps = f"{self.easycap_fps:g}/1"
        network_fps_caps = f"{self.network_fps:g}/1"
        return f"""
nvarguscamerasrc sensor-id={self.sensor_id} wbmode=1 !
video/x-raw(memory:NVMM),width=1920,height=1080,format=NV12,framerate=30/1 !
nvvidconv ! video/x-raw,format=I420,width={self.network_width},height={self.network_height} !
videorate ! video/x-raw,framerate={network_fps_caps} !
queue max-size-buffers=2 max-size-time=0 max-size-bytes=0 leaky=downstream ! selector.sink_0
v4l2src device="{self.easycap_device}" do-timestamp=true !
image/jpeg,width={self.easycap_width},height={self.easycap_height},framerate={fps_caps} !
jpegparse ! jpegdec ! videoconvert ! videoscale add-borders=true !
video/x-raw,format=I420,width={self.network_width},height={self.network_height} !
videorate ! video/x-raw,framerate={network_fps_caps} !
queue max-size-buffers=2 max-size-time=0 max-size-bytes=0 leaky=downstream ! selector.sink_1
input-selector name=selector sync-streams=true cache-buffers=true !
x264enc bitrate={self.network_bitrate} speed-preset=ultrafast tune=zerolatency
key-int-max=15 bframes=0 ! h264parse !
rtph264pay pt={self.payload_type} config-interval=1 mtu=1200 !
udpsink host={self.target_host} port={self.target_port} sync=false async=false
""".strip()

    def set_source(self, source: str) -> None:
        if not self.selector:
            return
        normalized = "analog" if source == "analog" else "digital"
        if normalized == "analog" and not Path(self.easycap_device).exists():
            normalized = "digital"
        if normalized == self.active_source:
            return
        pad_name = "sink_1" if normalized == "analog" else "sink_0"
        pad = self.selector.get_static_pad(pad_name)
        if pad is None:
            print(f"[camera-stream] selector pad missing: {pad_name}", flush=True)
            return
        self.selector.set_property("active-pad", pad)
        previous = self.active_source
        self.active_source = normalized
        print(f"[camera-stream] source changed: {previous} -> {normalized}", flush=True)

    def on_bus_message(self, _bus, message, loop) -> None:
        if message.type == Gst.MessageType.ERROR:
            error, debug = message.parse_error()
            print(f"[camera-stream] GStreamer error: {error}; {debug or ''}", flush=True)
            loop.quit()
        elif message.type == Gst.MessageType.EOS:
            loop.quit()

    def poll_state(self) -> bool:
        if self.stop_requested or self.recording_active():
            if self.loop:
                self.loop.quit()
            return False
        self.set_source(self.source())
        return True

    def run_pipeline(self) -> None:
        self.pipeline = Gst.parse_launch(self.pipeline_description())
        self.selector = self.pipeline.get_by_name("selector")
        if self.selector is None:
            raise RuntimeError("camera pipeline did not create input-selector")
        self.active_source = None
        self.set_source(self.source())
        self.loop = GLib.MainLoop()
        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self.on_bus_message, self.loop)
        GLib.timeout_add(250, self.poll_state)
        self.pipeline.set_state(Gst.State.PLAYING)
        self.loop.run()
        self.pipeline.set_state(Gst.State.NULL)
        self.pipeline = None
        self.selector = None
        self.loop = None
        self.active_source = None

    def run(self) -> int:
        Gst.init(None)
        print(
            f"[camera-stream] target={self.target_host}:{self.target_port}; "
            f"source-file={self.preview_source_file}",
            flush=True,
        )
        while not self.stop_requested:
            if self.recording_active():
                time.sleep(0.5)
                continue
            try:
                self.run_pipeline()
            except Exception as exc:
                print(f"[camera-stream] pipeline failed: {exc}", flush=True)
                if not self.stop_requested:
                    time.sleep(2)
        return 0

    def stop(self, *_args) -> None:
        self.stop_requested = True
        if self.loop and self.loop.is_running():
            self.loop.quit()


def main() -> int:
    service = CameraStreamService()
    signal.signal(signal.SIGINT, service.stop)
    signal.signal(signal.SIGTERM, service.stop)
    return service.run()


if __name__ == "__main__":
    raise SystemExit(main())
