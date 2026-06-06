# Bengawan UAV SAR Showcase Console

Ground station showcase untuk demonstrasi integrasi flight controller, telemetry link, peta posisi UAV, dan video payload Jetson Orin Super untuk misi pencarian korban banjir bandang.

App ini tidak ditujukan untuk menggantikan ArduPilot Mission Planner. Konfigurasi parameter lanjutan seperti `Q_ENABLE`, `Q_FRAME_CLASS`, airspeed, servo function, calibration, dan tuning tetap dilakukan di Mission Planner. Fokus aplikasi ini adalah tampilan operasional yang rapi untuk demo, monitoring, dan command dasar yang sudah tervalidasi.

## Fokus Produk

- Connect telemetry MAVLink melalui port COM dan baudrate yang dipilih operator.
- Monitoring kondisi flight controller: connected, armed, flight mode, battery, GPS, altitude, speed, attitude, heading.
- Command dasar: arm, disarm, reboot aman saat disarmed, dan flight mode showcase untuk mode ArduPilot Plane/QuadPlane.
- Video showcase dari Jetson Orin Super untuk pipeline object detection korban bencana.
- Peta showcase berisi titik GPS UAV dan ikon pesawat yang mengikuti heading/gyro telemetry.
- Event log UI dan terminal backend untuk membantu operator melihat command berhasil/gagal.

## Status Flight Mode

Mode switching sudah diverifikasi dari MAVLink `HEARTBEAT.custom_mode`, bukan hanya dari response HTTP. Backend membaca custom mode ArduPilot dan menampilkan mode seperti:

- `MANUAL`
- `FBWA`
- `AUTO`
- `RTL`
- `QSTABILIZE`
- `QHOVER`
- `QLAND`

Catatan: MAVSDK Python tidak mengenali beberapa mode ArduPilot QuadPlane sehingga telemetry MAVSDK bisa melaporkan `UNKNOWN`. Backend membaca heartbeat MAVLink langsung untuk mendapatkan mode ArduPilot yang benar.

## Scope Yang Tidak Dikerjakan Di App Ini

- Parameter setup dan tuning: tetap di Mission Planner.
- Kalibrasi compass, accelerometer, airspeed, radio, motor test: tetap di Mission Planner.
- Upload mission penuh dan konfigurasi autopilot lanjutan bukan prioritas showcase.

## Arsitektur Ringkas

- Frontend: React/Vite dashboard showcase.
- Backend: Flask + MAVSDK Python.
- Protocol: MAVLink telemetry dan command.
- Payload vision: placeholder UI untuk Jetson Orin Super camera/object detection, siap diarahkan ke stream nyata.

## Menjalankan Backend

```powershell
cd src-tauri\src-py
.\.venv\Scripts\python.exe main.py
```

Backend berjalan di:

```text
http://127.0.0.1:5001
```

Pastikan hanya ada satu proses `main.py` aktif agar log terminal sesuai dengan UI yang sedang dipakai.

## Menjalankan Frontend

```powershell
npm run dev -- --host 127.0.0.1
```

## Demo Flow

1. Buka app.
2. Pilih COM port dan baudrate telemetry.
3. Klik connect.
4. Pastikan backend log menampilkan vehicle online.
5. Uji arm/disarm atau flight mode sesuai kebutuhan showcase.
6. Pantau map, attitude, heading, GPS, dan panel video SAR.

## Tahap Berikutnya

- Integrasi stream video Jetson Orin Super.
- Overlay bounding box object detection dari model AI.
- Integrasi peta nyata dan marker GPS.
- 3D aircraft marker yang lebih matang mengikuti roll, pitch, yaw, dan heading.
- POI korban: hasil deteksi dikaitkan dengan estimasi koordinat GPS.
