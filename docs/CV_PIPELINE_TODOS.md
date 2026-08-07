# Computer Vision Pipeline TODOs

Dokumen ini adalah living document untuk pengembangan pipeline computer vision,
telemetry, streaming, geolocation, dan manual labeling pada BUV SAR Console.

Perbarui checklist ini setiap kali sebuah pekerjaan selesai, dibatalkan, atau
keputusannya berubah. Tambahkan catatan singkat pada bagian `Change Log` jika
perubahan memengaruhi arsitektur atau kontrak data.

## Status

- `[ ]` belum dikerjakan
- `[~]` sedang dikerjakan
- `[x]` selesai dan sudah diverifikasi
- `[!]` terblokir atau membutuhkan keputusan/hardware

## Keputusan yang sudah dikonfirmasi

- Mission Planner tetap menjadi jalur telemetry dan command untuk dashboard.
- Jetson membaca telemetry FC secara read-only untuk kebutuhan CV yang sensitif terhadap latency.
- Kamera HP terhubung ke Jetson melalui stream IP.
- Jetson menjadi pemilik capture, inference, tracking, dan rekaman lokal.
- Video live dikirim ke ground station melalui koneksi 5G/internet.
- Metadata deteksi dikirim terpisah dari video dan tidak boleh menghentikan loop kamera.
- Window propagasi/manual labeling menggunakan **5 frame**, bukan 10 frame.
- `window_size=5` pada Coordinate-Estimator dipertahankan.
- `MAX_COASTING_FRAMES=25` tetap merupakan batas kehilangan track dan tidak disamakan dengan window 5 frame.
- Latitude/longitude dummy boleh digunakan hanya untuk demo dan harus diberi status `DUMMY` atau `SIMULATED`.
- Jika GPS atau altitude belum tersedia, hasil koordinat nyata harus berstatus `UNAVAILABLE` atau `RELATIVE_APPROXIMATE`, bukan koordinat palsu.

## Kontrak data minimum

Setiap frame yang diproses Jetson perlu dapat direkonstruksi dengan record
berikut. Nama field boleh berubah, tetapi maknanya harus tetap konsisten.

```json
{
  "mission_id": "demo-mission-001",
  "boot_id": "jetson-boot-001",
  "camera_id": "phone-ip-camera-001",
  "frame_id": 0,
  "capture_timestamp_ns": 0,
  "telemetry": {
    "roll_deg": null,
    "pitch_deg": null,
    "yaw_deg": null,
    "source_timestamp_ns": null,
    "received_timestamp_ns": null,
    "age_ms": null
  },
  "detections": [],
  "coordinate": {
    "status": "UNAVAILABLE",
    "latitude": null,
    "longitude": null,
    "error_radius_m": null
  }
}
```

Bounding box disimpan dalam koordinat normalized agar tidak rusak ketika video
ditampilkan pada ukuran UI berbeda.

## Fase 0 — Baseline dan observability

- [ ] Tambahkan panel status field telemetry: tersedia, `null`, stale, atau tidak didukung.
- [ ] Verifikasi response `/api/v1/telemetry` untuk roll, pitch, yaw, GPS, altitude, dan speed.
- [ ] Tambahkan `source_timestamp`, `received_timestamp`, dan umur telemetry pada log.
- [ ] Pastikan dashboard tidak menampilkan koordinat dummy sebagai koordinat nyata.
- [ ] Dokumentasikan resolusi, FPS, latency, dan format stream kamera HP.

## Fase 1 — Kamera IP dan rekaman Jetson

- [ ] Buat capture service Jetson untuk URL kamera IP.
- [ ] Tambahkan `frame_id` yang monoton dan `capture_timestamp_ns` pada setiap frame.
- [ ] Simpan video asli tanpa overlay untuk kebutuhan offline.
- [ ] Simpan metadata frame dalam JSONL atau format append-only yang dapat diputar ulang.
- [ ] Tambahkan reconnect kamera tanpa menghentikan service.
- [ ] Buat replay lokal dari video dan metadata hasil rekaman.

## Fase 2 — Object detection dan tracking

- [ ] Jalankan model detector sederhana di Jetson menggunakan footage lokal terlebih dahulu.
- [ ] Filter kelas target, misalnya `person`, dan confidence threshold.
- [ ] Render bounding box, class, confidence, dan `track_id`.
- [ ] Tambahkan tracker untuk mempertahankan objek ketika detector miss.
- [ ] Simpan detection record per `frame_id`.
- [ ] Uji kondisi target muncul, hilang, muncul kembali, dan lebih dari satu target.

## Fase 3 — Dummy end-to-end pipeline

- [~] Sediakan mode `SIMULATION` yang dapat menggunakan footage/image acak (`mock_vision.py` sudah menghasilkan video dan JSONL).
- [ ] Buat dummy bounding box yang bergerak secara deterministik agar mudah diuji.
- [ ] Buat dummy latitude/longitude tetap atau bergerak dengan `coordinate.status=SIMULATED`.
- [ ] Tampilkan bounding box dan koordinat dummy pada dashboard.
- [ ] Pastikan data dummy tidak tercampur dengan data flight nyata.
- [ ] Tambahkan switch konfigurasi untuk mematikan mode dummy pada deployment nyata.

## Fase 4 — Ingestion dan dashboard

