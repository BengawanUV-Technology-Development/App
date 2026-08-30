# MAVLink router setup

Untuk baseline redevelopment, lihat [R0_ARCHITECTURE_BASELINE.md](./R0_ARCHITECTURE_BASELINE.md).
Panduan ini menjelaskan setup runtime yang tersedia saat ini; ia tidak berarti
seluruh mission, frame metadata, UTC Global, atau hardware verification Mission
Planner/QGroundControl R0 sudah selesai.

This repository uses a small `pymavlink` router instead of exposing the
Pixhawk serial device directly to the web backend. Mission Planner fan-out is
optional and must use a separate UDP destination.

```
Pixhawk serial
      │
      ▼
scripts/mavlink_readonly_router.py
      ├── UDP 14550 ──► QGroundControl (telemetry + commands)
      ├── UDP 14552 ──► Mission Planner (optional telemetry + commands)
      └── UDP 14551 ──► web backend (receive-only telemetry)
```

The router script is intentionally not the stock `mavproxy.py` process. It is
a restricted MAVLink fan-out designed for this application: the QGC path can
write back to the flight controller, while the web path can only receive
telemetry.

## Windows PowerShell

### 1. Install prerequisites

Install:

- Python 3.10 or newer
- QGroundControl
- Pixhawk USB driver

Connect the Pixhawk and open **Device Manager → Ports (COM & LPT)**. Note the
serial port, for example `COM5`.

Open PowerShell in the repository directory. If script execution is blocked,
allow scripts for this terminal only:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

### 2. Create the Python environment

```powershell
.\scripts\setup_mavlink_windows.ps1
```

This creates `.venv` and installs the backend dependencies, including
`pymavlink`.

### 3. Start the router

Use a separate PowerShell window:

```powershell
.\scripts\start_mavlink_router.ps1 -SerialPort COM5 -Baud 57600
```

The default routes are:

- QGroundControl: `127.0.0.1:14550`
- Mission Planner: optional, for example `127.0.0.1:14552`
- Web backend: `127.0.0.1:14551`

To enable Mission Planner in the same router process, pass
`-MissionPlannerAddress 127.0.0.1:14552` to the PowerShell launcher or set
`MAVLINK_MISSION_PLANNER_ADDRESS=127.0.0.1:14552` before starting the router.

### 4. Start the web backend

Use another PowerShell window:

```powershell
.\scripts\start_readonly_backend.ps1
```

The backend HTTP API is available at `http://127.0.0.1:5001`.

### 5. Configure QGroundControl

Add a UDP link using port `14550`. Do not add the Pixhawk serial port directly
to QGroundControl; the router must be the only process opening the serial
device.

The webapp is telemetry-only. Arm, disarm, flight mode, mission, parameter,
reboot, and other flight commands remain available only through QGroundControl.

### 6. Monitor the web input

Optional, in a third PowerShell window:

```powershell
.\.venv\Scripts\python.exe .\scripts\monitor_mavlink_udp.py --port 14551
```

## macOS and Linux

Create the environment and install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r src-tauri/src-py/requirements.txt
```

Start the router:

```bash
python scripts/mavlink_readonly_router.py \
  --serial /dev/cu.usbserial-DU0E7WRJ \
  --baud 57600
