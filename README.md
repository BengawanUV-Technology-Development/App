# Mission Planner

**Bengawan UAV – Technology Development Team**

---

## Overview

Mission Planner adalah aplikasi ground control station (GCS) yang dikembangkan oleh Technology Development Team Bengawan UAV untuk mendukung perencanaan, eksekusi, dan analisis misi UAV secara terintegrasi.

Aplikasi ini sedang dikembangkan untuk mendukung **Misi Search and Rescue
(SAR)**. Integrasi AI/Computer Vision merupakan roadmap setelah fondasi R0,
bukan capability aktif pada runtime telemetry-only saat ini.

> **R0 architecture baseline:** lihat [R0_ARCHITECTURE_BASELINE.md](./R0_ARCHITECTURE_BASELINE.md).
> Dokumen tersebut adalah acuan redevelopment dan membedakan target R0 dari
> implementasi yang sudah tersedia.

> **Mode integrasi saat ini: telemetry-only.** Webapp hanya membaca data
> MAVLink. Semua command flight, mission, parameter, dan koneksi serial dari
> webapp dinonaktifkan. QGroundControl tetap menjadi ground station yang
> memiliki akses command penuh.

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

Runtime R0 saat ini menyediakan monitoring telemetry read-only dan live camera
preview. YOLO, bounding-box detection, auto-marking, geotagging, dan coordinate
reconstruction adalah roadmap batch berikutnya; dokumentasi fitur tersebut tidak
boleh dibaca sebagai fitur aktif.

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
* **Future**: Post-flight analysis, 3D replay, dan pengambilan evidence video
  tertentu dari Jetson.

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

Implementasi R1 sekarang membuat `mission_id` dan Ground
`missions/<mission_id>/telemetry.jsonl` per recording. Recording agent Jetson
yang terpasang menulis `epochs/<capture_epoch>/frames.jsonl` dari source
capture callback; `jetson/frame_metadata.py` menyediakan validator yang
kompatibel untuk audit artifact.

Prosedur short-flight dan offline synchronization tersedia di
[`SHORT_FLIGHT_TEST.md`](./SHORT_FLIGHT_TEST.md).

Aktivasi dan verifikasi clock Ground–Jetson tersedia di
[`CHRONY_SETUP.md`](./CHRONY_SETUP.md); helper-nya memasang chrony, mengatur
service saat boot, menyimpan backup konfigurasi lama, dan menyediakan profil
Windows berbasis `W32Time`.

MAVLink Anywhere, Internet fallback, dan link failover bukan dependency saat ini
dan hanya dicatat sebagai future development.

---

## Instalasi backend telemetry-only

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

# Jalankan backend telemetry-only
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

```
mission-planner/
│── src/                # Source code utama
│── configs/            # File konfigurasi parameter
│── assets/             # UI, icon, dan map assets
│── logs/               # Data log penerbangan
│── simulation/         # 3D replay & simulation
│── tests/              # Unit & integration tests
│── docs/               # Dokumentasi
│── main.py             # Entry point aplikasi
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
