# BUV SAR Showcase Console - Progress & Roadmap

Dokumen ini adalah catatan status kerja terbaru untuk aplikasi ground station showcase Bengawan UAV.

Keputusan scope saat ini: aplikasi ini bukan pengganti ArduPilot Mission Planner. Parameter setup dan tuning seperti `Q_ENABLE`, frame/servo setup, calibration, airspeed setup, dan konfigurasi autopilot lanjutan tetap dilakukan di Mission Planner. Aplikasi ini difokuskan untuk showcase operasional: connect telemetry, command dasar, monitoring flight controller, map, model wahana 3D, dan payload video/object detection Jetson Orin Super.

## Status Terkini

Per 3 Juni 2026, aplikasi sudah sampai tahap:

- Backend command dasar stabil.
- Connection manual COM/baudrate sudah seperti Mission Planner style.
- Flight mode ArduPilot Plane/QuadPlane bisa dikirim via MAVLink direct.
- Flight mode sudah diverifikasi dari `HEARTBEAT.custom_mode`, bukan hanya response HTTP.
- Dashboard frontend sudah diarahkan menjadi SAR showcase console.
- Model wahana `.glb` dari `public/img/wahana.glb` sudah dirender memakai Three.js di map panel.
- Terminal backend sudah menampilkan log command/connection yang berguna untuk debugging.

## Yang Sudah Dikerjakan

### 1. Connection / Telemetry

- Menonaktifkan auto-connect awal; operator memilih COM/baudrate sendiri.
- Menampilkan COM port dari Device Manager via serial port scan.
- Mendukung baudrate umum seperti `57600` dan `115200`.
- MAVSDK gRPC port dibuat auto agar tidak bentrok di `50051`.
- Endpoint connection/health/telemetry tersedia.
- Polling `/health` dan `/telemetry` difilter dari log terminal agar tidak spam.

File terkait:

- `src-tauri/src-py/main.py`
- `src-tauri/src-py/app/routes/connection.py`
- `src/hooks/useConnection.js`
- `src/components/connection/ConnectionPanel.jsx`

### 2. Terminal Logging

- Backend print startup banner dengan PID, cwd, route, dan port.
- Command request/response diprint di terminal.
- Mode switching, arm/disarm, reboot, connection target, dan error command terlihat jelas.
- Duplicate backend process pernah menyebabkan terminal terlihat kosong; catatan penting: jalankan satu `main.py` saja di terminal visible.

File terkait:

- `src-tauri/src-py/main.py`
- `src-tauri/src-py/app/routes/commands.py`
- `src-tauri/src-py/app/services/command.py`

### 3. Command Dasar

- `arm`
- `disarm`
- `takeoff`
- `land`
- `set_takeoff_altitude`
- `reboot` dengan guard: hanya saat disarmed
- response command sudah pakai kontrak seragam
- error handling command sudah dipetakan ke domain error

File terkait:

- `src-tauri/src-py/app/routes/commands.py`
- `src-tauri/src-py/app/services/command.py`
- `src-tauri/src-py/tests/test_command_logic.py`
- `src-tauri/src-py/tests/test_http_smoke.py`

### 4. Flight Mode ArduPilot

Mode yang didukung backend:

- `MANUAL`
- `FBWA`
- `AUTO`
- `RTL`
- `QSTABILIZE`
- `QHOVER`
- `QLAND`

UI boleh memakai label Mission Planner style dengan underscore:

- `Q_STABILIZE`
- `Q_HOVER`
- `Q_LAND`

Backend melakukan normalisasi ke nama ArduPilot tanpa underscore.

Implementasi:

- `SET_MODE`
- `COMMAND_LONG / MAV_CMD_DO_SET_MODE`
- target default `sysid=1`, `compid=1`
- base mode menambahkan armed flag saat FC armed
- mode dibaca ulang dari MAVLink `HEARTBEAT.custom_mode`

Bukti berhasil:

```text
[heartbeat] mode=FBWA custom_mode=5 sysid=1 compid=1
[heartbeat] mode=QHOVER custom_mode=18 sysid=1 compid=1
[heartbeat] mode=QSTABILIZE custom_mode=17 sysid=1 compid=1
```

Catatan AUTO:

- AUTO tetap ditampilkan karena nanti dipakai untuk mission.
- Jika FC masuk RTL setelah command AUTO, itu bukan bug UI. Heartbeat menunjukkan FC menolak/keluar dari AUTO dan report `RTL custom_mode=11`.
- Kemungkinan penyebab: mission belum valid, auto condition belum terpenuhi, atau failsafe/state FC menahan mode.

File terkait:

- `src-tauri/src-py/app/services/command.py`
- `src-tauri/src-py/main.py`
- `src/components/command/FlightModeGrid.jsx`

### 5. Telemetry HUD

Backend sudah mengonsumsi:

- posisi GPS: lat/lng/alt
- armed state
- flight mode
- battery
- roll
- pitch
- yaw
- heading
- groundspeed
- vertical speed

File terkait:

- `src-tauri/src-py/app/models.py`
- `src-tauri/src-py/main.py`
- `src/views/DashboardView.jsx`

### 6. SAR Showcase Dashboard

Dashboard sekarang diarahkan untuk demo:

- panel kiri: PFD mini, arm/disarm, reboot, flight mode, takeoff/land
- panel tengah atas: video placeholder Jetson Orin Super + object detection boxes
- panel tengah bawah: map placeholder + route + POI + model wahana 3D
- panel kanan: Flight Controller, Telemetry/Controller, Vision Payload, System Alerts Log
- log UI bisa scroll dan menyimpan lebih banyak event