```

Start the backend in another terminal:

```bash
./src-tauri/src-py/start_readonly_backend.sh
```

Monitor UDP `14551` if needed:

```bash
python scripts/monitor_mavlink_udp.py --port 14551
```

## Live camera preview

The camera preview is receive-only, like the telemetry path. The current Jetson
service can select a low-resolution CSI/Arducam or EasyCAP branch, encode it as
H.264/RTP/UDP, and send it to the backend. The backend decodes it with
GStreamer and exposes an MJPEG preview at `/api/v1/camera/preview`. The website
starts requesting this endpoint when the Live camera panel is opened.

The R0 mission/frame metadata contract is intentionally not carried by this
low-resolution preview pipeline. The deployed high-resolution recording agent
assigns frame identity at the source callback and writes epoch-scoped
`frames.jsonl`; `jetson/frame_metadata.py` validates that artifact. See
[`SHORT_FLIGHT_TEST.md`](./SHORT_FLIGHT_TEST.md). Jetson source, systemd units,
machine-only env files, and deployment commands are documented in
[`jetson/README.md`](./jetson/README.md); do not use an `App-v03` checkout as a
runtime service source.

Install the platform GStreamer packages and PyGObject before enabling the
feed. Keep the values in
[`src-tauri/src-py/camera.env.example`](src-tauri/src-py/camera.env.example)
in sync with the Jetson sender, especially `JETSON_VIDEO_PORT` and
`JETSON_VIDEO_PAYLOAD_TYPE`.

Verify the receiver without opening the website:

```bash
curl http://127.0.0.1:5001/api/v1/camera/status
curl -X POST http://127.0.0.1:5001/api/v1/camera/start
curl -i --max-time 2 http://127.0.0.1:5001/api/v1/camera/preview
```

If GStreamer is unavailable, telemetry remains available and the camera status
reports the missing video dependency instead of affecting MAVLink reception.

## Live YOLO callback dan map target

Recording agent Jetson memiliki extension R2 untuk menjalankan custom YOLO pada
branch inference terpisah. Ia tetap merekam video high-resolution dan
`frames.jsonl` ke SSD; yang dikirim ke Ground hanya JSON detection kecil. Model
yang saat ini terpasang di Jetson adalah:

```text
/home/bengawan/Documents/s-yolov11-main/ghostv3_dwconv-seed0/weights/best.pt
```

Profile tersebut diverifikasi dengan manifest
`jetson/production_model_ghostv3.json`, `imgsz=640`, confidence `0.25`,
`SAHI=false`, dan custom runtime/module path. Jetson saat ini memakai CPU
secara eksplisit karena driver CUDA lebih lama daripada runtime Torch yang
terpasang; inference berjalan low-rate sehingga capture tidak menunggu inference.

Sebelum membuka/menjalankan recording, konfigurasi backend Ground secara lokal
(jangan commit token):

```text
JETSON_RECORDING_AGENT_URL=http://100.124.21.25:5101
JETSON_RECORDING_AGENT_TOKEN=<token-control-agent-jetson>
# Flask must listen beyond loopback for Jetson callbacks.
API_HOST=0.0.0.0
API_PORT=5001
JETSON_GCS_HOST=<IP-Tailscale-laptop-Ground>
VISION_INGEST_TOKEN=<nilai-yang-sama-dengan-JETSON_INGEST_TOKEN>
VISION_COORDINATE_ENABLED=false
```

Pada laptop Windows teman, ganti `<IP-Tailscale-laptop-Ground>` dengan IP
Tailscale laptop tersebut. Jangan memakai IP laptop developer atau alamat
loopback, karena Jetson harus dapat melakukan callback ke Ground. Token
`JETSON_RECORDING_AGENT_TOKEN` mengontrol start/stop; token
`VISION_INGEST_TOKEN` mengautentikasi event detection Jetson → Ground.
Izinkan inbound TCP `5001` dari interface/Tailscale network pada Windows
Firewall. Jika backend tetap bind ke `127.0.0.1`, video preview lokal mungkin
tetap berjalan tetapi callback detection Jetson akan gagal.

Urutan pengujian:

1. Jalankan router MAVLink dan backend Ground.
2. Pastikan `buv-recording-agent.service` Jetson aktif.
3. Buka camera preview untuk memastikan RTP masuk.
4. Tekan **Start Record**. Ground membuat mission dan Jetson memulai recorder
   serta child inference.
5. Periksa endpoint berikut dari Ground:

   ```text
   http://127.0.0.1:5001/api/v1/detection/status
   http://127.0.0.1:5001/api/v1/detection/latest
   ```

6. Tekan **Stop Record**. Artifact Ground berada di
   `runtime/logs/missions/<mission_id>/detections_with_telemetry.jsonl`; video
   dan frame metadata tetap di Jetson.

Live detection callback tidak menggambar bbox pada preview. Dot target di peta
hanya dirender bila coordinate result memiliki status
`ESTIMATED_UNCALIBRATED`/`CALIBRATED_ESTIMATE` dan koordinat valid. Karena
calibration Arducam, mounting orientation, dan AGL belum tervalidasi,
`VISION_COORDINATE_ENABLED=false` adalah konfigurasi aman saat ini; event dan
telemetry join tetap dapat diuji tanpa menghasilkan dot coordinate palsu.

MAVLink Anywhere, Internet fallback, dan link failover tetap future work.
Coordinate reconstruction offline/live adapter didokumentasikan di
`COORDINATE_ESTIMATOR_AUDIT.md` dan tidak mengubah receive-only boundary.

## Troubleshooting

Check Windows UDP listeners:

```powershell
Get-NetUDPEndpoint -LocalPort 14550,14551 -ErrorAction SilentlyContinue
```

Check the Pixhawk serial device:

```powershell
Get-PnpDevice -Class Ports | Where-Object Status -eq "OK"
```

If the router prints a serial read error, close QGroundControl's serial link
and any other serial monitor. QGroundControl should use UDP `14550`, not the
Pixhawk COM port.

If the monitor receives nothing, verify that the router is running and that
the web backend/monitor is bound to UDP `14551` only after the router has
started sending packets.
