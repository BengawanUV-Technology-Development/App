# Ground Station Backend Checklist

> **Runtime integration note (telemetry-only):** checklist sections below
> describe the legacy command-capable service layer and are retained as
> historical/unit-test reference. The production entry point now uses the
> receive-only MAVLink UDP backend on `127.0.0.1:14551`; command and mission
> HTTP routes are hard-blocked with `403 READ_ONLY`, and the Pixhawk serial
> link plus all vehicle commands belong to the external router/QGroundControl
> path.

> **R0 baseline notice:** [R0_ARCHITECTURE_BASELINE.md](../../R0_ARCHITECTURE_BASELINE.md)
> is the normative redevelopment context. The checklist below is retained as
> historical/legacy service-layer reference and roadmap material. Its command,
> MAVSDK, WebSocket, YOLO, and coordinate-reconstruction entries must not be
> interpreted as active R0 runtime capabilities.

> R0 additionally requires a per-recording `mission_id`, Jetson/Ground mission
> linkage, canonical frame metadata, chrony-based clock alignment, and separate
> telemetry source/receive timestamps. Those contracts are not implemented by
> this checklist batch.

Dokumen ini dipakai sebagai jalur kerja backend Python (Flask + MAVSDK) sampai siap dipakai frontend.
Fokusnya command API: konsisten, aman, gampang di-maintain, dan cukup lengkap untuk dipakai UI tanpa banyak asumsi tambahan.

## Roadmap Fitur Full

Status saat ini:

- Core backend command dan telemetry dasar sudah ada.
- Fase 1 sampai 8 di checklist backend sudah selesai.
- Fitur yang masih perlu dibangun mostly ada di luar command dasar, terutama telemetry HUD lanjutan, reconnect hardening, dan fitur frontend yang lebih lengkap.

### Scope backend yang sebaiknya dianggap "full"

Supaya plan backend tidak terlalu sempit, scope akhirnya sebaiknya mencakup:

- Connection lifecycle: connect, reconnect, health, dan recovery saat link putus.
- Command control: arm, disarm, takeoff, land, set takeoff altitude.
- Flight mode control: monitoring mode dan switching mode yang aman.
- Mission workflow: waypoint, upload mission, start, stop, dan progress monitor.
- Safety and reboot: reboot flight controller dengan guard yang jelas.
- Telemetry/HUD data: posisi, altitude, battery, attitude, speed, heading, dan status navigasi.
- Persistent logging: command event, telemetry ringkas, dan audit flight session.
- API contract consistency: error code, HTTP status, dan response body harus stabil di semua route.

### 1. ARM

- Backend: selesai.
- Status: siap dipakai frontend.

### 2. Flight Modes

- Backend monitoring: selesai.
- Backend switching mode: belum ada.
- Mode yang perlu ditambah kalau mau full control: `FBWA`, `Q_STABILIZE`, `Q_HOVER`, `Q_LAND`, `AUTO`, `MANUAL`.

### 3. Reboot

- Backend: belum ada endpoint reboot.
- Perlu: aksi reboot MAVSDK atau mekanisme restart yang aman.
- Perlu juga guard agar reboot tidak bisa dipanggil dalam kondisi yang tidak diizinkan tim.

### 4. Connect Telemetri

- Backend: selesai.
- Status: state koneksi, retry, recover, health, telemetry sudah ada.

### 5. GPS & Maps

- Backend monitoring posisi UAV: selesai.
- Bikin waypoint: belum ada.
- Upload/execute mission: belum ada.

### 6. HUD

- Backend data dasar: sudah ada untuk connected, armed, flight_mode, posisi, battery.
- Data HUD lanjutan seperti heading, speed, attitude, dan indikator navigasi masih bisa ditambah.
- Kalau frontend butuh overlay penerbangan yang enak dipakai, data attitude, groundspeed, vertical speed, dan heading sebaiknya masuk roadmap berikutnya.

### 7. Data Log

- Backend: belum ada logging persisten.
- Perlu: file log atau storage lain kalau mau histori flight dan command.

### 8. Opsional tapi berguna

- Endpoint disconnect/manual stop untuk memutus session dengan rapi.
- Endpoint status ringkas untuk frontend bootstrap.
- Audit trail command untuk debug insiden.
- Standardisasi nama field telemetry bila nanti ada kebutuhan sinkronisasi dengan UI atau mobile client.

## Progress Backend

- Fase 1: selesai.
- Fase 2: selesai.
- Fase 3: selesai.
- Fase 4: selesai.
- Fase 5: selesai.
- Fase 6: selesai.
- Fase 7: selesai.
- Fase 8: selesai.
- Fase 9: selesai.
- Fase 10: selesai.
- Fase 11: selesai.

