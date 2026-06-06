# Mission Planner Bridge and Computer Vision Refactor Plan

Tanggal keputusan: 6 Juni 2026  
Status: rancangan sebelum refactor  
Target: aplikasi showcase SAR yang realistis untuk diselesaikan tahun ini

## 1. Keputusan Utama

Aplikasi ini tidak lagi bertindak sebagai ground control station yang berkomunikasi
langsung dengan flight controller melalui MAVSDK/MAVLink.

Mission Planner menjadi sumber kebenaran untuk:

- koneksi ke flight controller;
- telemetry kendaraan;
- status armed/disarmed dan flight mode;
- eksekusi command kendaraan;
- pembuatan, upload, dan pengelolaan mission.

Aplikasi BUV menjadi console operasional yang berfokus pada:

- dashboard dan HUD;
- visualisasi GPS, jalur, waypoint, dan POI pada map;
- live video;
- object detection;
- geotagging hasil deteksi;
- pencatatan event dan hasil pencarian.

Keputusan repository: tetap gunakan repository ini dan buat branch refactor baru.
Repo baru belum diperlukan karena frontend, komponen HUD, Tauri shell, model 3D,
dan sebagian struktur backend masih dapat digunakan.

Nama branch yang disarankan:

```text
irfan/mission-planner-vision-refactor
```

Branch baru dibuat setelah perubahan aktif pada `irfan/main-refactored` disimpan
dalam commit agar riwayat dan working tree tetap jelas.

## 2. Target Arsitektur

```text
Flight Controller
       |
       | MAVLink
       v
Mission Planner
       |
       | Mission Planner Python script
       | HTTP API pada 127.0.0.1:5000
       v
BUV Backend pada 127.0.0.1:5001
  - Mission Planner adapter/proxy
  - map state dan POI
  - video/vision integration
  - object detection dan geotagging
  - event log
       |
       | HTTP API / WebSocket
       v
React + Tauri Frontend
```

Frontend hanya berkomunikasi dengan BUV Backend pada port `5001`. Frontend
tidak mengakses Mission Planner pada port `5000` secara langsung. Dengan pola
ini, perubahan format data dari script Mission Planner cukup ditangani oleh
adapter backend.

## 3. Batas Tanggung Jawab

### Mission Planner dan Script Bridge

Wajib menangani:

- membaca telemetry dan status dari Mission Planner;
- menyediakan snapshot telemetry melalui HTTP;
- menerima command terbatas dari BUV Backend;
- mengembalikan hasil command yang jelas;
- menyediakan heartbeat/status bridge.

Tidak menangani:

- object detection;
- pengolahan video;
- POI hasil deteksi;
- penyimpanan event aplikasi;
- rendering map atau dashboard.

### BUV Backend

Wajib menangani:

- proxy dan normalisasi data Mission Planner;
- validasi freshness telemetry;
- health status seluruh dependency;
- state map, track, detection, dan POI;
- integrasi stream kamera;
- inference object detection atau penerimaan hasil inference dari Jetson;
- sinkronisasi detection dengan posisi dan attitude UAV;
- event log.

Tidak lagi menangani:

- serial port scan flight controller;
- koneksi MAVSDK;
- decoding MAVLink heartbeat;
- command MAVLink langsung;
- upload mission langsung ke flight controller.

### Frontend

Wajib menangani:

- dashboard status yang mudah dipahami operator;
- HUD dan telemetry;
- map, track UAV, waypoint, dan POI;
- live video dan detection overlay;
- command button dengan confirmation untuk command berisiko;
- status Mission Planner bridge, backend, kamera, dan detector.

Tidak menangani:

- MAVLink;
- komunikasi langsung ke flight controller;
- perhitungan computer vision berat;
- normalisasi format data Mission Planner.

## 4. Kontrak API Minimum

Semua waktu menggunakan Unix timestamp dalam detik dan semua response memiliki
field `ok`.

### Mission Planner Bridge pada Port 5000

```text
GET  /api/v1/health
GET  /api/v1/telemetry
GET  /api/v1/mission
POST /api/v1/commands/arm
POST /api/v1/commands/disarm
POST /api/v1/commands/set-flight-mode
POST /api/v1/commands/start-mission
POST /api/v1/commands/pause-mission
POST /api/v1/commands/rtl
```

Contoh telemetry:

```json
{
  "ok": true,
  "timestamp": 1780750800.123,
  "vehicle": {
    "connected": true,
    "armed": false,
    "flight_mode": "QHOVER"
  },
  "position": {
    "lat": -7.123456,
    "lng": 110.123456,
    "relative_alt_m": 25.4,
    "absolute_alt_m": 130.8
  },
  "attitude": {
    "roll_deg": 1.2,
    "pitch_deg": -2.4,
    "yaw_deg": 183.0,
    "heading_deg": 183.0
  },
  "velocity": {
    "groundspeed_m_s": 12.3,
    "vertical_speed_m_s": 0.4
  },
  "battery": {
    "remaining_percent": 78.0,
    "voltage_v": 22.4
  }
}
```

