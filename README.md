# Mission Planner

**Bengawan UAV – Technology Development Team**

---

## Overview

Mission Planner adalah aplikasi ground control station (GCS) yang dikembangkan oleh Technology Development Team Bengawan UAV untuk mendukung perencanaan, eksekusi, dan analisis misi UAV secara terintegrasi.

Aplikasi ini memiliki fokus khusus pada **Misi Search and Rescue (SAR)**, di mana UAV dibekali dengan kecerdasan buatan untuk membantu tim penyelamat menemukan korban bencana secara lebih cepat dan akurat melalui teknologi Computer Vision.

> **Mode integrasi saat ini: telemetry-only.** Webapp hanya membaca data
> MAVLink. Semua command flight, mission, parameter, dan koneksi serial dari
> webapp dinonaktifkan. QGroundControl tetap menjadi ground station yang
> memiliki akses command penuh.

## Arsitektur MAVLink read-only

Router MAVLink menjadi satu-satunya proses yang membuka serial Pixhawk. Router
menggandakan telemetry ke dua jalur yang terpisah:

```text
Pixhawk serial
      │
      ▼
read-only MAVLink router
      ├── UDP 14550 ──► QGroundControl (telemetry + command)
      └── UDP 14551 ──► web backend (receive-only telemetry)
                              │
                              └── GET /telemetry ──► web UI
```

Backend web tidak membuka `/dev/cu.*`, COM port, atau koneksi MAVSDK ke
flight controller. Receiver-nya menggunakan UDP `recvfrom` saja. Semua route
di `/command/*` dan `/mission/*` menjawab `403 READ_ONLY`; jadi request HTTP
yang keliru tidak dapat diteruskan ke Pixhawk.

---

## Fitur Utama & SAR Intelligence

### 1. Computer Vision Victim Detection
* **Real-Time Object Detection**: Menggunakan pipeline AI (YOLO/PyTorch) untuk mendeteksi tanda-tanda keberadaan korban (pakaian, bagian tubuh, dll) langsung dari stream video UAV.
* **Visual Bounding Box**: Menampilkan kotak deteksi secara real-time pada interface operator untuk memudahkan identifikasi.

### 2. Auto-Marking & Geotagging
* **Precision Geotagging**: Menghitung koordinat GPS objek di darat secara otomatis dengan menggabungkan data posisi UAV, altitude, attitude (gyro), dan sudut kamera.
* **Instant Map Markers**: Setiap temuan akan langsung ditandai di peta digital sebagai Point of Interest (POI) permanen untuk disurvei oleh tim darat.

### 3. Koneksi & Sistem Dasar
* **Connect Telemetri**: Telemetry diterima dari router melalui UDP MAVLink.
* **Flight Control**: Command flight dilakukan melalui QGroundControl.

### 4. Flight Modes & Navigasi
* **Multi-Mode Support**: MANUAL, FBWA, AUTO (Waypoint), Q_STABILIZE, Q_HOVER, dan Q_LAND.
* **GPS & Maps Integration**: Tampilan peta berbasis koordinat real-time dengan tracking posisi UAV yang presisi.

### 5. Monitoring & Visualisasi (HUD)
* **Advanced HUD**: Informasi attitude (roll, pitch, yaw), airspeed, altitude, dan heading dalam satu tampilan intuitif.
* **Real-Time Telemetry**: Status kesehatan sistem UAV yang terpantau setiap detik.

---

### 5. Data Logging & Analisis

* **Data Log Recording**

  * Penyimpanan seluruh data penerbangan
* **Post-Flight Analysis**

  * Evaluasi performa UAV setelah misi
* **3D Model Simulation (Post-Flight)**

  * Visualisasi ulang flight dalam bentuk simulasi 3D

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

* **Frontend (UI/UX)**

  * Interface interaktif untuk operator
  * Visualisasi peta dan HUD

* **Backend**

  * Pengolahan data misi
  * Manajemen komunikasi UAV

* **Communication Layer**

  * Protokol MAVLink untuk komunikasi telemetri

* **Data Storage**

  * Penyimpanan mission plan dan log penerbangan

---

## Instalasi backend telemetry-only

Panduan setup lengkap untuk Windows PowerShell, macOS, dan Linux tersedia di
[MAVLINK_SETUP.md](./MAVLINK_SETUP.md).

### Prasyarat

* Python 3.10+
* Router MAVLink yang meneruskan telemetry ke UDP `127.0.0.1:14551`
* QGroundControl memakai UDP `14550`, bukan serial Pixhawk langsung

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