- [ ] Tetapkan endpoint ingestion untuk detection record yang memiliki `frame_id`.
- [ ] Validasi schema payload di backend, bukan hanya memeriksa JSON tidak kosong.
- [ ] Simpan detection dan event secara persisten.
- [ ] Tampilkan daftar deteksi, confidence, track ID, timestamp, dan coordinate status.
- [ ] Tampilkan overlay detection pada live preview atau pada player yang memiliki metadata frame.
- [ ] Tampilkan status detector: `OFFLINE`, `STARTING`, `LIVE`, `STALE`, atau `FAILED`.

## Fase 5 — Manual labeling lima frame

- [ ] Tambahkan freeze-frame pada dashboard.
- [ ] Tambahkan gambar bounding box manusia secara manual.
- [ ] Tambahkan ground-contact point pada bagian bawah tengah bounding box.
- [ ] Simpan annotation dengan `frame_id`, ukuran frame asli, normalized geometry, dan transform preview.
- [ ] Propagasikan annotation ke total 5 frame menggunakan tracker.
- [ ] Tandai hasil sebagai `manual` atau `propagated`.
- [ ] Simpan `parent_annotation_id` dan confidence propagation.
- [ ] Beri operator kesempatan mengoreksi drift.
- [ ] Jangan masukkan label propagated ke training dataset sebelum review.

## Fase 6 — Streaming 5G/internet

- [ ] Pilih media transport yang sesuai dengan kebutuhan latency dan deployment.
- [ ] Pisahkan video dari metadata deteksi.
- [ ] Tambahkan receiver di ground station dengan reconnect dan indikator latency.
- [ ] Tambahkan queue/retry untuk metadata ketika link terganggu.
- [ ] Pastikan rekaman lokal Jetson tetap lengkap ketika video live drop.
- [ ] Uji bitrate, latency, packet loss, NAT, authentication, dan reconnect pada jaringan 5G.

## Fase 7 — Estimasi koordinat relatif

- [ ] Kalibrasi intrinsic kamera HP.
- [ ] Ukur extrinsic kamera terhadap badan UAV.
- [ ] Gunakan ground plane datar dan altitude dummy/konstan untuk demo.
- [ ] Implementasikan pixel → ray → intersection dengan ground plane.
- [ ] Beri status hasil sebagai `RELATIVE_APPROXIMATE`.
- [ ] Tampilkan error radius dan umur telemetry.
- [ ] Bandingkan hasil live dengan hasil offline menggunakan footage yang sama.

## Fase 8 — Koordinat geografis nyata

- [ ] Tambahkan sumber GPS yang valid.
- [ ] Tambahkan sumber altitude yang valid, misalnya barometer, rangefinder, atau data FC.
- [ ] Pastikan timestamp GPS, altitude, attitude, dan frame dapat disejajarkan.
- [ ] Tetapkan reference frame dan datum koordinat.
- [ ] Uji validitas hasil pada beberapa ketinggian dan attitude.
- [ ] Tambahkan DEM/DSM jika permukaan tanah tidak dapat dianggap datar.
- [ ] Pisahkan status `LIVE_APPROXIMATE` dari `OFFLINE_REFINED`.

## Fase 9 — Reliability dan deployment

- [ ] Jalankan inference dan network sender pada worker terpisah.
- [ ] Tambahkan health check Jetson, kamera, detector, telemetry, dan uplink.
- [ ] Tambahkan rate limit, authentication, dan encryption untuk endpoint internet.
- [ ] Simpan log kegagalan dan alasan frame/metadata dibuang.
- [ ] Uji long-running flight recording.
- [ ] Uji behavior saat kamera, telemetry, 5G, atau detector berhenti.

## Opsi pengembangan berikutnya

### Opsi A — Dummy vertical slice di laptop

Video/image lokal diproses oleh backend atau script mock. Bounding box dan
koordinat dummy dikirim ke dashboard.

- Kelebihan: paling cepat, mudah di-debug, tidak membutuhkan Jetson atau 5G.
- Kekurangan: belum menguji performa Jetson, latency kamera IP, dan kondisi jaringan.

### Opsi B — Dummy detector langsung di Jetson

Jetson menerima footage kamera HP, menggambar bounding box dummy, lalu mengirim
metadata dummy ke backend.

- Kelebihan: menguji arsitektur deployment yang mendekati sistem nyata.
- Kekurangan: membutuhkan Jetson, jaringan kamera, dan setup service lebih awal.

### Opsi C — Detector nyata lebih dahulu

Langsung menjalankan model object detection pada footage kamera HP.

- Kelebihan: cepat mendapatkan hasil CV yang nyata.
- Kekurangan: debugging menjadi sulit karena capture, model, telemetry, dan network belum terpisah.

Rekomendasi: mulai dengan Opsi A, lanjutkan ke Opsi B, lalu ganti dummy detector
dengan detector nyata. Dengan urutan ini, format data dan UI dapat diuji sebelum
masuk ke masalah hardware dan jaringan.

## Change Log

### 2026-08-05

- Menetapkan window manual labeling/propagasi sebesar 5 frame.
- Memisahkan window 5 frame dari batas coasting 25 frame pada estimator.
- Menetapkan dummy latitude/longitude hanya untuk mode simulasi.
- Menetapkan Jetson sebagai pemilik capture dan inference, sedangkan bridge Mission Planner digunakan untuk dashboard.