Contoh command:

```json
{
  "request_id": "uuid-dari-backend",
  "timestamp": 1780750800.123,
  "mode": "AUTO"
}
```

Contoh response command:

```json
{
  "ok": true,
  "request_id": "uuid-dari-backend",
  "command": "set-flight-mode",
  "message": "Flight mode changed to AUTO",
  "timestamp": 1780750800.456
}
```

### BUV Backend pada Port 5001

Kontrak frontend menggunakan prefix yang sama:

```text
GET  /api/v1/health
GET  /api/v1/telemetry
GET  /api/v1/map/state
GET  /api/v1/detections
GET  /api/v1/poi
POST /api/v1/commands/*
POST /api/v1/poi/:id/confirm
POST /api/v1/poi/:id/reject
```

WebSocket ditambahkan setelah kontrak polling stabil:

```text
WS /api/v1/events
```

Event minimum:

- `telemetry.updated`;
- `bridge.status_changed`;
- `detection.created`;
- `poi.created`;
- `command.completed`;
- `system.alert`.

## 5. Keep, Replace, dan Remove

### Dipertahankan

- React/Vite frontend;
- Tauri shell;
- layout dashboard dan komponen HUD;
- `src/components/map/AircraftModel3D.jsx`;
- `public/img/wahana.glb`;
- komponen confirmation, toast, badge, dan event log;
- pola service API frontend;
- state model dan session log backend setelah disederhanakan;
- test infrastructure Python yang masih relevan.

### Diganti atau Disederhanakan

- `src/services/api.js`: gunakan `/api/v1` dan konfigurasi base URL;
- `src/hooks/useTelemetry.js`: sesuaikan kontrak telemetry baru dan stale state;
- `src/hooks/useConnection.js`: menjadi hook status Mission Planner bridge, bukan
  pemilih COM port;
- `src/hooks/useCommand.js`: gunakan command proxy backend;
- backend `main.py`: menjadi application factory/orchestrator sederhana;
- health endpoint: laporkan backend, Mission Planner bridge, kamera, dan detector;
- command routes: proxy tervalidasi ke Mission Planner bridge;
- mission view: hanya monitoring mission dari Mission Planner.

### Dihapus Setelah Pengganti Terverifikasi

- dependency `mavsdk`;
- dependency `grpcio` dan `protobuf` jika tidak digunakan vision;
- dependency `pyserial`;
- serial port scan;
- MAVSDK background loop;
- MAVLink heartbeat consumer;
- direct MAVLink flight mode mapping;
- backend service untuk arm, disarm, takeoff, land, reboot, dan mission upload
  langsung ke flight controller;
- UI untuk memilih COM port dan baudrate;
- test yang hanya menguji implementasi MAVSDK lama.

Kode lama tidak langsung dihapus pada awal refactor. Penghapusan dilakukan
setelah adapter Mission Planner lolos acceptance test.

## 6. Tahapan Implementasi

### Fase 0 - Amankan Baseline dan Buat Branch

- [x] Commit seluruh perubahan aktif pada `irfan/main-refactored`.
- [x] Pastikan frontend build dan test backend baseline lulus.
- [x] Buat branch `irfan/mission-planner-vision-refactor`.
- [x] Simpan dokumen ini sebagai acuan scope.

Selesai jika branch baru dapat dijalankan dengan kondisi yang sama seperti
baseline.

### Fase 1 - Feasibility Spike Mission Planner Bridge

- [x] Buat script Mission Planner minimum.
- [x] Buktikan script dapat membaca connected, armed, flight mode, GPS, dan
  attitude.
- [x] Buktikan endpoint HTTP lokal dapat berjalan tanpa membuat UI Mission
  Planner macet.
- [x] Buktikan satu command aman, misalnya perubahan mode saat pengujian di SITL.
- [ ] Ukur kestabilan selama minimal 30 menit.
- [x] Dokumentasikan cara start/stop script dan batasan environment scripting.

Fallback jika HTTP server di dalam script Mission Planner tidak stabil:
gunakan proses bridge Python terpisah yang menerima data dari Mission Planner.
Arsitektur BUV Backend dan frontend tetap sama.

Selesai jika `GET /api/v1/telemetry` stabil dan command uji memiliki response
yang dapat diverifikasi.

Hasil pengujian awal:

- Health dan telemetry Mission Planner asli lolos contract verifier.
- Perubahan mode `Q_HOVER` berhasil dikonfirmasi melalui telemetry SITL setelah
  parameter QuadPlane `Q_ENABLE=1`.