## Audit Kesiapan Backend (22 April 2026)

Validasi yang sudah dicek ulang:

- Test backend lulus: 11/11.
- Endpoint command utama tersedia: `arm`, `disarm`, `takeoff`, `land`, `set_takeoff_altitude`.
- Telemetry + health endpoint tersedia dan terpasang.

Temuan penting sebelum lanjut ke fitur baru:

- Konsistensi error handling antar endpoint command sudah jauh lebih seragam.
- Di service layer, error MAVSDK sudah dipetakan ke exception domain yang lebih stabil.
- Endpoint untuk flight mode switching, reboot, waypoint/mission, dan data log persisten sudah tersedia.

Keputusan gate:

- Backend core sudah stabil untuk command dasar.
- Belum ideal lompat langsung ke fitur besar berikutnya sebelum gate konsistensi API dibereskan.

## Rekomendasi Urutan Kerja Berikutnya

Kalau mau aman dan efisien, backend sebaiknya dikejar sampai minimal fitur kontrol yang dipakai frontend sudah stabil:

1. Tambah HUD data lanjutan.
2. Tambah endpoint disconnect/manual stop.
3. Tambah perapihan frontend mission/log viewer.
4. Tambah hardening reconnect dan rotasi log jika diperlukan.

Kalau tujuanmu adalah cepat bikin UI jalan, frontend boleh mulai sekarang karena kontrak command dasar dan mission/logging sudah ada. Backend berikutnya lebih cocok ke penyempurnaan HUD dan workflow operasional.

## Tahap Selanjutnya (Backend)

Urutan ini disarankan supaya kamu (backend) tetap aman dari regresi:

### Fase 9 - API Consistency Gate (Wajib)

Tujuan: pastikan semua endpoint command selalu mengembalikan kontrak response yang konsisten untuk semua error path.

- [x] Samakan penanganan exception di semua route command (`arm`, `disarm`, `takeoff`, `land`, `set_takeoff_altitude`).
- [x] Ubah service agar melempar exception domain (`CommandFailedError`, `NotConnectedError`, `InvalidRequestError`) alih-alih `RuntimeError` generik.
- [x] Tambah mapping timeout ke `ErrorCode.TIMEOUT`.
- [x] Tambah test negatif untuk tiap endpoint command (MAVSDK gagal, timeout, invalid request).

DoD:

- Semua endpoint command menghasilkan format response error yang seragam.
- Tidak ada error path yang lolos menjadi HTML `500` default Flask.
- Route command dasar sudah punya cakupan negatif yang cukup untuk validasi response contract.

### Fase 10 - Flight Mode Switching

Tujuan: backend bisa ganti mode flight dari API.

- [x] Tambah endpoint `POST /command/set_flight_mode`.
- [x] Validasi mode yang diizinkan: `FBWA`, `Q_STABILIZE`, `Q_HOVER`, `Q_LAND`, `AUTO`, `MANUAL`.
- [x] Implement mapping mode -> MAVSDK action/API yang sesuai.
- [x] Tambah unit + smoke test untuk mode valid/invalid.
- [x] Tentukan apakah mode-switching ini hanya monitoring atau benar-benar bisa dieksekusi dari backend; kalau MAVSDK tidak mendukung mode tertentu, dokumentasikan fallback-nya.

DoD:

- Frontend bisa memicu perubahan mode via endpoint dengan response kontrak yang sama.

### Fase 11 - Reboot Endpoint

Tujuan: backend mendukung reboot flight controller secara aman.

- [x] Tambah endpoint `POST /command/reboot`.
- [x] Tambah safety guard (wajib connected, dan reject saat armed).
- [x] Tambah test sukses/gagal.
- [x] Reboot dieksekusi lewat MAVSDK action wrapper yang sama dengan command lain.

DoD:

- Reboot bisa dieksekusi dengan error handling yang konsisten.

### Fase 12 - Waypoint & Mission Basic

Tujuan: mulai dukung workflow mission planning minimal.

- [x] Definisikan kontrak waypoint payload (lat, lng, alt, urutan).
- [x] Tambah endpoint upload mission.
- [x] Tambah endpoint start/stop mission.
- [x] Tambah endpoint monitor progress mission.
- [x] Tambah validation untuk waypoint kosong, urutan duplikat, dan koordinat di luar range.
- [x] Pertimbangkan payload mission yang bisa dipakai ulang oleh frontend tanpa transformasi tambahan.

DoD:

- Mission sederhana bisa diupload dan dieksekusi dari backend.

