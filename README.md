# Mission Planner

**Bengawan UAV – Technology Development Team**

---

## Overview

Mission Planner adalah aplikasi ground control station (GCS) yang dikembangkan oleh Technology Development Team Bengawan UAV untuk mendukung perencanaan, eksekusi, dan analisis misi UAV secara terintegrasi.

Aplikasi ini sedang dikembangkan untuk mendukung **Misi Search and Rescue
(SAR)**. Runtime live tetap receive-only untuk MAVLink, sementara recording
path Jetson sekarang memiliki optional low-rate YOLO callback ke Ground. Offline
inference dan replay tetap tersedia untuk audit footage. Status dan progress
lintas tahap dipelihara di bagian
[Progress proyek](#progress-proyek).

> **R0 architecture baseline:** lihat [R0_ARCHITECTURE_BASELINE.md](./R0_ARCHITECTURE_BASELINE.md).
> Dokumen tersebut adalah acuan redevelopment dan membedakan target R0 dari
> implementasi yang sudah tersedia.

> **Batas keamanan saat ini: telemetry-only untuk MAVLink.** Webapp hanya
> membaca data MAVLink dan metadata/detection dari pipeline. Semua command
> flight, mission, parameter, dan koneksi serial dari webapp dinonaktifkan.
> QGroundControl tetap menjadi ground station yang memiliki akses command
> penuh.

## Arsitektur MAVLink read-only

Router MAVLink menjadi satu-satunya proses yang membuka serial Pixhawk. Router
menggandakan telemetry ke jalur GCS, optional Mission Planner, dan web:

```text
Pixhawk serial
      │
      ▼
read-only MAVLink router
      ├── UDP 14550 ──► QGroundControl (telemetry + command)
      ├── UDP 14552 ──► Mission Planner (optional telemetry + command)
      └── UDP 14551 ──► web backend (receive-only telemetry)
                              │
                              └── GET /telemetry ──► web UI
```

Backend web tidak membuka `/dev/cu.*`, COM port, atau koneksi MAVSDK ke
flight controller. Receiver-nya menggunakan UDP `recvfrom` saja. Semua route
di `/command/*` dan `/mission/*` menjawab `403 READ_ONLY`; jadi request HTTP
yang keliru tidak dapat diteruskan ke Pixhawk.

---

## Scope R0 dan roadmap SAR

Runtime R0 menyediakan monitoring telemetry read-only dan live camera preview.
Sebagai extension R2, service recording Jetson dapat menjalankan custom YOLO
secara low-rate dan mengirim event detection kecil ke Ground. Ground menyimpan
event tersebut setelah join ke telemetry source-time. Coordinate reconstruction
live tersedia sebagai jalur opt-in, tetapi default-nya disabled sampai calibration,
AGL, mounting, dan ground truth tervalidasi. Auto-marking, geotagging
terkalibrasi, dan manual detection/review tetap future work.

### Koneksi dan sistem dasar
* **Connect Telemetri**: Telemetry diterima dari router melalui UDP MAVLink.
* **Flight Control**: Command flight dilakukan melalui QGroundControl atau GCS
  yang ditetapkan dalam topologi R0, bukan melalui website.
* **Live camera**: Jetson mengirim H.264/RTP/UDP; Ground mengubahnya menjadi
  MJPEG HTTP untuk React.

### Flight Modes & Navigasi
* **Multi-Mode Support**: MANUAL, FBWA, AUTO (Waypoint), Q_STABILIZE, Q_HOVER, dan Q_LAND.
* **GPS & Maps Integration**: Tampilan peta berbasis koordinat real-time dengan tracking posisi UAV yang presisi.

Daftar mode dan parameter di dokumen lama adalah konteks GCS/QGroundControl;
website tetap monitoring-only dan tidak menjadi command authority.

### 5. Monitoring & Visualisasi (HUD)
* **Advanced HUD**: Informasi attitude (roll, pitch, yaw), airspeed, altitude, dan heading dalam satu tampilan intuitif.
* **Real-Time Telemetry**: Status kesehatan sistem UAV yang terpantau setiap detik.

---

### Data Logging & Analisis

* **Current**: Ground menyimpan telemetry/event JSONL pada session backend.
* **R0 target**: Ground menyimpan telemetry dan metadata per `mission_id`.
* **R2**: Post-flight inference, sinkronisasi detection terhadap timestamp
  source, optional low-rate Jetson inference callback, dan adapter coordinate
  reconstruction diuji dari evidence video Jetson.
* **Current R2**: Replay validator offline dapat memasangkan setiap frame
  dengan state telemetry berdasarkan capture UTC. Saat recording aktif, Ground
  juga menulis `detections_with_telemetry.jsonl` tanpa menyalin video besar.
* **Future**: UI/3D replay interaktif, calibrated coordinate qualification,
  auto-marking/geotagging, manual detection/review, dan link failover.

  High-resolution evidence tetap berada di Jetson; transfer otomatis seluruh
  video bukan bagian R0.

---

## Fitur Opsional (Advanced Configuration)

### 1. Pre-Flight & Kalibrasi

* Pre-flight Airspeed Calibration
* Compass Calibration
* Level Calibration
* Accelerometer Calibration

---

### 2. Hardware Testing

* Motor Test
* Sensor validation

---

### 3. Parameter Configuration

Konfigurasi parameter lanjutan untuk tuning sistem:

#### VTOL & Frame Configuration

* `Q_ENABLE`
* `Q_FRAME_CLASS`
* `Q_FRAME_TYPE`
* `Q_TILT_ENABLE`
* `Q_TILT_MASK`

#### Airspeed Configuration

* `ARSPD_USE`
* `ARSPD_TYPE`
* `ARSPD_PIN`
* `ARSPD_AUTOCAL`
* `ARSPD_FBW_MIN`

#### Servo & Control

* `SERVO[X]_FUNCTION`

#### Flight Behavior & Transition

* `Q_VFWD_GAIN`
* `Q_RTL_MODE`
* `Q_TRANS_FAIL`
* `Q_TRANS_DURATION` / `Q_TRANSITION_MS`

---

## Arsitektur Sistem

Topologi target, mission contract, frame identity, clock contract, dan
discrepancy implementasi dijelaskan di
[R0_ARCHITECTURE_BASELINE.md](./R0_ARCHITECTURE_BASELINE.md).

Implementasi R1 membuat `mission_id` dan Ground
`missions/<mission_id>/telemetry.jsonl` per recording. Runtime Jetson kanonis
berada di `/home/bengawan/Documents/app-mavproxy`; recording agent yang
terpasang menulis `epochs/<capture_epoch>/frames.jsonl` dari source capture
callback. `jetson/frame_metadata.py` menyediakan validator yang kompatibel
untuk audit artifact. Detail file, unit systemd, env machine-only, dan prosedur
deploy ada di [`jetson/README.md`](./jetson/README.md).

Prosedur short-flight dan offline synchronization tersedia di
[`SHORT_FLIGHT_TEST.md`](./SHORT_FLIGHT_TEST.md).

Audit repository `Coordinate-Estimator`, mapping input, adapter, dan limitasi
calibration tersedia di
[`COORDINATE_ESTIMATOR_AUDIT.md`](./COORDINATE_ESTIMATOR_AUDIT.md).

Kontrak waktu saat ini adalah **UTC Global**. `capture_utc_ns` pada Jetson dan
`source_timestamp` telemetry yang valid harus berada pada domain UTC yang sama;
`receive_timestamp` hanya dipakai untuk observability. Chrony/NTP khusus
Ground–Jetson bukan lagi dependency atau gate R2.

MAVLink Anywhere, Internet fallback, dan link failover bukan dependency saat ini
dan hanya dicatat sebagai future development.

## Progress proyek

Bagian ini adalah sumber progress utama. Dokumen prosedur hanya menjelaskan
cara verifikasi dan tidak boleh mengubah status implementasi di sini.

| Tahap | Status | Ringkasan |
| --- | --- | --- |
| R0 | Baseline tersedia | Telemetry receive-only, router MAVLink, live camera preview, dan command authority tetap berada pada QGroundControl/GCS yang ditetapkan. |
| R1 | Fondasi tersedia | `mission_id`, mission-scoped telemetry JSONL, canonical frame metadata, source PTS, UTC/source-time fields, dan validator artifact tersedia. |
| R2 | Inference, temporal sync, live detection callback, coordinate adapter, map-dot smoke, dan replay validator tersedia; qualification tertahan | Positive detection nyata dan visual bbox sudah lulus. Existing interpolator tetap dipakai. Custom model Jetson sudah dikonfigurasi melalui runtime terpisah; event callback, bounded retry, Ground join, synthetic geometry, rendering dot ke MapLibre, serta replay metadata/telemetry lulus secara software. Mission same-time dengan target, AGL, calibration intrinsics/distortion, mounting extrinsics, ground truth, dan hardware/browser E2E masih belum tervalidasi. Coordinate live default disabled. |
| Future work | Belum dikerjakan | Calibrated coordinate qualification, auto-marking/geotagging, manual detection/review, UI/3D replay interaktif, dan link failover. |

### Snapshot pengujian lokal

Pada 2026-08-29, suite backend Python (59), Jetson (16), postflight (21), dan
scripts (5) lulus; frontend map contract test (4) dan production build juga
lulus. Belum ada
browser/E2E test atau hardware flight acceptance. `cargo test` berhasil
melakukan compile test harness, tetapi crate saat ini tidak memiliki test case.
Sebanyak 18 test berada pada suite coordinate/replay (16 geometri/integrasi
coordinate dan 2 replay frame–telemetry), ditambah 3 test synchronization untuk
total 21 postflight test. Backend test mencakup live source-time timeline,
late-telemetry resolution, authenticated ingestion, deduplication, dan
recording lifecycle.

Smoke test frontend untuk kontrak dot coordinate dijalankan dengan:

```bash
npm run test:map
```

Hasilnya 4/4 test lulus: fixture menghasilkan satu point pada koordinat
`[longitude, latitude]`, status `NOT_AVAILABLE` disembunyikan dari peta, dan
response detection live hanya dipakai ketika backend menyatakan mission aktif;
poll yang gagal juga menghapus dot lama agar target stale tidak tertinggal.

Replay receive-only terhadap mission sinkron
`mission-27bd4805-50f3-4504-8046-4f297e50833f` juga lulus untuk 956 frame
metadata dan 423 source-time telemetry sample: 956/956 state lengkap, capture
duration 39,75 detik, dan tidak ada packet atau command yang dikirim. Runner-nya
ada di `postflight/replay.py`. Verifikasi pembacaan file video fisik membutuhkan
akses ke file 4K di Jetson; metadata replay tidak menggantikan pemeriksaan jumlah
frame video.

### Evidence R2 yang sudah ditemukan

Footage nyata yang dipilih berada di Jetson pada:

```text
/media/bengawan/nopal-ssd1/flight-recordings/mission-6f1ff7d6-c99d-4fe2-80bc-3544180868a9/epochs/0001/
```

`video.mp4` berukuran sekitar 1,6 GB, H.264 3840×2160, dengan durasi probe
sekitar 1466 detik. Untuk pengujian, model yang dipilih adalah
`ghostv3_dwconv-seed0/weights/best.pt` dari folder hasil training Downloads
(SHA-256 `7c3c2dd5ecb0cc440f4ae9b7add6a9493c1f6bbc9b6924f7d35a6e250ad7727f`).
Model yang sama sekarang dikonfigurasi di Jetson pada
`/home/bengawan/Documents/s-yolov11-main/ghostv3_dwconv-seed0/weights/best.pt`
dan dicatat di `jetson/production_model_ghostv3.json`. Checkpoint custom ini
membutuhkan source runtime `modules_ghost.py` serta `modules_sy.py`; file besar
tidak disalin ke Ground.
File `detections.jsonl` yang sudah ada bukan hasil R2 yang valid: artifact
tersebut berstatus detector `FAILED` karena paket Ultralytics tidak tersedia
pada runtime recorder dan seluruh detection-nya kosong; jangan memakai artifact
lama itu sebagai bukti keberhasilan.

Smoke test baru sudah berhasil dijalankan di staging Jetson:

- footage asli harus dibuat remux copy-only ke
  `/home/bengawan/r2-inference-staging/video-r2-remux.mp4` agar dapat dibuka
  OpenCV; file asli di SSD tidak diubah;
- sampel 10 frame diproses oleh `postflight.offline_yolo`: `frames_processed=10`
  dan `detections_written=1`;
- output berada di
  `/home/bengawan/r2-inference-staging/results/detections-ghostv3-sample10.jsonl`;
  record yang tertulis adalah `frame_id=4`, kelas `pedestrian`, confidence
  sekitar `0.5733`;
- runtime offline sebelumnya adalah Ultralytics 8.3.0 dengan patch custom
  GhostV3 dan CPU-only; smoke satu frame 3840×2160 memerlukan sekitar 5,39
  detik. Full-run offline epoch besar belum dijalankan karena tidak efisien.
- runtime live Jetson diverifikasi memakai custom Ultralytics 8.3.0 dan Torch
  `2.13.0+cu130`. Driver Jetson saat ini terlalu lama untuk CUDA runtime itu,
  sehingga `JETSON_MODEL_DEVICE=cpu` dipilih secara eksplisit; inference sample
  960×540 pada `imgsz=640`, confidence `0.25` menghasilkan `pedestrian` dengan
  confidence sekitar `0.4762` tanpa error.
- service `buv-recording-agent.service` aktif dan child inference memakai
  `/home/bengawan/Documents/Object-Detection/venv/bin/python` plus custom
  `PYTHONPATH`. Retry event callback diuji dengan satu planned failure lalu
  recovery (`sent=1`, `errors=1`, `dropped=0`). Full camera-to-Ground live E2E
  masih perlu dilakukan pada recording berikutnya.

Untuk epoch lama ini, acceptance penuh masih tertahan oleh tiga masalah artifact nyata: metadata
`frames.jsonl` valid sampai `frame_id=34340` lalu memiliki blok NUL pada baris
34342; `telemetry.jsonl` memiliki kerusakan ekor yang sama; dan video remux
terbaca OpenCV sebagai 34.439 frame, sehingga belum cocok dengan 34.341 frame
metadata valid. Telemetry pada epoch ini juga berstatus `SOURCE_OFFLINE`
karena `127.0.0.1:5760` connection refused dan tidak memiliki sample
`source_time_valid=true`. Sinkronisasi tidak boleh mengganti source time dengan
`receive_timestamp`.

### Uji sinkronisasi dengan radio telemetry

Pada 2026-08-28 dibuat capture Arducam CSI baru dengan radio telemetry Ground
yang diteruskan secara receive-only. Mission yang dihasilkan:

```text
mission-27bd4805-50f3-4504-8046-4f297e50833f
```

Hasil audit end-to-end:

- Jetson menulis 956 frame metadata (`frame_id=0..955`) dan video final dapat
  dibuka OpenCV sebagai tepat 956 frame, 3840×2160 pada sekitar 24,03 FPS;
- ground log memiliki 2.265 telemetry sample, 423 di antaranya
  `source_time_valid=true` dengan domain `fc_boot_ms_mapped_to_utc`;
- seluruh 956 frame memiliki bracket timestamp telemetry dan state lengkap
  (`latitude`, `longitude`, `altitude`, `roll`, `pitch`, `yaw`) melalui
  interpolasi linear;
- `telemetry_dropped_samples=0`. Ground log tersimpan di
  `src-tauri/src-py/runtime/logs/missions/<mission_id>/telemetry.jsonl`,
  sedangkan footage tetap berada di SSD Nopal Jetson.

Inference custom pada 10 frame dari mission yang sama juga memproses 10/10
frame tanpa error, tetapi menulis 0 detection pada threshold 0,25. Karena itu
temporal synchronization sudah lulus, sementara mission tersebut belum
memiliki record detection untuk dijoin. Runtime live agent yang sebelumnya
`FAILED` sudah diperbaiki dan dikonfigurasi dengan model/runtime custom, tetapi
full camera-to-Ground detection → telemetry acceptance tetap memerlukan
recording baru yang memuat target visual.

### Live inference callback R2

Saat `POST /api/v1/recordings/start` berhasil, Ground membuat mission yang sama
untuk telemetry, memulai timeline source-time, lalu meneruskan `mission_id` ke
Jetson. Recording agent Jetson mempertahankan high-resolution video dan
`frames.jsonl`, sementara child YOLO berjalan low-rate pada branch inference
terpisah. Detection queue dibatasi agar inference lambat tidak menghentikan
capture. Event kecil dikirim ke:

```text
POST /api/v1/detection/ingest
POST /api/v1/detection/overlay
```

Ground hanya menerima event dengan mission/frame identity yang valid, memakai
`capture_utc_ns` dari event untuk interpolasi terhadap telemetry dengan
`source_time_valid=true`, lalu menulis:

```text
runtime/logs/missions/<mission_id>/detections_with_telemetry.jsonl
```

`overlay` hanya disimpan sebagai diagnostik; UI tidak menggambar bbox pada
preview. Dashboard melakukan polling detection terbaru dan hanya menampilkan
dot jika coordinate result berstatus `ESTIMATED_UNCALIBRATED` atau
`CALIBRATED_ESTIMATE` dengan koordinat valid. Karena calibration/AGL/mounting
belum tersedia, konfigurasi default `VISION_COORDINATE_ENABLED=false`, sehingga
live inference dan telemetry join dapat berjalan tanpa menghasilkan dot palsu.

Jika detection tiba sebelum telemetry source-time yang membungkus
`capture_utc_ns`, Ground mengembalikan `processing_status=pending_telemetry`
dan menahannya di queue bounded. Sampel telemetry berikutnya akan memicu
resolusi ulang; jika recording dihentikan lebih dulu, event tetap ditulis
sebagai `finalized_unsynchronized` dengan coordinate `NOT_AVAILABLE`. Duplicate
`detection_id` yang sama idempotent, sedangkan ID yang sama dengan payload
berbeda ditolak.

Endpoint `POST` selalu membutuhkan Bearer token. Endpoint `GET` dapat diakses
tanpa token hanya dari loopback untuk UI lokal; akses non-loopback membutuhkan
`VISION_READ_TOKEN` (atau fallback ke `VISION_INGEST_TOKEN`).

Ground harus memakai `VISION_INGEST_TOKEN` yang sama dengan
`JETSON_INGEST_TOKEN` di Jetson. `JETSON_GCS_HOST` harus berisi IP Tailscale
Ground yang dapat dijangkau Jetson; pada laptop Windows milik teman, jangan
menyalin IP contoh laptop lama. Backend juga harus bind ke interface yang dapat
dijangkau Jetson, misalnya `API_HOST=0.0.0.0` dengan `API_PORT=5001`, dan
firewall Windows harus mengizinkan koneksi TCP dari interface Tailscale.

### Coordinate reconstruction MVP

Audit dan adapter offline di
[`COORDINATE_ESTIMATOR_AUDIT.md`](./COORDINATE_ESTIMATOR_AUDIT.md) memakai
formulasi ray/ground dari repository `Coordinate-Estimator`, tanpa mengganti
interpolator telemetry. Adapter hanya menerima detection dengan
`telemetry_sync_status=synchronized`, memakai bbox center, dan menolak
synthetic clock alignment. Flat-ground MVP membutuhkan deklarasi AGL eksplisit,
intrinsics camera, serta mounting/attitude convention; `relative_altitude` dan
AMSL tidak otomatis dianggap AGL. Status coordinate output dapat berupa
`NOT_AVAILABLE`, `ESTIMATED_UNCALIBRATED`, atau `CALIBRATED_ESTIMATE`.

Belum ada coordinate qualification nyata: positive detection `frame_id=1919`
berasal dari footage 12 Agustus, sedangkan telemetry tambahan yang tersedia
berasal dari 25 Agustus. Prototype join 47/47 hanya digunakan untuk menguji
plumbing dan ditandai non-qualification.

#### Smoke test dot target pada peta

`OperationalMap` sekarang dapat menerima satu hasil coordinate reconstruction
eksplisit dan merendernya sebagai GeoJSON point di atas peta. Status
`ESTIMATED_UNCALIBRATED` ditampilkan sebagai dot amber, sedangkan
`CALIBRATED_ESTIMATE` sebagai dot hijau. Result `NOT_AVAILABLE` tidak
dirender.

Untuk membuka fixture smoke yang berasal dari deteksi pedestrian nyata pada
`frame_id=1919`, jalankan:

```bash
npm run dev
# buka http://localhost:5173/?coordinate_smoke_test=1
```

Fixture tersebut menggunakan coordinate hasil adapter yang sudah diperoleh
dari data sebelumnya, tetapi masih memakai synthetic clock alignment dan
asumsi AGL 10 m. Karena itu dot diberi label `TARGET · SMOKE` dan
`NON-QUALIFICATION`; ini hanya membuktikan plumbing coordinate result → map,
bukan akurasi target di lapangan. Pada URL normal, live dot baru muncul bila
Ground menerima detection yang tersinkron dan coordinate reconstruction
diaktifkan dengan konfigurasi eksplisit; default aman tetap tidak menampilkan
dot coordinate.

### Dokumentasi aktif dan retired

Dokumentasi aktif adalah `README.md` (progress utama),
`R0_ARCHITECTURE_BASELINE.md` (kontrak arsitektur), `SHORT_FLIGHT_TEST.md`
(prosedur R2), `MAVLINK_SETUP.md` (setup Ground), dan `jetson/README.md`
(runtime/deployment Jetson). Dokumen historis `CHRONY_SETUP.md` dan checklist
lama `src-tauri/src-py/step.md` sudah tidak digunakan dan dihapus;
progress-nya dipertahankan di bagian ini.

---

## Instalasi backend receive-only

Panduan setup lengkap untuk Windows PowerShell, macOS, dan Linux tersedia di
[MAVLINK_SETUP.md](./MAVLINK_SETUP.md).

### Prasyarat

* Python 3.10+
* Router MAVLink yang meneruskan telemetry ke UDP `127.0.0.1:14551`
* QGroundControl memakai UDP `14550`, bukan serial Pixhawk langsung

Konfigurasi ini menjalankan custom Python router. Untuk memakai Mission Planner
bersamaan, tambahkan destination yang berbeda dari QGC, misalnya
`--mission-planner 127.0.0.1:14552` atau set
`MAVLINK_MISSION_PLANNER_ADDRESS=127.0.0.1:14552`.

### Langkah Instalasi

```bash
git clone --branch main https://github.com/BengawanUV-Technology-Development/App
cd App

# Install dependencies backend
python3 -m pip install -r src-tauri/src-py/requirements.txt

# Jalankan backend receive-only
./src-tauri/src-py/start_readonly_backend.sh
```

Endpoint verifikasi:

```bash
curl http://127.0.0.1:5001/health
curl http://127.0.0.1:5001/capabilities
curl http://127.0.0.1:5001/telemetry
```

Percobaan command dari webapp harus ditolak:

```bash
curl -i -X POST http://127.0.0.1:5001/command/arm
# HTTP/1.1 403
# "error_code": "READ_ONLY"
```

---

## Cara menjalankan stack

Urutan yang disarankan:

1. Hentikan monitor UDP lama yang masih bind ke `14551` jika ada.
2. Jalankan `scripts/mavlink_readonly_router.py` dengan serial Pixhawk. Contoh:

   ```bash
   python3 scripts/mavlink_readonly_router.py \
     --serial /dev/cu.usbserial-DU0E7WRJ \
     --baud 57600
   ```

3. Jalankan `./src-tauri/src-py/start_readonly_backend.sh`.
4. Buka QGroundControl dan gunakan link UDP `14550`; jangan menambahkan link
   serial Pixhawk di QGC.

Untuk Windows PowerShell, gunakan:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\scripts\setup_mavlink_windows.ps1
.\scripts\start_mavlink_router.ps1 -SerialPort COM5 -Baud 57600
.\scripts\start_readonly_backend.ps1
```

Tidak ada ketergantungan koneksi yang ketat antara langkah 2–4: backend dan
QGC boleh dibuka lebih dahulu karena keduanya hanya menunggu datagram. Untuk
UX operasional, langkah tersebut nantinya dapat dibungkus dalam satu launcher
yang menampilkan status router, backend, dan QGC secara bersamaan.

Webapp hanya menampilkan telemetry. ARM, mode, parameter, mission, reboot, dan
command lain tetap dilakukan dari QGroundControl.

---

## Struktur Proyek

```text
App/
├── src/                 # Frontend React
├── src-tauri/src-py/    # Backend Ground receive-only
├── src-tauri/           # Shell Tauri
├── jetson/              # Source dan unit deployment Jetson kanonis
├── postflight/          # Inference, replay, sync, dan coordinate adapter
├── scripts/             # Router MAVLink dan utilitas setup
├── tests/               # Contract test frontend
├── README.md            # Progress utama
├── MAVLINK_SETUP.md     # Setup Ground
└── SHORT_FLIGHT_TEST.md # Prosedur R2
```

---

## Roadmap Pengembangan

* Integrasi AI untuk optimasi rute
* Peningkatan akurasi simulasi 3D
* UI/UX lebih intuitif
* Dukungan multi-UAV

---

## Kontribusi

* Gunakan branch terpisah untuk setiap fitur
* Ikuti coding standard tim
* Pastikan semua testing lolos sebelum PR

---

## Tim

**Bengawan UAV – Technology Development Team**

---

## Kontak

Silakan hubungi tim melalui kanal komunikasi internal Bengawan UAV untuk kolaborasi atau pertanyaan teknis.

---
