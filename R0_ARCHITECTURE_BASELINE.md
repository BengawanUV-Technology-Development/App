# R0 Architecture Baseline

Status dokumen: **normatif untuk redevelopment R0**.

Dokumen ini adalah acuan arsitektur untuk batch berikutnya. Ia tidak menyatakan
bahwa seluruh kontrak R0 sudah tersedia di runtime saat ini. Perbedaan antara
target dan implementasi aktual harus dilaporkan secara eksplisit sebelum fitur
baru dikerjakan.

## 1. Topologi target

### MAVLink

```text
Pixhawk
→ Telemetry Radio
→ Ground Laptop
→ MAVLink router
   ├─ QGroundControl
   ├─ Mission Planner (optional destination)
   └─ Flask Backend
        → React Website
```

Ground Laptop adalah tempat distribusi MAVLink. Pixhawk tetap menjadi flight
authority. Website adalah consumer telemetry dan tidak memiliki authority untuk
mengirim flight command, mission command, parameter write, atau reboot ke
Pixhawk.

Pada implementasi repository saat ini, peran router dijalankan oleh custom
Python `pymavlink` fan-out. Script tersebut memiliki output QGC dan Flask secara
default, serta destination Mission Planner opsional yang dikonfigurasi terpisah.
Operasi simultan live GCS tetap perlu diverifikasi dengan hardware. Migrasi ke
`mavlink-router` resmi merupakan future development dan bukan scope R0.

### Vision

```text
Arducam
→ Jetson
   ├─ high-resolution local recording
   └─ H.264/RTP/UDP
       → Ground Flask/GStreamer
       → MJPEG HTTP
       → React <img>
```

Jetson memiliki camera capture, high-resolution evidence, frame metadata, dan
nantinya YOLO detection. Ground memiliki telemetry, web backend, dan post-flight
coordinate reconstruction adapter pada batch R2; live coordinate reconstruction
tetap bukan bagian runtime R0.

R0 tidak mengganti transport video yang sudah ada dengan WebSocket, WebRTC,
HLS, RTSP, atau transport besar lainnya.

## 2. Mission contract

Satu aksi `Start Record` membuat satu mission baru.

```text
React
→ Ground Flask
→ Jetson
→ create/use mission_id
→ start recording
```

Ground dan Jetson wajib menggunakan `mission_id` yang sama. `Stop Record`
menutup mission. Jika capture restart di tengah mission, `mission_id` tetap
sama dan `capture_epoch` bertambah.

Ground menyimpan:

- `mission_id`;
- waktu mulai dan selesai;
- status mission;
- telemetry log;
- referensi mission/data di Jetson.

Jetson menyimpan:

- `mission_id`;
- high-resolution video;
- frame metadata;
- detection pada batch berikutnya.

High-resolution evidence tetap berada di Jetson. Ground hanya mengambil data
mission tertentu ketika diminta; transfer otomatis seluruh video bukan bagian
R0.

## 3. Frame identity

Canonical frame metadata:

```text
mission_id
capture_epoch
frame_id
camera_id
capture_utc_ns
capture_monotonic_ns
source_pts_ns
```

Keputusan desain R0 adalah membawa `frame_id` melalui custom RTP header
extension dan mempertahankan `source_pts_ns` dari capture source Jetson. Ground
tidak boleh membuat ulang `source_pts_ns`. Ground dapat menggunakan `frame_id`
untuk lookup metadata lengkap.

Preview pipeline repository masih mengirim H.264/RTP dan Ground
mempublikasikan JPEG terbaru tanpa identity/PTS. High-resolution recording
agent remote menulis identity/PTS ke epoch-scoped `frames.jsonl`; validator
lokal tersedia di `jetson/frame_metadata.py`. Artifact bench sudah tervalidasi.
Flight artifact acceptance dan inference offline pada footage nyata adalah
pekerjaan R2; live detection bukan runtime R0.

## 4. Clock dan telemetry synchronization

Kontrak waktu operasi adalah **UTC Global**. Ground dan Jetson menggunakan waktu
UTC dari system clock masing-masing; Jetson diasumsikan tetap hidup selama
operasi penerbangan. Sinkronisasi khusus Ground–Jetson dengan chrony/NTP tidak
menjadi dependency runtime maupun gate acceptance R2.

Asumsi Jetson selalu hidup tidak dengan sendirinya membuktikan akurasi UTC.
Artifact tetap wajib menyimpan timestamp UTC dan domain clock secara eksplisit
agar korelasi dapat diaudit.

Setiap telemetry Ground harus membedakan:

```text
source_timestamp
receive_timestamp
```

`receive_timestamp` hanya untuk observability dan latency debugging. Timeline
utama untuk korelasi adalah `source_timestamp` yang valid pada clock domain UTC
yang sama dengan `capture_utc_ns`.

Jika MAVLink message hanya menyediakan `time_boot_ms`, `time_usec`, atau
timestamp lain yang bukan UTC, sistem wajib membuat mapping/normalisasi terlebih
dahulu. Nilai tersebut tidak boleh dibandingkan langsung dengan UTC
nanoseconds.

