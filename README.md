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

## Menjalankan

1. Jalankan `mission-planner/mission_planner_bridge.py` dari Mission Planner.
2. Jalankan backend:

   ```powershell
   cd src-tauri/src-py
   .\.venv\Scripts\python.exe main.py
   ```

3. Jalankan frontend:

   ```powershell
   npm run dev -- --host 127.0.0.1
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
