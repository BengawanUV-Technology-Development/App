# BUV SAR Console

BUV SAR Console adalah aplikasi operasional pendamping Mission Planner untuk
monitoring penerbangan, visualisasi map, dan pengembangan computer vision.

Mission Planner tetap menjadi sumber kebenaran untuk koneksi flight controller,
telemetry, konfigurasi parameter, dan mission. Aplikasi ini tidak berkomunikasi
langsung dengan MAVLink/MAVSDK.

## Arsitektur

```text
Flight Controller
  -> Mission Planner
  -> Mission Planner HTTP Bridge :5000
  -> BUV Backend API/WebSocket :5001
  -> React + Tauri Frontend
```

## Setup and Installation

This project utilizes Docker to containerize the Python backend and AI dependencies, ensuring a consistent development environment.

### Prerequisites
- Node.js & npm
- Docker Desktop
- Mission Planner (Windows)

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

3. **Start the Mission Planner Bridge**
   Open Mission Planner, navigate to the Scripts tab, and run `mission-planner/mission_planner_bridge.py`. This bridge is required to forward telemetry data to the backend.

4. **Start the Backend Services (Docker)**
   ```bash
   docker compose up -d
   ```
   *The Flask API and AI Orchestrator will run in the background on port 5001.*

5. **Start the Frontend UI (Tauri)**
   ```bash
   npm install
   npm run tauri dev
   ```

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

## Endpoint Backend

```text
GET  /api/v1/health
GET  /api/v1/telemetry
WS   /api/v1/events
POST /api/v1/commands/arm
POST /api/v1/commands/disarm
POST /api/v1/commands/reboot
POST /api/v1/commands/set-flight-mode
GET  /logs/summary
GET  /logs/recent
```

## Scope Saat Ini

- Telemetry HUD dari Mission Planner.
- Arm, disarm, reboot saat disarmed, dan perubahan flight mode melalui Mission
  Planner.
- HTTP snapshot dengan WebSocket real-time dan fallback polling.
- Deteksi telemetry stale dan validitas GPS.
- Dashboard SAR, model wahana 3D, serta fondasi map dan computer vision.

Roadmap lengkap tersedia di
`docs/2026-06-06-mission-planner-vision-refactor-plan.md`.