Target korelasi R2:

```text
frame.capture_utc_ns
        +
telemetry.source_timestamp
        ↓
telemetry interpolation
        ↓
vehicle state pada waktu capture frame
```

Mapping source timestamp ke UTC dan interpolasi tetap merupakan fondasi R2.
Helper chrony/NTP yang masih ada di `scripts/` bukan prosedur operasi aktif dan
tidak boleh dijadikan prasyarat pengujian.

## 5. Audit implementasi saat ini

| Area | Implementasi aktual | Status terhadap R0 |
| --- | --- | --- |
| MAVLink router | Custom Python `pymavlink`; QGC `14550`, optional Mission Planner destination, Flask `14551` | Fan-out destination tersedia; simultaneous live GCS operation tetap perlu hardware verification |
| Website authority | Backend UDP receive-only; command/mission route `403 READ_ONLY` | Sesuai |
| Preview video | Jetson H.264/RTP/UDP; Ground GStreamer; Flask MJPEG; React `<img>` | Sesuai transport |
| Camera source | CSI/Arducam dan EasyCAP analog dengan selector | Lebih luas dari single Arducam R0; keputusan scope perlu dikunci |
| Recording control | React → Flask → authenticated Jetson agent | Ground mengirim `mission_id`; bench remote contract terverifikasi |
| Ground mission storage | `missions/<mission_id>/telemetry.jsonl`, versioned mission-scoped JSONL | R1 implementation tersedia |
| Frame metadata | Remote agent writes epoch-scoped `frames.jsonl`; local `jetson/frame_metadata.py` validates canonical fields | Bench verified; flight artifact and offline inference acceptance are the R2 work item |
| Telemetry time | Per-sample source/receive nanosecond metadata | UTC mapping valid bila source mapping tersedia; invalid source time dipertahankan |
| Clock sync | UTC Global pada system clock Ground dan Jetson; `receive_timestamp` tetap dipisahkan dari source time | Tidak ada dependency chrony/NTP khusus; audit dilakukan dari field UTC dan source clock domain pada artifact |
| YOLO/reconstruction | Runner offline `postflight/offline_yolo.py` dan adapter `postflight/coordinate_reconstruction.py` tersedia; live detector/estimator tidak aktif di runtime | R2 offline geometry tersedia; calibration, AGL, mounting convention, ground truth, dan real qualification masih pending |
| Post-flight replay | `postflight/replay.py` memasangkan frame metadata dengan telemetry source-time; UI/3D replay belum aktif | Metadata/telemetry replay tersedia; pemeriksaan video fisik dilakukan bila file video diberikan |

## 6. Scope R0

Jangan mengimplementasikan pada batch dokumentasi/fondasi ini:

- YOLO atau detection pipeline;
- live coordinate reconstruction atau auto-geotagging;
- AI Agent, Telegram, atau Notion;
- flight command, mission command, parameter write, atau command system baru;
- MAVLink Anywhere, Internet/4G/5G fallback, atau link failover;
- penggantian transport video;
- WebSocket detection/telemetry sebagai jalur baru.

MAVLink Anywhere dan Internet fallback dicatat sebagai future development saja,
bukan dependency runtime R0.

## 7. Discrepancy yang ditunda ke batch berikutnya

1. Verifikasi dengan hardware output simultan Mission Planner/QGC tanpa merusak
   jalur QGC dan receive-only Flask.
2. Pastikan mapping source timestamp ke UTC konsisten dan dapat diaudit pada
   artifact flight; tidak ada pre-flight chrony gate.
3. Pisahkan telemetry interpolation dari telemetry receive-time observability.
4. Putuskan apakah branch analog/EasyCAP tetap berada di luar atau di dalam
   baseline single-Arducam R0.
5. Lengkapi full inference offline R2 pada segmen footage nyata yang memiliki
   target visual, lalu join detection terhadap telemetry pada capture yang sudah
   lolos temporal synchronization. Capture radio telemetry terbaru sudah lulus
   korelasi frame–telemetry dan positive detection sudah ditemukan pada footage
   lain. Adapter coordinate reconstruction dan synthetic geometry test sudah
   tersedia, tetapi belum ada pasangan mission same-time dengan AGL/calibration
   yang tervalidasi. Manual detection/review sengaja tetap menjadi future work.

## 8. File audit utama

- `scripts/mavlink_readonly_router.py`
- `src-tauri/src-py/app/services/readonly_mavlink.py`
- `src-tauri/src-py/app/services/camera_stream.py`
- `src-tauri/src-py/app/routes/recording.py`
- `src-tauri/src-py/app/services/jetson_recording.py`
- `jetson/camera_stream_service.py`
- `src/components/recording/CameraPreview.jsx`
- `src-tauri/src-py/app/utils/session_log.py`
- `README.md`
- `MAVLINK_SETUP.md`
- `GEMINI.md`
- `SHORT_FLIGHT_TEST.md`
- `COORDINATE_ESTIMATOR_AUDIT.md`
