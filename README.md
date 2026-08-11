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

Do not use the diagnostic MJPEG endpoint as the production preview. The
production browser path is the binary vision WebSocket described by the
canonical contract.