### Fase 13 - Data Logging Persisten

Tujuan: data command + telemetry tersimpan untuk analisis pasca-flight.

- [x] Tentukan format log (JSONL/CSV/SQLite).
- [x] Simpan event command penting + telemetry interval.
- [x] Tambah endpoint baca log ringkas.
- [x] Tambah rotasi/limit file log.
- [x] Tambah metadata session minimal: start time, end time, system address, dan ringkasan error terakhir.

DoD:

- Minimal 1 sesi flight bisa direkam dan dibaca ulang.

## Status Pindah Tahap (Per 22 April 2026)

- Status saat ini: API consistency, flight mode switching, reboot endpoint, mission basic, data logging, dan HUD Expansion (Fase 14) sudah selesai.
- Backend berikutnya paling masuk akal lanjut ke Integrasi Peta, Computer Vision, dan Sinkronisasi Koordinat (Auto-marking).

## Tahap Lanjutan: SAR Intelligence & Computer Vision

### Fase 14 - HUD Expansion (Selesai)

Tujuan: backend mengonsumsi data attitude, speed, dan heading untuk keperluan visualisasi dan kalkulasi AI.

- [x] Tambahkan field data baru di `StateManager` (roll, pitch, yaw, heading, airspeed, groundspeed, v_speed).
- [x] Tambahkan MAVSDK consumer untuk attitude, velocity, dan heading di `main.py`.
- [x] Tampilkan data di dashboard Frontend (`App.jsx` atau `FlyView.jsx`).

### Fase 15 - Integrasi Peta Interaktif (Leafmap/Leaflet) (Partial)

Tujuan: frontend tidak lagi menampilkan koordinat angka, tapi peta visual.

- [x] Tambahkan library peta (misal: react-leaflet).
- [ ] Render posisi UAV secara real-time sebagai icon pesawat/drone di peta (3D Model Icon).
- [x] Tampilkan jalur (waypoint) dari `missionDraft`.

### Fase 16 - Computer Vision Integration (Object Detection Pipeline)

Tujuan: backend bisa memproses video stream dan mendeteksi objek.

- [ ] Setup virtual environment/dependency AI (OpenCV, YOLO/PyTorch).
- [ ] Buat script Python (terpisah dari `main.py` utama atau sebagai thread khusus) untuk menerima stream video (RTSP/UDP).
- [ ] Implementasikan object detection model sederhana.
- [ ] Siapkan endpoint atau WebSocket untuk mengirim hasil bounding box/deteksi ke Frontend.

### Fase 17 - Auto-Marking System (Geotagging Discovery)

Tujuan: menghitung koordinat GPS dari objek yang terdeteksi dan menandainya di peta.

- [ ] Buat formula kalkulasi (Posisi UAV + Altitude + Roll/Pitch/Yaw + Sudut Gimbal + Posisi Piksel Bounding Box) -> (Lat/Lng Objek di tanah).
- [ ] Backend memancarkan (emit) event penemuan (POI) lengkap dengan koordinat.
- [ ] Frontend mendengarkan event POI dan menambahkan marker (warna berbeda) secara permanen di peta.

### Fase 18 - Video Stream Overlay & UI SAR Optimization

Tujuan: menyatukan semua elemen SAR di layar GCS.

- [ ] Frontend menampilkan feed video dengan bounding box langsung dari backend.
- [ ] UI dibagi dua: Map View (kiri) dan Video/HUD View (kanan).
- [ ] List log penemuan (Timestamp, Gambar Crop Objek, Koordinat) di panel terpisah.

---

## Cara Pakai Dokumen Ini

- Kerjakan dari atas ke bawah.
- Jangan lompat fase kalau checkbox fase sebelumnya belum beres.
- Tiap fase punya indikator selesai (DoD).

---

## Fase 1 - Fondasi State Tunggal

Tujuan: semua endpoint baca state yang sama, tidak ada state dobel.

- [x] `StateManager` jadi source of truth utama.
- [x] Update telemetry di loop MAVSDK pakai `state_manager.update(...)`.
- [x] Endpoint command baca state dari `StateManager`, bukan dari dict global.
- [X] Hapus semua sisa state lama (`_state_lock`, `_telemetry_state`, helper legacy) kalau masih tersisa.

DoD:

- Tidak ada lagi path baca/tulis state selain `StateManager`.
- `GET /health` dan `POST /command/arm` selalu melihat nilai `connected` yang sama pada waktu yang sama.

---

## Fase 2 - Kontrak Response Konsisten

Tujuan: frontend bisa percaya format response tanpa if-else acak per endpoint.