- Saat `Q_ENABLE=0`, Mission Planner menerima permintaan tetapi flight
  controller mempertahankan mode `Manual`; verifier berhasil mendeteksi kondisi
  tersebut.

### Fase 2 - Buat Mission Planner Adapter di BUV Backend

- [x] Tambahkan konfigurasi `MISSION_PLANNER_API_URL`.
- [x] Buat client HTTP dengan timeout pendek dan error mapping.
- [x] Normalisasi response bridge ke model internal BUV.
- [x] Buat `/api/v1/health` dan `/api/v1/telemetry`.
- [x] Tandai telemetry `stale` jika timestamp terlalu lama.
- [x] Tambahkan test menggunakan fake Mission Planner API.

Selesai jika backend tetap hidup dan memberi error yang jelas ketika Mission
Planner bridge mati.

### Fase 3 - Migrasikan Frontend ke Kontrak Baru

- [x] Ubah seluruh route command dan telemetry frontend aktif ke `/api/v1`.
- [x] Ganti Connection Panel menjadi Dependency Status Panel.
- [x] Hubungkan HUD ke telemetry dari adapter.
- [x] Tampilkan state `offline`, `stale`, dan `active`.
- [x] Pertahankan command confirmation.
- [x] Hapus ketergantungan UI terhadap COM port dan baudrate.

Selesai jika dashboard dapat menampilkan telemetry Mission Planner tanpa MAVSDK
di BUV Backend.

Status implementasi awal:

- Backend melakukan polling Mission Planner bridge pada interval 200 ms.
- Frontend mengambil snapshot awal dari HTTP dan menerima pembaruan melalui
  `WS /api/v1/events`.
- Frontend kembali ke polling dua detik saat WebSocket terputus.
- Command arm, disarm, reboot, dan perubahan flight mode sudah menggunakan proxy
  Mission Planner baru.
- Endpoint dan implementasi MAVSDK lama masih dipertahankan sementara untuk
  command yang belum dimigrasikan.
- Tombol takeoff, land, dan reboot lama dihapus sampai memiliki endpoint
  Mission Planner baru.
- Setelah validasi frontend, UI takeoff/land/reboot, config/tuning, mission
  upload langsung, serta pemilih COM/baud dihapus agar aplikasi hanya
  menampilkan fitur yang benar-benar aktif.

### Fase 4 - Hapus Jalur MAVSDK Lama

- [x] Hapus MAVSDK loop dan direct MAVLink implementation.
- [x] Hapus route/service connection lama.
- [x] Hapus service command/mission langsung.
- [x] Hapus dependency Python yang tidak lagi digunakan.
- [x] Hapus atau tulis ulang test lama.
- [x] Pastikan tidak ada import atau route lama tersisa.

Selesai jika aplikasi berjalan tanpa `mavsdk`, `grpcio`, dan `pyserial`.

### Fase 5 - Map Operasional

- [x] Pilih Leaflet dan CARTO Dark Matter sebagai basemap online awal.
- [x] Render posisi serta heading UAV.
- [x] Simpan dan render track UAV di frontend dengan batas awal 1.000 titik.
- [ ] Tampilkan waypoint/mission dari Mission Planner sebagai read-only.
- [ ] Tambahkan marker detection candidate dan confirmed POI.
- [ ] Tentukan batas panjang track dan strategi penyimpanan.
- [ ] Tambahkan cache/offline map setelah alur map online stabil.

Selesai jika operator dapat melihat posisi, arah, jalur, mission, dan POI secara
jelas pada map.

### Fase 6 - Video Pipeline

- [ ] Tentukan sumber kamera dan protokol stream.
- [ ] Buat endpoint/config stream.
- [ ] Tampilkan live video dengan reconnect dan fallback.
- [ ] Catat timestamp/frame identifier.
- [ ] Ukur latency end-to-end.

Pilihan awal yang disarankan:

- MJPEG untuk prototipe tercepat;
- WebRTC jika latency rendah menjadi kebutuhan utama;
- RTSP untuk input backend/Jetson, lalu konversi untuk konsumsi frontend.

Selesai jika stream stabil, dapat reconnect, dan timestamp frame tersedia.

### Fase 7 - Object Detection

- [ ] Tentukan kelas target dan dataset.
- [ ] Siapkan anotasi dan pembagian train/validation/test.
- [ ] Latih model baseline.
- [ ] Ekspor model ke format deployment Jetson.
- [ ] Jalankan inference pada stream.
- [ ] Kirim metadata `label`, `confidence`, `bbox`, `frame_id`, dan `timestamp`.
- [ ] Render bounding box sinkron dengan video.
- [ ] Simpan snapshot detection penting.

Selesai jika detection nyata tampil stabil pada video dan dapat dicatat sebagai
event.

### Fase 8 - Geotagging dan POI

