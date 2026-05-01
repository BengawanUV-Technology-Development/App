# Mission Planner

**Bengawan UAV – Technology Development Team**

---

## Overview

Mission Planner adalah aplikasi ground control station (GCS) yang dikembangkan oleh Technology Development Team Bengawan UAV untuk mendukung perencanaan, eksekusi, dan analisis misi UAV secara terintegrasi.

Aplikasi ini memiliki fokus khusus pada **Misi Search and Rescue (SAR)**, di mana UAV dibekali dengan kecerdasan buatan untuk membantu tim penyelamat menemukan korban bencana secara lebih cepat dan akurat melalui teknologi Computer Vision.

---

## Fitur Utama & SAR Intelligence

### 1. Computer Vision Victim Detection
* **Real-Time Object Detection**: Menggunakan pipeline AI (YOLO/PyTorch) untuk mendeteksi tanda-tanda keberadaan korban (pakaian, bagian tubuh, dll) langsung dari stream video UAV.
* **Visual Bounding Box**: Menampilkan kotak deteksi secara real-time pada interface operator untuk memudahkan identifikasi.

### 2. Auto-Marking & Geotagging
* **Precision Geotagging**: Menghitung koordinat GPS objek di darat secara otomatis dengan menggabungkan data posisi UAV, altitude, attitude (gyro), dan sudut kamera.
* **Instant Map Markers**: Setiap temuan akan langsung ditandai di peta digital sebagai Point of Interest (POI) permanen untuk disurvei oleh tim darat.

### 3. Koneksi & Sistem Dasar
* **Connect Telemetri**: Koneksi langsung ke UAV melalui modul telemetri via MAVLink.
* **Flight Control**: Kontrol status ARM/DISARM dan sistem dasar flight controller.

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

## Instalasi

### Prasyarat

* OS: Windows / Linux
* Python / environment sesuai stack
* UAV / simulator kompatibel

### Langkah Instalasi

```bash
git clone https://github.com/BengawanUV-Technology-Development/App

# Install dependencies
pip install -r requirements.txt

# Jalankan aplikasi
python main.py
```

---

## Cara Penggunaan

1. Jalankan aplikasi Mission Planner
2. Hubungkan telemetri UAV
3. Lakukan ARM jika sistem siap
4. Pilih flight mode sesuai kebutuhan
5. Buat dan upload waypoint mission
6. Monitor UAV melalui HUD dan map
7. Setelah flight, analisis data log

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