File terkait:

- `src/views/DashboardView.jsx`
- `src/App.css`
- `src/components/command/FlightModeGrid.jsx`

### 7. Model Wahana 3D

- File model: `public/img/wahana.glb`
- Model dirender di map panel memakai Three.js.
- Dependency `three` sudah ditambahkan.
- Component baru dibuat:

```text
src/components/map/AircraftModel3D.jsx
```

Status:

- model sudah muncul
- fallback tampil saat GLB loading/error
- heading/roll/pitch sudah dihubungkan ke telemetry
- arah model mungkin masih perlu kalibrasi offset tergantung orientasi bawaan `.glb`

Kalibrasi arah model:

```js
const MODEL_HEADING_OFFSET_DEG = 0;
```

Jika nose model tidak searah heading FC, coba ubah ke `90`, `180`, atau `-90`.

File terkait:

- `public/img/wahana.glb`
- `src/components/map/AircraftModel3D.jsx`
- `src/views/DashboardView.jsx`
- `src/App.css`
- `package.json`
- `package-lock.json`

### 8. Dokumentasi

README sudah diubah agar scope lebih realistis:

- aplikasi adalah SAR Showcase Console
- parameter tuning tetap di Mission Planner
- mode switching sudah diverifikasi dari heartbeat
- tahap berikutnya: map nyata, Jetson stream, detection overlay, POI geotagging

File terkait:

- `README.md`
- `src-tauri/src-py/step.md`

## Verifikasi Terakhir

Command yang sudah dijalankan dan berhasil:

```powershell
npm run build
.\.venv\Scripts\python.exe -m py_compile main.py app\services\command.py
.\.venv\Scripts\python.exe -m pytest tests
```

Catatan:

- Build frontend berhasil.
- Backend tests pernah lulus `36 passed`.
- Setelah Three.js, Vite memberi warning chunk besar untuk `AircraftModel3D`, tapi sudah di-code-split dengan `React.lazy`.

## Cara Menjalankan Saat Demo

Backend:

```powershell
cd C:\Users\irfan\Kuliah\BUV\test\src-tauri\src-py
.\.venv\Scripts\python.exe main.py
```

Frontend:

```powershell
cd C:\Users\irfan\Kuliah\BUV\test
npm run dev -- --host 127.0.0.1
```

URL frontend yang biasa aktif:

```text
http://127.0.0.1:1420
```

## Roadmap Berikutnya

### Fase 16 - Map Nyata

Tujuan: mengganti placeholder map dengan map operasional.

- [ ] Pilih library peta: Leaflet/react-leaflet atau map tile lightweight.
- [ ] Render posisi UAV berdasarkan GPS.
- [ ] Tampilkan model wahana di koordinat UAV.
- [ ] Model mengikuti heading/roll/pitch/yaw telemetry.
- [ ] Tambahkan marker POI korban.

### Fase 17 - Mission Showcase

Tujuan: AUTO dapat dipakai dalam konteks mission.

- [ ] Pastikan mission plan valid sebelum tombol AUTO dipakai.
- [ ] Tampilkan status mission loaded / not loaded.
- [ ] Tampilkan waypoint route di map.
- [ ] Tambahkan warning UI jika AUTO gagal dan FC masuk RTL.
- [ ] Integrasikan progress mission dari backend.

### Fase 18 - Jetson Orin Super Video Stream

Tujuan: mengganti video placeholder dengan stream nyata.

- [ ] Tentukan protokol stream dari Jetson: RTSP, UDP, MJPEG, atau WebRTC.
- [ ] Tambahkan config stream URL.
- [ ] Render live video di panel atas.
- [ ] Jaga fallback placeholder saat stream belum tersedia.

### Fase 19 - Object Detection Overlay

Tujuan: hasil deteksi korban tampil di video panel.

- [ ] Terima metadata detection dari Jetson.
- [ ] Format metadata minimal: label, confidence, bbox, timestamp.
- [ ] Overlay bounding box di video.
- [ ] Catat detection event ke System Alerts Log.

### Fase 20 - POI / Geotagging

Tujuan: hasil deteksi dapat menjadi kandidat titik korban di map.

- [ ] Hitung estimasi lokasi korban dari posisi UAV, altitude, attitude, sudut kamera, dan bbox center.
- [ ] Simpan POI dengan coordinate, confidence, timestamp.
- [ ] Render POI permanen di map.

### Fase 21 - Controller / RC Monitoring

Tujuan: panel controller tidak lagi placeholder.

- [ ] Tentukan MAVLink stream untuk RC/channel/controller state.
- [ ] Tampilkan signal/status controller.
- [ ] Tampilkan channel penting jika dibutuhkan showcase.

## Catatan Penting

- Jangan ubah parameter autopilot dari app ini untuk demo sekarang; gunakan Mission Planner.
- Jalankan hanya satu backend `main.py` agar log terminal benar.
- AUTO bisa gagal jika mission belum siap; heartbeat RTL berarti FC yang memilih/menahan RTL.
- Mode ArduPilot QuadPlane dari heartbeat memakai nama tanpa underscore: `QHOVER`, `QSTABILIZE`, `QLAND`.
- UI boleh menampilkan label dengan underscore demi keterbacaan: `Q_HOVER`, `Q_STABILIZE`, `Q_LAND`.