- [ ] Simpan ring buffer telemetry berdasarkan timestamp.
- [ ] Cocokkan timestamp detection dengan telemetry terdekat.
- [ ] Kalibrasi kamera: resolusi, focal length/FOV, mounting angle, dan arah.
- [ ] Hitung estimasi lokasi objek dari posisi UAV, attitude, altitude, dan titik
  tengah bbox.
- [ ] Sertakan confidence dan estimasi error.
- [ ] Bedakan candidate POI dengan confirmed POI.
- [ ] Tampilkan POI pada map dan simpan riwayatnya.

Selesai jika hasil detection dapat menghasilkan kandidat lokasi yang dapat
diverifikasi di lapangan.

### Fase 9 - Hardening dan Demo

- [ ] Tambahkan startup checklist.
- [ ] Tambahkan simulator/fake bridge untuk demo tanpa flight controller.
- [ ] Uji putus-sambung Mission Planner, kamera, dan detector.
- [ ] Uji command timeout dan duplicate request.
- [ ] Pastikan command berisiko selalu meminta confirmation.
- [ ] Buat satu command untuk menjalankan stack aplikasi.
- [ ] Dokumentasikan SOP demo dan troubleshooting.

Selesai jika aplikasi dapat digunakan berulang kali tanpa perubahan manual pada
kode.

## 7. Urutan Prioritas untuk Target Tahun Ini

### Wajib

1. Mission Planner bridge stabil.
2. Telemetry/HUD melalui BUV Backend.
3. Map posisi UAV dan track.
4. Live video.
5. Object detection overlay.
6. Detection event dan candidate POI.
7. Status dependency dan error handling yang jelas.

### Bagus Jika Sempat

1. Geotagging dengan estimasi error yang terkalibrasi.
2. Penyimpanan session dan export laporan.
3. WebSocket real-time.
4. Packaging Tauri penuh.

### Tidak Masuk Scope Tahun Ini

1. Menggantikan seluruh fungsi Mission Planner.
2. Parameter tuning dan calibration autopilot.
3. Mission editor lengkap.
4. Direct MAVLink/MAVSDK fallback di aplikasi BUV.
5. Multi-vehicle support.

### Catatan Backlog Reboot

- Reboot FC melalui Mission Planner dapat membuat port COM hilang sementara.
- Auto reconnect perlu dievaluasi kembali setelah map, video, dan vision stabil.
- Untuk sekarang operator menyambungkan ulang Mission Planner bila port serial
  telah muncul kembali.

## 8. Risiko Utama dan Mitigasi

| Risiko | Dampak | Mitigasi |
| --- | --- | --- |
| HTTP server dalam script Mission Planner tidak stabil | Seluruh telemetry/command terganggu | Validasi pada Fase 1 dan siapkan bridge process terpisah |
| Telemetry dan frame video tidak sinkron | POI salah lokasi | Timestamp, frame ID, dan telemetry ring buffer |
| Mission Planner berhenti atau script mati | UI menampilkan data lama sebagai data aktif | Freshness check dan status `stale` |
| Command dikirim dua kali | Perilaku kendaraan berbahaya | `request_id`, timeout, dan deduplication |
| Object detection terlalu lambat | Overlay terlambat dan geotagging salah | Ukur latency dan gunakan inference di Jetson |
| Geotagging tidak akurat | POI tidak berguna | Kalibrasi kamera dan tampilkan estimasi error |

## 9. Acceptance Test Minimum

Sebelum dinyatakan selesai, sistem harus membuktikan:

- backend hidup walau Mission Planner belum berjalan;
- UI membedakan backend offline, bridge offline, telemetry stale, dan vehicle
  disconnected;
- telemetry yang ditampilkan memiliki timestamp;
- command memiliki confirmation, request ID, timeout, dan hasil yang jelas;
- map mengikuti GPS kendaraan;
- video dapat reconnect;
- detection bbox sesuai frame;
- detection event memiliki timestamp dan telemetry terkait;
- candidate POI dapat dikonfirmasi atau ditolak operator;
- semua fitur inti dapat diuji menggunakan fake bridge.

## 10. Langkah Refactor Pertama Setelah Dokumen Disetujui

1. Simpan perubahan aktif di branch sekarang dalam commit baseline.
2. Buat branch `irfan/mission-planner-vision-refactor`.
3. Implementasikan fake Mission Planner bridge terlebih dahulu.
4. Buat adapter backend dan migrasikan satu alur vertikal:
   `fake bridge -> backend /api/v1/telemetry -> HUD frontend`.
5. Setelah alur tersebut stabil, implementasikan script Mission Planner nyata.
6. Baru hapus MAVSDK lama secara bertahap.

Pendekatan ini menjaga aplikasi tetap dapat dijalankan selama proses refactor
dan memberi jalur pengujian tanpa selalu membutuhkan flight controller.
