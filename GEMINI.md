# Mission Planner - Bengawan UAV

A Ground Control Station (GCS) application for UAVs, built with a hybrid architecture combining the performance of Rust (Tauri), the flexibility of Python (MAVSDK), and a modern React frontend.

## Project Overview

*   **Frontend:** React (JavaScript) + Vite.
*   **Shell/Desktop Layer:** Tauri (Rust).
*   **Backend Engine:** Python (Flask) using MAVSDK for MAVLink communication.
*   **Intelligence:** Computer Vision (CV) pipeline for Search and Rescue (SAR) missions.
*   **Purpose:** Planning, executing, and analyzing UAV missions with real-time telemetry, HUD, and automated victim detection.

## SAR Intelligence & Computer Vision Roadmap

The project is evolving into a specialized SAR tool with the following intelligence layers (refer to `src-tauri/src-py/step.md` for full details):

1.  **Object Detection Pipeline (Fase 16):** Integration of OpenCV and YOLO/PyTorch to process real-time video streams (RTSP/UDP) for detecting victims (limbs, clothing, etc.).
2.  **Geotagging Discovery (Fase 17):** An auto-marking system that calculates the real-world GPS coordinates of detected objects by triangulating UAV position, altitude, attitude (Roll/Pitch/Yaw), and gimbal angle.
3.  **SAR UI Optimization (Fase 18):** A split-view interface featuring a live video feed with bounding box overlays and an interactive map showing automatically generated Points of Interest (POI).

## Architecture & Communication

1.  **UI <-> Backend:** The React frontend communicates with the Python Flask backend via HTTP polling on `http://localhost:5001`. No WebSocket — all data is fetched via `setInterval` + `fetch`.
2.  **Backend <-> UAV:** The Python backend uses `MAVSDK` to communicate with the Flight Controller (FC) via MAVLink.
3.  **Vision Engine:** (Planned) A specialized thread in the Python backend will handle video stream processing and emit detection events.
4.  **Shell:** Tauri provides the desktop window and handles system-level integrations.

### Current Backend Endpoints

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| GET | `/health` | Connection status, system address |
| GET | `/telemetry` | Full telemetry state (position, attitude, speed, battery) |
| POST | `/command/arm` | Arm vehicle |
| POST | `/command/disarm` | Disarm vehicle |
| POST | `/command/takeoff` | Takeoff to altitude |
| POST | `/command/land` | Land vehicle |
| POST | `/command/set_takeoff_altitude` | Set takeoff altitude |
| POST | `/command/set_flight_mode` | Switch flight mode (ArduPilot direct bypass) |
| POST | `/command/reboot` | Reboot flight controller |
| POST | `/mission/upload` | Upload waypoint mission |
| POST | `/mission/start` | Start mission |
| POST | `/mission/pause` | Pause mission |
| POST | `/mission/clear` | Clear mission |
| GET | `/mission/progress` | Get mission progress |
| GET | `/logs/summary` | Session log summary |
| GET | `/logs/recent` | Recent log events |

## Getting Started

### Prerequisites

*   Node.js & npm
*   Rust (for Tauri)
*   Python 3.10+
*   MAVSDK-compatible simulator (e.g., PX4/ArduPilot SITL) or physical hardware.

### Running the Application

This project requires both the Python backend and the Tauri frontend to be running simultaneously.

#### 1. Start the Python Backend
```bash
cd src-tauri/src-py
# Recommended: Create a virtual environment
python -m venv .venv
source .venv/bin/activate # or .venv\Scripts\activate on Windows
pip install -r requirements.txt
python main.py
```
*Note: The default `MAVSDK_ADDRESS` is `serial://COM9:115200`. You can override this using environment variables.*

#### 2. Start the Tauri Frontend
```bash
# In the project root
npm install
npm run tauri dev
```

## Development Conventions

### Python Backend (`src-tauri/src-py`)
*   **Routes:** Organized using Flask Blueprints in `app/routes/`.
*   **State Management:** The `StateManager` class in `app/utils/state.py` holds real-time telemetry.
*   **MAVSDK Loop:** Runs in a background thread to maintain the MAVLink connection.
*   **Testing:** Uses `unittest`. Run with `pytest tests/` from the `src-py` directory.

### Frontend (`src/`)
*   **Components:** Functional React components.
*   **API Calls:** Centralized `API_BASE` is `http://localhost:5001`.
*   **Styles:** Standard CSS (`App.css`).

## Key Commands & Scripts

| Command | Description |
| :--- | :--- |
| `npm run dev` | Start Vite dev server for the frontend only. |
| `npm run tauri dev` | Start the full Tauri desktop application. |
| `npm run build` | Build the frontend for production. |
| `python src-tauri/src-py/main.py` | Start the Python MAVSDK backend. |
| `pytest src-tauri/src-py/tests` | Run Python backend unit tests. |

## Troubleshooting

*   **Connection Error:** Ensure the `MAVSDK_ADDRESS` in `src-tauri/src-py/main.py` or environment variables matches your device or simulator port.
*   **Backend Access:** If the frontend shows "Backend Python belum bisa diakses", verify that the Flask server is running on port 5001.
