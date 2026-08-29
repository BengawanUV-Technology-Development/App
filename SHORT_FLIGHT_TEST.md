# R2 Offline Inference / Post-Flight Synchronization

Dokumen ini adalah prosedur pengujian R2. Fokusnya adalah membuktikan rantai
temporal dan inference offline berikut, bukan coordinate reconstruction:

```text
video.mp4 + frames.jsonl + Ground telemetry.jsonl
    → offline YOLO
    → detections.jsonl
    → frame timestamp
    → source-time telemetry interpolation
```

Kontrak waktu operasi adalah UTC Global. Chrony/NTP khusus Ground–Jetson tidak
lagi menjadi dependency atau acceptance gate. Jetson diasumsikan tetap hidup
selama penerbangan; timestamp UTC pada artifact tetap wajib dapat diaudit.

## Artefak mission

Ground menyimpan telemetry di:

```text
runtime/logs/missions/<mission_id>/telemetry.jsonl
```

Jetson production agent menyimpan evidence di epoch capture:

```text
<mission_id>/mission.json
<mission_id>/epochs/<capture_epoch>/video.mp4
<mission_id>/epochs/<capture_epoch>/frames.jsonl
<mission_id>/epochs/<capture_epoch>/detections.jsonl
```

Validator menerima langsung direktori mission atau direktori epoch. Ground
telemetry tetap berada di `missions/<mission_id>/telemetry.jsonl`.

## Integrasi recording agent Jetson

Kontrak writer/validator lokal ada di `jetson/frame_metadata.py`. Agent remote
yang sedang terpasang sudah memiliki source-pad identity callback dan bounded
sidecar writer; bench deployment menghasilkan `frames.jsonl` dengan canonical
fields, PTS source, dan tanpa queue drop. Jangan menambahkan writer kedua ke
pipeline remote. Bila agent diganti, pola integrasinya tetap:

```python
from pathlib import Path

from jetson.frame_metadata import FrameMetadataWriter

frames = FrameMetadataWriter(
    Path(session_dir) / "frames.jsonl",
    mission_id=mission_id,
    camera_id="arducam-0",
    capture_epoch=capture_epoch,
)
frames.start()
```

Pada callback **source camera**, sebelum encoder/queue post-processing, panggil:

```python
frames.record_gst_buffer(
    buffer,
    frame_id=capture_frame_counter,
)
```

`record_gst_buffer()` menyalin `buffer.pts` sebagai `source_pts_ns` dan
mengambil `capture_utc_ns` serta `capture_monotonic_ns` pada callback tersebut.
Jangan mengisi `source_pts_ns` dari waktu Ground, waktu inference, atau waktu
ketika file video dibaca ulang. Pada Stop Record, panggil `frames.stop()` dan
pastikan `frames.status()["missing_source_pts"] == 0`.

Preview service saja tidak cukup karena berhenti saat recording pipeline
high-resolution aktif. Setelah perubahan agent, ulangi validator terhadap
epoch artifact sebelum flight.

## Validasi sebelum offline YOLO

Setelah video dan telemetry tersedia di satu host:

```bash
python3 -m jetson.validate_mission_artifacts \
  /path/to/<mission_id> \
  --telemetry /path/to/ground/missions/<mission_id>/telemetry.jsonl
```

Validator menolak kondisi berikut:

- `video.mp4` hilang atau kosong;
- `frames.jsonl` hilang, mission ID tidak konsisten, frame ID mundur/duplikat;
- `capture_utc_ns`, `capture_monotonic_ns`, atau `source_pts_ns` hilang/mundur;
- telemetry tidak memiliki `source_time_valid=true`.

Untuk korelasi R2, sample telemetry yang dipakai juga harus memiliki
`source_clock_domain` yang secara eksplisit menyatakan UTC epoch atau mapping
ke UTC (misalnya `utc_epoch_usec` atau `fc_*_mapped_to_utc`) dan
`source_timestamp` pada domain UTC yang sama dengan `capture_utc_ns`.
`receive_timestamp` tidak boleh menjadi fallback.

## Offline YOLO

Perintah ini tidak dijalankan oleh live recording service:

```bash
python3 -m postflight.offline_yolo \
  /path/to/<mission_id>/epochs/<capture_epoch>/video.mp4 \
  /path/to/<mission_id>/epochs/<capture_epoch>/frames.jsonl \
  /path/to/<mission_id>/epochs/<capture_epoch>/detections.jsonl \
  --model /path/to/model.pt \
  --device cuda:0
```

Runner memproses video sesuai urutan `frames.jsonl`. Perbedaan jumlah frame
dianggap error agar detection tidak bergeser ke frame yang salah. Setiap
detection menyimpan `detection_id`, `mission_id`, `frame_id`, timestamp,
class, confidence, pixel XYXY, dan normalized master-image XYXY.

## Sinkronisasi detection → telemetry

```bash
python3 -m postflight.synchronization \
  /path/to/<mission_id>/epochs/<capture_epoch>/detections.jsonl \
  /path/to/<mission_id>/epochs/<capture_epoch>/frames.jsonl \
  /path/to/ground/missions/<mission_id>/telemetry.jsonl \
  /path/to/<mission_id>/epochs/<capture_epoch>/synced-detections.jsonl
```

Tool ini hanya memakai sample telemetry dengan `source_time_valid=true`, lalu
mencari sample source-time sebelum dan sesudah `capture_utc_ns`. `receive_timestamp`
tidak pernah dipakai sebagai fallback. Output detection berisi:

```text
mission_id
frame_id
capture_utc_ns
latitude
longitude
altitude
roll
pitch
yaw
```

Coordinate reconstruction bukan bagian acceptance temporal R2. Adapter offline
MVP dan audit reference tersedia di
[`COORDINATE_ESTIMATOR_AUDIT.md`](./COORDINATE_ESTIMATOR_AUDIT.md); ia hanya
boleh dijalankan setelah detection memiliki real
`telemetry_sync_status=synchronized`. Synthetic clock alignment ditolak.

## Replay frame dan telemetry secara receive-only

Untuk memutar ulang timeline frame dan telemetry pada kecepatan capture asli,
gunakan runner offline berikut:

```bash
PYTHONPATH=. python3 -m postflight.replay \
  /path/to/<mission_id>/epochs/<capture_epoch>/frames.jsonl \
  /path/to/ground/missions/<mission_id>/telemetry.jsonl \
  /path/to/<mission_id>/replay.jsonl \
  --video /path/to/<mission_id>/epochs/<capture_epoch>/video.mp4 \
  --speed 1.0
```

`speed=1.0` mengikuti interval `capture_utc_ns` secara real-time. Runner
memakai interpolator source-time existing, memeriksa state lengkap pada setiap
frame, dan bila `--video` diberikan memastikan video memiliki tepat satu frame
yang dapat dibaca untuk setiap record metadata serta tidak memiliki frame ekor.
Gunakan `--no-sleep` untuk validasi cepat/CI. Tanpa `--video`, runner tetap
memvalidasi pasangan metadata–telemetry tanpa memindahkan file video besar dari
Jetson.

Replay ini tidak membuka MAVLink, tidak publish UDP, tidak mengirim command ke
Pixhawk, dan tidak mengubah evidence asli. Output `replay_frame` adalah artifact
diagnostik untuk post-flight; ini belum merupakan UI/3D replay interaktif.

Pada 2026-08-29, metadata-only replay mission radio terbaru berhasil
memproses 956/956 frame dengan 956/956 state lengkap, memakai 423 sample
telemetry `source_time_valid=true`, dan mengikuti durasi capture 39,75 detik.
Pembacaan video fisik secara langsung belum diulang pada run tersebut karena
koneksi ke Jetson sedang timeout; hasil sebelumnya tetap mencatat video mission
tersebut terbaca OpenCV sebagai tepat 956 frame.

## Evidence R2 saat ini

Footage target yang dipilih berada di SSD Nopal Jetson pada epoch:

```text
/media/bengawan/nopal-ssd1/flight-recordings/mission-6f1ff7d6-c99d-4fe2-80bc-3544180868a9/epochs/0001/
```

