# Bengawan UAV Ground Application

The v0.3 release connects a single Arducam on Jetson to a Flask/Tauri ground
application. Stable behavior is defined in [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md);
qualification evidence and remaining hardware gates are tracked in
[PROJECT_STATUS.md](PROJECT_STATUS.md).

## Production profile

- Arducam master evidence: 1920×1080 at 30 FPS on Jetson SSD.
- H.264/RTP/UDP preview: 960×540 at 15 FPS.
- Baseline s-YOLOv11: 640 input, confidence 0.45, CUDA, SAHI disabled.
- Schema v2.0 canonical identity from capture through browser overlay.
- Coordinate status is always `not_available`; reconstruction is future work.
- Flight commands are restricted to SITL until Batch 7 qualification passes.

## Local development

The Python backend requires Python 3.10 or newer. The production test suite
uses `dataclass(slots=True)` and is not supported by Python 3.9.

### Architecture Overview

```text
Flight Controller
  -> MAVLink Router di Jetson
  -> telemetry collector read-only :5760 localhost
  -> telemetry.jsonl per frame
```

Video dan recording Arducam berjalan melalui Jetson:

```text
Arducam CSI/Argus -> Jetson split pipeline
  ├─ high-res -> video.mp4 lokal Jetson
  ├─ frame PTS + MAVLink snapshot -> telemetry.jsonl lokal Jetson
  ├─ optional YOLO/SAHI -> detections.jsonl lokal Jetson
  ├─ low-res H.264/RTP/UDP :5000 -> GCS preview
  └─ bbox HTTP :5001 -> GCS overlay

GCS website -> recording agent Jetson :5101 -> START / STOP & SAVE
```

## Setup and Installation

This project utilizes Docker to containerize the Python backend and AI dependencies, ensuring a consistent development environment.

### Prerequisites
- Node.js & npm
- Docker Desktop
- Mission Planner (Windows; optional untuk capture-only)
- Tailscale, atau jaringan modem/LAN yang membuat Jetson dan GCS saling terjangkau
- Jetson dengan kamera Arducam CSI/Argus dan GStreamer

### Quick Start

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd <repository-folder>
   ```

2. **Configure Environment Variables**
   ```bash
   cp src-tauri/src-py/.env.example src-tauri/src-py/.env
   ```
   *Edit `src-tauri/src-py/.env` and insert your Gemini, Notion, and Telegram API keys.*

3. **Start the Mission Planner Bridge (optional)**
   Open Mission Planner, navigate to the Scripts tab, and run
   `mission-planner/mission_planner_bridge.py` if the dashboard needs live
   telemetry, mission, or flight-controller commands. Capture-only recording
   can skip this step; Jetson reads MAVLink separately in read-only mode.

4. **Start the Backend Services (Docker)**
   ```bash
   docker compose up --build -d backend
   ```
   *The Flask API runs on TCP port 5001. The Docker Compose configuration juga
   mem-publish UDP port 5000 untuk low-res RTP dari Jetson.*

5. **Start the Frontend UI (Tauri)**
   ```bash
   npm install
   npm run tauri dev
   ```

> Flight recording melalui EasyCAP harus menjalankan backend secara native di
> Windows. Container Docker Linux tidak memiliki akses ke perangkat DirectShow.
> RD945 juga tetap membutuhkan catu daya fisik; Python mengaktifkan capture
> EasyCAP, bukan power receiver.

### Alternative: Manual Setup (Without Docker)

If you prefer to run the backend natively using a Python virtual environment:

1. **Adjust Environment Variables**: Ensure `MISSION_PLANNER_API_URL` in `src-tauri/src-py/.env` is set to `http://127.0.0.1:5000` (instead of `host.docker.internal`).
2. **Start the Backend**:
   ```bash
   cd src-tauri/src-py
   python -m venv .venv
   .\.venv\Scripts\activate   # Use `source .venv/bin/activate` on Linux/Mac
   pip install -r requirements.txt
   python main.py
   ```

### Testing the AI Pipeline
To simulate a target detection from the companion computer (e.g., Jetson Nano):
```bash
python src-tauri/src-py/mock_jetson.py
```

Untuk menguji bounding box, `frame_id`, dan koordinat dummy pada footage lokal:
```bash
python src-tauri/src-py/mock_vision.py --show
```

## Jetson split pipeline: high-res local + low-res network

Untuk produksi, jalankan `jetson/arducam_split_pipeline.py` secara native di
Jetson. Satu capture Argus dibagi menjadi tiga cabang:

```text
Arducam high-res
  ├─ x264enc → video.mp4 lokal Jetson       (evidence penerbangan)
  ├─ frame PTS + MAVLink → telemetry.jsonl   (read-only telemetry)
  ├─ BGR appsink → optional YOLO/SAHI        (detail objek)
  │                └─ detections.jsonl + optional POST bbox ke GCS
  └─ resize + x264enc → H.264/RTP/UDP        (low-res live preview GCS)
```

Default yang aman untuk mulai adalah high-res `1920x1080@30` untuk recording
dan YOLO/SAHI, lalu network `960x540@15` dengan bitrate `2 Mbps`. Orin Nano
tidak memiliki NVENC, sehingga sender menggunakan `x264enc` software.

```bash
npm install
npm run build

cd src-tauri/src-py
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python main.py
```

Run the Python suite from the repository root:

```bash
PYTHONPATH=src-tauri/src-py python -m unittest discover -s src-tauri/src-py/tests -v
```

The three tokens in `.env.example` are separate trust boundaries. Never name
the operator credential with a `VITE_` prefix. The desktop UI asks for it at
startup and retains it only in memory for that application session.

## Services

- `src-tauri/src-py`: ground API, synchronized receiver, persistent catalog,
  command audit, post-flight workflow, and reporting queue.
- `jetson`: recording agent, Arducam split pipeline, MAVLink sidecars, detector,
  and authenticated ingest client.
- `mission-planner`: loopback-by-default SITL command/telemetry bridge.

The production receiver requires the system PyGObject GStreamer 1.0 bindings;
it does not invoke `gst-launch` or parse a JPEG byte stream. The backend Docker
image installs the matching GI packages explicitly.

Do not use the diagnostic MJPEG endpoint as the production preview. The
production browser path is the binary vision WebSocket described by the
canonical contract.
