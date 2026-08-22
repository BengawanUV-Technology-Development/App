# MAVLink router setup

This repository uses a small `pymavlink` router instead of exposing the
Pixhawk serial device directly to the web backend.

```
Pixhawk serial
      │
      ▼
scripts/mavlink_readonly_router.py
      ├── UDP 14550 ──► QGroundControl (telemetry + commands)
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
- Web backend: `127.0.0.1:14551`

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
