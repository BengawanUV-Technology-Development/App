# Short Flight Test / Post-Flight Synchronization

Dokumen ini adalah prosedur sementara sebelum R2. Fokusnya adalah membuktikan
rantai temporal berikut, bukan coordinate reconstruction:

```text
video.mp4 + frames.jsonl + Ground telemetry.jsonl
    → offline YOLO
    → detections.jsonl
    → frame timestamp
    → source-time telemetry interpolation
```

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

Coordinate reconstruction dari bbox tetap berada di luar scope.

## Acceptance penuh

Short flight baru dianggap lulus penuh bila semua gate berikut terpenuhi:

1. time service Ground lulus verifier dan `chronyc tracking`/`chronyc sources -v`
   di Jetson menunjukkan source yang synchronized;
2. camera frame terlihat jelas dan target yang memang ada di scene terlihat;
3. validator artifact lulus tanpa missing PTS atau dropped sample;
4. offline YOLO memproses semua frame dan menulis minimal satu detection;
5. synchronization menulis minimal satu record `telemetry_sync_status=synchronized`;
6. detection tersebut diperiksa manual terhadap frame video yang sama.

Video yang blur, tidak memiliki target, atau menghasilkan nol detection hanya
merupakan capture/integration test; itu bukan acceptance penuh walaupun file
dan timestamp valid.

## Clock pre-flight

Panduan aktivasi otomatis Ground–Jetson tersedia di
[CHRONY_SETUP.md](./CHRONY_SETUP.md).

Verifikasi di Ground dan Jetson sebelum `Start Record`.

Untuk macOS/Linux Ground:

```bash
chronyc tracking
chronyc sources -v
```

Repository helper (read-only; di macOS Homebrew gunakan path `chronyc` eksplisit):

```bash
python3 scripts/verify_chrony.py --role ground-server --chronyc-path /opt/homebrew/bin/chronyc
python3 scripts/verify_chrony.py --role jetson-client
```

Untuk Windows Ground:

```powershell
.\scripts\verify_windows_time_server.ps1 -JetsonIp "<JETSON_IP>"
w32tm /query /source
w32tm /query /status
```

Ground harus menjadi sumber waktu jaringan dan Jetson harus menjadi client.
Pada Windows, `W32Time` adalah profil kompatibilitas karena Windows tidak
menyediakan `chronyd` native. Jika time service belum aktif atau source Jetson
belum synchronized, flight test temporal tidak boleh dianggap valid meskipun
file video dapat diputar.