Model yang digunakan untuk pengujian ini adalah checkpoint
`ghostv3_dwconv-seed0/weights/best.pt` dari hasil training Downloads
(SHA-256 `7c3c2dd5ecb0cc440f4ae9b7add6a9493c1f6bbc9b6924f7d35a6e250ad7727f`).
Checkpoint custom ini membutuhkan `modules_ghost.py` dan `modules_sy.py` dari
runtime training; `best.pt` saja belum cukup.
`detections.jsonl` bawaan epoch tersebut berstatus detector `FAILED` karena
Ultralytics belum tersedia pada runtime recorder, sehingga file itu bukan
evidence inference R2. Sidecar telemetry epoch tersebut berstatus
`SOURCE_OFFLINE`, jadi synchronization juga belum lulus.

Smoke test yang sudah dijalankan pada 2026-08-28 memakai checkpoint custom yang
sama dan runner `postflight.offline_yolo`:

- remux staging dapat dibuka OpenCV dan terbaca 34.439 frame;
- sampel footage nyata 10 frame berhasil diproses seluruhnya;
- output `detections-ghostv3-sample10.jsonl` menulis 1 detection (`frame_id=4`,
  `pedestrian`, confidence sekitar 0,5733);
- runtime Jetson yang tersedia CPU-only (`torch.cuda.is_available()=False`),
  sehingga full 34 ribu frame belum dijalankan.

Full acceptance masih tertahan: `frames.jsonl` dan `telemetry.jsonl` memiliki
blok NUL mulai baris 34342, video memiliki 34.439 frame sedangkan metadata
valid hanya sampai `frame_id=34340`, dan telemetry tidak menyediakan
`source_time_valid=true`. Remux dan sampel dibuat di
`/home/bengawan/r2-inference-staging/`; footage asli SSD tetap tidak diubah.

### Capture radio telemetry terbaru

Pada 2026-08-28 dilakukan capture baru dengan mission ID
`mission-27bd4805-50f3-4504-8046-4f297e50833f` menggunakan Arducam CSI dan
radio telemetry Ground secara receive-only. Hasil validasinya:

- video final terbaca tepat 956 frame oleh OpenCV dan metadata valid memiliki
  `frame_id=0..955`;
- ground telemetry berisi 2.265 sample, dengan 423 sample
  `source_time_valid=true` dan mapping `fc_boot_ms_mapped_to_utc`;
- 956/956 frame memiliki bracket telemetry dan state lengkap untuk interpolasi
  linear;
- tidak ada telemetry sample yang drop.

Ini membuktikan temporal synchronization footage → telemetry pada capture baru.
Inference custom 10 frame dari mission yang sama juga selesai 10/10 tanpa error,
namun menghasilkan 0 detection; detection → telemetry belum dapat menghasilkan
output karena tidak ada bbox yang dijoin. Untuk acceptance berikutnya, gunakan
segmen yang benar-benar memuat target visual. Manual detection/review tetap
future work dan bukan gate.

## Acceptance R2

Pengujian inference offline dianggap lulus bila gate berikut terpenuhi:

1. footage berasal dari video nyata di SSD Nopal Jetson dan pasangan
   `frames.jsonl` tersedia;
2. validator artifact lulus tanpa missing PTS, duplicate frame ID, atau frame
   count mismatch;
3. offline YOLO memakai model yang tercatat, memproses seluruh frame yang
   tersedia, dan menulis detection bila target terdeteksi;
4. bila telemetry Ground dengan `source_time_valid=true` tersedia,
   synchronization menulis record `telemetry_sync_status=synchronized` tanpa
   memakai receive-time fallback;
5. output inference dan ringkasan command disimpan sebagai evidence R2.

Video yang blur, tidak memiliki target, atau menghasilkan nol detection dicatat
sebagai hasil capture/integration test, bukan detection acceptance. Manual
detection/review sengaja tidak menjadi gate R2 dan tetap merupakan future work.

## UTC Global pre-flight dan evidence

Tidak ada langkah instalasi atau verifikasi chrony pada prosedur ini. Sebelum
memulai recording/inference, catat waktu UTC host dan pastikan artifact menulis
field UTC secara valid:

```bash
date -u '+%Y-%m-%dT%H:%M:%SZ'
```

Jika `source_timestamp` telemetry belum valid atau domain clock belum dapat
dipetakan ke UTC, status synchronization harus dicatat
**blocked/unsynchronized**; jangan mengganti source time dengan
`receive_timestamp`.
