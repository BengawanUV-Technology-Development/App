# Jetson capture-only flight workflow

Dokumen ini menjelaskan mode penerbangan yang hanya merekam footage dan
telemetry. YOLO tidak dijalankan di Jetson; deteksi dilakukan setelah flight
selesai.

## Tujuan dan batasan

- Jetson menjadi pemilik capture dan penyimpanan evidence.
- Mission Planner tidak diperlukan untuk proses recording.
- Telemetry dibaca secara read-only dari MAVLink Router.
- Jika flight controller belum mengirim MAVLink, recording tetap berjalan dan
  field telemetry ditulis sebagai `null` dengan status yang eksplisit.
- Coordinate reconstruction belum dijalankan oleh capture pipeline; hasilnya
  menjadi tahap offline setelah detection tersedia.

## Jalur data

```text
Arducam/Argus
    └── arducam_split_pipeline.py
          ├── high-res H.264 ──► video.mp4 (SSD Jetson)
          ├── frame PTS ────────► telemetry.jsonl (SSD Jetson)
          ├── empty detection ─► detections.jsonl (SSD Jetson)
          └── low-res H.264/RTP/UDP ──► laptop web app

Flight controller ── MAVLink ──► mavlink-router ──► TCP 127.0.0.1:5760
                                                       │ read-only
                                                       ▼
                                             telemetry collector
```

`JETSON_RECORD_DIR` harus menunjuk ke mountpoint SSD, misalnya:

```text
/media/<user>/<ssd-label>/flight-recordings
```

Jangan menggunakan `/home` sebagai fallback untuk video.

## Isi session

```text
<session>/
├── video.mp4
├── metadata.json
├── telemetry.jsonl
└── detections.jsonl
```

`metadata.json` berisi status session, konfigurasi resolusi/FPS, identitas
frame, konfigurasi detector, sumber telemetry, dan daftar sidecar.

`telemetry.jsonl` memiliki satu row per frame pada mode capture-only. Kunci
penggabungan adalah `frame_id`; `pts_ns`, `captured_at_unix`, dan
`capture_timestamp_ns` membantu validasi timing. Snapshot aktual berada pada
object `telemetry` dan mencakup, bila tersedia:

- latitude, longitude, altitude relatif dan AMSL;
- roll, pitch, yaw, heading;
- groundspeed dan vertical speed;
- GPS fix, HDOP, VDOP, jumlah satelit;
- armed, flight mode, vehicle type;
- battery voltage, current, dan percentage.

`telemetry_status` dapat bernilai `ACTIVE`, `STALE`, `NO_DATA`, atau
`SOURCE_OFFLINE`. Nilai `null` dengan status offline adalah hasil yang valid,
bukan GPS dummy.

`detections.jsonl` tetap dibuat walaupun YOLO off. Setiap row capture-only
memiliki:

```json
{
  "detector": {
    "enabled": false,
    "status": "DISABLED",
    "reason": "YOLO_DISABLED_CAPTURE_ONLY"
  },
  "bbox": null,
  "detections": [],
  "coordinate": {
    "status": "UNAVAILABLE",
    "latitude": null,
    "longitude": null
  }
}
```

## Preflight sebelum UAV diterbangkan

Di Jetson, pastikan kamera, recording agent, SSD, dan telemetry telah diperiksa:

```bash
findmnt -T /media/<user>/<ssd-label>/flight-recordings
test -w /media/<user>/<ssd-label>/flight-recordings
systemctl is-active nvargus-daemon.service
systemctl is-active buv-recording-agent.service
ls -l /dev/ttyACM0
curl -sS http://127.0.0.1:9070/api/v1/diagnostics
```

Untuk telemetry aktual, diagnostics harus menunjukkan MAVLink aktif dan nilai
`heartbeats`/`bytesReceived` bertambah. Jika `/dev/ttyACM0` belum ada atau
router belum aktif, jangan menganggap telemetry flight tersedia. Kamera masih
bisa diuji, tetapi sidecar akan mencatat `SOURCE_OFFLINE`.

Recording dimulai dari web app laptop atau endpoint backend yang sudah ada:

```text
POST /api/v1/recordings/start
POST /api/v1/recordings/stop
```

Setelah stop, tunggu status `COMPLETED` sebelum memindahkan session atau
mematikan Jetson. EOS/SIGINT diperlukan agar MP4 selesai difinalisasi.

## Pengolahan setelah flight

1. Pertahankan session asli sebagai evidence.
2. Jalankan YOLO/SAHI offline pada `video.mp4` atau frame hasil ekstraksi.
3. Simpan hasil detector sebagai `detections-yolo.jsonl`, bukan menimpa
   `detections.jsonl` capture-only.
4. Pertahankan `frame_id` dan koordinat bbox high-res/normalized.
5. Gabungkan `detections-yolo.jsonl` dengan `telemetry.jsonl` berdasarkan
   `frame_id` atau timestamp terdekat.
6. Jalankan coordinate reconstruction setelah intrinsic/extrinsic kamera,
   altitude, reference frame, dan ground plane dikonfigurasi.

Estimator lama masih menggunakan format CSV, sehingga adapter JSONL dan
kalibrasi harus dilakukan sebelum koordinat dianggap valid.

## Runtime files

- `jetson/arducam_split_pipeline.py`: capture, frame identity, video, dan
  sidecar writer.
- `jetson/mavlink_telemetry.py`: parser MAVLink read-only melalui TCP lokal.
- `jetson/recording_agent.py`: HTTP lifecycle control.
- `src-tauri/src-py/tests/test_mavlink_telemetry.py`: test parser dan schema
  placeholder.
