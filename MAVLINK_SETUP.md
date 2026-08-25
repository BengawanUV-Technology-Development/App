# MAVLink router setup

Untuk baseline redevelopment, lihat [R0_ARCHITECTURE_BASELINE.md](./R0_ARCHITECTURE_BASELINE.md).
Panduan ini menjelaskan setup runtime yang tersedia saat ini; ia tidak berarti
seluruh mission, frame metadata, chrony, atau hardware verification Mission
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
[`SHORT_FLIGHT_TEST.md`](./SHORT_FLIGHT_TEST.md).

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

MAVLink Anywhere, Internet fallback, YOLO, coordinate reconstruction, and a new
WebSocket video/detection transport are outside this setup and outside R0.

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