- [x] `POST /command/arm` pakai `CommandResponse`.
- [X] Semua endpoint command (`arm`, `disarm`, `takeoff`, `land`, `set_takeoff_altitude`) pakai `CommandResponse`.
- [X] Semua `error_code` ambil dari enum `ErrorCode` (hindari string hardcoded yang beda-beda).
- [X] Semua jalur invalid request return `400` dengan `error_code=INVALID_REQUEST`.

DoD:

- Struktur response sukses/error seragam di semua endpoint command.
- Tidak ada `error_code` liar di luar enum.

---

## Fase 3 - Validasi Request yang Aman

Tujuan: request jelek tidak meledak jadi `500`.

- [x] Validasi tipe `altitude_m` (harus numerik).
- [X] Tangani body kosong / field hilang dengan pesan yang jelas.
- [X] Semua kasus input invalid berhenti di `400`, bukan exception runtime.
- [X] Reuse `CommandValidator` untuk aturan yang sudah ada.

DoD:

- Mengirim `{"altitude_m": "abc"}` tidak bikin traceback, tapi response `400`.
- Semua validasi punya pesan error yang konsisten.

---

## Fase 4 - Service Layer untuk Command

Tujuan: route tipis, logic pindah ke service.

- [X] Implement `CommandService` di `src-tauri/src-py/app/services/command.py`.
- [X] Pindahkan logic `arm/disarm/takeoff/land` dari route ke service.
- [X] Route hanya: parse request -> call service -> return response.
- [X] Validator dipakai di service, bukan di route.

DoD:

- File route tidak lagi berisi business logic command.
- Service bisa dipanggil dari test tanpa HTTP layer.

---

## Fase 5 - Rapikan Blueprint dan Wiring App

Tujuan: `main.py` jadi bootstrap, bukan campur route + business logic.

- [X] Pindahkan route health ke `app/routes/health.py`.
- [X] Pindahkan route telemetry ke `app/routes/telemetry.py`.
- [X] Register semua blueprint di satu tempat yang jelas.
- [X] `main.py` fokus ke init app, init dependency, start background loop.

DoD:

- Tidak ada endpoint business route yang didefinisikan langsung di `main.py`.
- Struktur project kebaca jelas dari folder `routes/`, `services/`, `utils/`.

---

## Fase 6 - Manual Test (Wajib Sebelum MAVSDK Action Real)

Tujuan: pastikan flow endpoint benar dulu sebelum nembak action MAVSDK sungguhan.

- [X] Test `GET /health` saat belum connect.
- [X] Test `GET /telemetry` saat belum connect.
- [X] Test `POST /command/arm` saat `connected=false`.
- [X] Simulasikan `connected=true`, test `POST /command/arm` sukses.
- [X] Test `POST /command/takeoff` dengan altitude invalid (string, <2, >50).
- [X] Test `POST /command/takeoff` dengan altitude valid.

Contoh cepat:

```bash
curl -X POST http://127.0.0.1:5001/command/arm
curl -X POST http://127.0.0.1:5001/command/takeoff -H "Content-Type: application/json" -d '{"altitude_m":10}'
```

DoD:

- Semua test manual di atas menghasilkan status code dan body sesuai kontrak.

---

## Fase 7 - Integrasi MAVSDK Action Real

Tujuan: ganti placeholder sukses jadi action asli.

- [X] Implement panggilan MAVSDK action untuk `arm/disarm/takeoff/land`.
- [X] Tambah timeout handling.
- [X] Map exception MAVSDK ke `ErrorCode` yang sesuai.
- [X] Tetapkan aturan retry/recover yang jelas saat koneksi drop.

DoD:

- Command benar-benar mengeksekusi action, bukan sekadar mock response.
- Failure dari MAVSDK tetap keluar sebagai response API yang rapi.

---

## Fase 8 - Hardening & Siap Dipakai Frontend

Tujuan: stabil untuk dipakai tim lain.

- [X] Tambah logging request/response command penting.
- [X] Tambah unit test untuk validator dan command service.
- [X] Tambah integration smoke test endpoint utama.
- [X] Bersihkan TODO lama yang sudah tidak relevan.

DoD:

- Jalur command utama punya test minimum.
- Tidak ada warning/error statik di workspace Python backend.

---

## Definition of Done (Akhir)

- [ ] State tunggal, tanpa race/conflict antar endpoint.
- [ ] Semua command endpoint pakai kontrak response yang sama.
- [ ] Route tipis, service dominan.
- [ ] Manual test pass.
- [ ] Action MAVSDK real sudah terintegrasi dan ditangani error-nya.
