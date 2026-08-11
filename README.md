# BUV SAR Console

BUV SAR Console adalah aplikasi operasional pendamping Mission Planner untuk
monitoring penerbangan, visualisasi map, dan pengembangan computer vision.

Mission Planner tetap menjadi sumber kebenaran untuk dashboard, command,
konfigurasi parameter, dan mission. Untuk flight recording, Jetson juga dapat
membaca stream MAVLink flight controller secara read-only melalui
`mavlink-router`; jalur ini tidak mengirim command dan tidak membutuhkan
Mission Planner.

## Arsitektur

```text
Flight Controller
  -> Mission Planner
  -> Mission Planner HTTP Bridge :5000
  -> BUV Backend API/WebSocket :5001
  -> React + Tauri Frontend

Flight Controller
  -> MAVLink Router di Jetson
  -> telemetry collector read-only :5760 localhost
  -> telemetry.jsonl per frame
```

Video dan recording Arducam berjalan melalui Jetson, bukan melalui laptop:

```text
Arducam CSI/Argus -> Jetson split pipeline
  ├─ high-res -> video.mp4 lokal Jetson
  ├─ frame PTS + MAVLink snapshot -> telemetry.jsonl lokal Jetson
  ├─ optional YOLO/SAHI -> detections.jsonl lokal Jetson
  ├─ low-res H.264/RTP/UDP :5000 -> GCS preview
  └─ bbox HTTP :5001 -> GCS overlay

GCS website -> recording agent Jetson :5101 -> START / STOP & SAVE
```

## Setup and Installation

This project utilizes Docker to containerize the Python backend and AI dependencies, ensuring a consistent development environment.

### Prerequisites
- Node.js & npm
- Docker Desktop
- Mission Planner (Windows; optional untuk capture-only)
- Tailscale, atau jaringan modem/LAN yang membuat Jetson dan GCS saling terjangkau
- Jetson dengan kamera Arducam CSI/Argus dan GStreamer

### Quick Start

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd <repository-folder>
   ```

2. **Configure Environment Variables**
   ```bash
   cp src-tauri/src-py/.env.example src-tauri/src-py/.env
   ```
   *Edit `src-tauri/src-py/.env` and insert your Gemini, Notion, and Telegram API keys.*

3. **Start the Mission Planner Bridge (optional)**
   Open Mission Planner, navigate to the Scripts tab, and run
   `mission-planner/mission_planner_bridge.py` if the dashboard needs live
   telemetry, mission, or flight-controller commands. Capture-only recording
   can skip this step; Jetson reads MAVLink separately in read-only mode.

4. **Start the Backend Services (Docker)**
   ```bash
   docker compose up --build -d backend
   ```
   *The Flask API runs on TCP port 5001. The Docker Compose configuration juga
   mem-publish UDP port 5000 untuk low-res RTP dari Jetson.*

5. **Start the Frontend UI (Tauri)**
   ```bash
   npm install
   npm run tauri dev
   ```

> Flight recording melalui EasyCAP harus menjalankan backend secara native di
> Windows. Container Docker Linux tidak memiliki akses ke perangkat DirectShow.
> RD945 juga tetap membutuhkan catu daya fisik; Python mengaktifkan capture
> EasyCAP, bukan power receiver.

### Alternative: Manual Setup (Without Docker)

If you prefer to run the backend natively using a Python virtual environment:

1. **Adjust Environment Variables**: Ensure `MISSION_PLANNER_API_URL` in `src-tauri/src-py/.env` is set to `http://127.0.0.1:5000` (instead of `host.docker.internal`).
2. **Start the Backend**:
   ```bash
   cd src-tauri/src-py
   python -m venv .venv
   .\.venv\Scripts\activate   # Use `source .venv/bin/activate` on Linux/Mac
   pip install -r requirements.txt
   python main.py
   ```

### Testing the AI Pipeline
To simulate a target detection from the companion computer (e.g., Jetson Nano):
```bash
python src-tauri/src-py/mock_jetson.py
```

Untuk menguji bounding box, `frame_id`, dan koordinat dummy pada footage lokal:
```bash
python src-tauri/src-py/mock_vision.py --show
```

Script tersebut menghasilkan video ber-overlay dan metadata JSONL di bawah
`src-tauri/src-py/runtime/mock_vision/`. Koordinat yang dihasilkan berstatus
`SIMULATED` dan tidak boleh digunakan sebagai koordinat penerbangan nyata.

## Endpoint Backend

```text
GET  /api/v1/health
GET  /api/v1/telemetry
WS   /api/v1/events
GET  /api/v1/recordings/status
POST /api/v1/recordings/start
POST /api/v1/recordings/stop
GET  /api/v1/camera/status
GET  /api/v1/camera/preview
POST /api/v1/camera/start
POST /api/v1/camera/stop
POST /api/v1/camera/preview-source
GET  /api/v1/detection/overlay
POST /api/v1/detection/overlay
POST /api/v1/detection/ingest
POST /api/v1/commands/arm
POST /api/v1/commands/disarm
POST /api/v1/commands/reboot
POST /api/v1/commands/set-flight-mode
GET  /logs/summary
GET  /logs/recent
```

## Scope Saat Ini

- Telemetry HUD dari Mission Planner serta read-only telemetry sidecar dari
  MAVLink Router Jetson untuk flight recording.
- Arm, disarm, reboot saat disarmed, dan perubahan flight mode melalui Mission
  Planner.
- HTTP snapshot dengan WebSocket real-time dan fallback polling.
- Deteksi telemetry stale dan validitas GPS.
- Dashboard SAR, model wahana 3D, serta fondasi map dan computer vision.
- Arducam Jetson split pipeline: high-res MP4/detection sidecar lokal Jetson,
  telemetry sidecar per frame, low-res H.264/RTP/UDP preview ke GCS, dan
  overlay bbox di frontend. VRX RD945/EasyCAP tetap tersedia sebagai source
  legacy.

## Flight Recording

Untuk `CAMERA_SOURCE=jetson_udp`, tombol `START RECORDING` pada dashboard
mengontrol recorder high-res di Jetson melalui backend GCS dan jaringan
Tailscale. GCS tidak membuat file relay recording. Setelah `STOP & SAVE`, file
berada di Jetson:

```text
/media/<user>/<ssd-label>/flight-recordings/flight-<timestamp>-<id>/
  video.mp4
  video_analog.mkv
  telemetry.jsonl
  detections.jsonl
  preview-events.jsonl
  metadata.json
```

`video.mp4` adalah cabang high-res B0249 yang sama dengan input YOLO/SAHI.
Jika ARKMICRO EasyCAP terhubung dan dikonfigurasi, `video_analog.mkv` merekam
output switcher analog secara paralel sebagai MJPEG dengan timestamp yang
dinormalisasi; isi RGB/night/thermal mengikuti pilihan RC pilot.
`preview-events.jsonl` mencatat pilihan preview web digital/analog;
`telemetry.jsonl` berisi snapshot telemetry read-only yang dicocokkan ke
`frame_id` dan PTS. Pada mode capture-only, `detections.jsonl` tetap berisi
record per frame dengan `detections=[]` dan `bbox=null`; YOLO dapat dijalankan
offline setelah flight. Live preview low-res dan overlay bbox tetap
dikirim/ditampilkan di GCS, tetapi tidak disimpan sebagai recording kedua di
laptop.

Dokumentasi workflow lengkap tersedia di
[`docs/JETSON_CAPTURE_ONLY_WORKFLOW.md`](docs/JETSON_CAPTURE_ONLY_WORKFLOW.md).

Konfigurasi utama berada di `src-tauri/src-py/.env`:

- `CAMERA_SOURCE=jetson_udp` untuk Arducam melalui Tailscale;
- `JETSON_VIDEO_PORT`, `JETSON_VIDEO_PAYLOAD_TYPE`, dan
  `JETSON_VIDEO_JITTER_LATENCY_MS` harus cocok dengan sender;
- `JETSON_VIDEO_PREVIEW_WIDTH` dan `JETSON_VIDEO_PREVIEW_HEIGHT` mengatur
  resolusi decode/preview backend;
- `JETSON_RECORDING_AGENT_URL` dan `JETSON_RECORDING_AGENT_TOKEN` menghubungkan
  backend GCS ke service recording di Jetson;
- `DETECTION_OVERLAY_TTL_SECONDS` mengatur berapa lama bbox terakhir boleh
  ditampilkan ketika detector berhenti mengirim;
- `FLIGHT_RECORDINGS_DIR` hanya dipakai oleh source EasyCAP legacy;
- `CAMERA_SOURCE=easycap` mengaktifkan source VRX lama dan memakai
  `VRX_CAMERA_INDEX`, `VRX_CAPTURE_WIDTH`, `VRX_CAPTURE_HEIGHT`, dan
  `VRX_CAPTURE_FPS`.

Konfigurasi sender dan recording agent Jetson berada di `jetson/.env`. Salin
`jetson/.env.example` ke file tersebut di Jetson. Token harus sama dengan
konfigurasi GCS. Alamat GCS tidak perlu disimpan di Jetson: saat recording
dimulai, agent otomatis memakai IPv4 pemanggil `/recording/start` sebagai
tujuan RTP dan detection overlay.

`JETSON_FLIP_METHOD=2` merotasi input kamera 180 derajat sebelum pipeline
dipecah. Karena transform dilakukan sebelum `tee`, file recording, input
inference, dan live preview mempunyai orientasi yang sama. Gunakan nilai `0`
hanya untuk menonaktifkan rotasi saat pengujian bench.

Preview web dapat dipilih secara global tanpa mengubah master recording atau
inference. `source=digital` menampilkan cabang low-res B0249 dan mengizinkan
overlay bbox. `source=analog` menampilkan EasyCAP yang saat itu dipilih pilot
melalui switcher RC; overlay bbox B0249 disembunyikan karena field of view-nya
berbeda. Jetson tetap mengirim satu RTP stream pada satu waktu.

```text
POST /api/v1/camera/preview-source
Content-Type: application/json

{"source":"digital"}
{"source":"analog"}
```

EasyCAP bersifat opsional. Konfigurasi hardware project yang sudah diverifikasi
adalah `/dev/v4l/by-id/usb-ARKMICRO_USB2.0_PC_CAMERA-video-index0`, MJPEG
`640x480@30`. Node `video-index1` hanya membawa UVC metadata dan tidak boleh
dipakai. Bila capture node tidak terhubung, pipeline digital tetap bekerja,
recording analog dinonaktifkan, dan pilihan preview analog ditolak secara
eksplisit.

Pilihan preview disimpan oleh recording agent dan berlaku global untuk semua
browser. Pada lifecycle saat ini sender Jetson hidup bersama flight-recording
pipeline; pilihan yang dibuat ketika idle akan dipakai saat recording berikutnya
dimulai, dan dapat diganti tanpa menghentikan recording ketika pipeline aktif.

Dashboard mengambil live preview MJPEG dari service backend. Pada source Jetson,
backend menerima H.264/RTP/UDP dengan GStreamer dan hanya menyediakan preview;
perintah recording diteruskan ke Jetson Recording Agent. Pada source EasyCAP,
perangkat legacy masih dapat direkam secara lokal oleh backend.

## Jetson split pipeline: high-res local + low-res network

Untuk produksi, jalankan `jetson/arducam_split_pipeline.py` secara native di
Jetson. Satu capture Argus dibagi menjadi tiga cabang:

```text
Arducam high-res
  ├─ x264enc → video.mp4 lokal Jetson       (evidence penerbangan)
  ├─ frame PTS + MAVLink → telemetry.jsonl   (read-only telemetry)
  ├─ BGR appsink → optional YOLO/SAHI        (detail objek)
  │                └─ detections.jsonl + optional POST bbox ke GCS
  └─ resize + x264enc → H.264/RTP/UDP        (low-res live preview GCS)
```

Default yang aman untuk mulai adalah high-res `1920x1080@30` untuk recording
dan YOLO/SAHI, lalu network `960x540@15` dengan bitrate `2 Mbps`. Orin Nano
tidak memiliki NVENC, sehingga sender menggunakan `x264enc` software; ukur
beban CPU/FPS di unit aktual sebelum menaikkan resolusi. File high-res dan
sidecar detector berada di Jetson, sedangkan GCS hanya menerima cabang
network dan overlay bbox.

Contoh command (ganti IP, model, dan direktori sesuai instalasi):

```bash
cd <repository-folder>
python3 jetson/arducam_split_pipeline.py \
  --host IP_TAILSCALE_GCS \
  --port 5000 \
  --high-width 1920 --high-height 1080 --high-fps 30 \
  --network-width 960 --network-height 540 --network-fps 15 \
  --record-dir /media/<user>/<ssd-label>/flight-recordings \
  --sahi --slice-width 640 --slice-height 640 --overlap 0.2 \
  --ingest-url http://IP_TAILSCALE_GCS:5001/api/v1/detection/overlay
```

`--weights` boleh dihilangkan untuk mode capture-only tanpa detector. Pada mode
ini `telemetry.jsonl` dan placeholder `detections.jsonl` tetap dibuat.
Command manual ini adalah smoke test; jangan menjalankannya
bersamaan dengan `recording_agent.py`. Endpoint `/api/v1/detection/overlay` hanya menyimpan hasil
frame terbaru dengan TTL singkat; endpoint ini sengaja terpisah dari
`/api/v1/detection/ingest`, yang tetap digunakan untuk event detection yang
boleh memicu evaluasi AI/dispatcher. Bbox dikirim dalam koordinat high-res dan
network; frontend menggambar `bbox_network` di atas preview low-res.

Sebelum penerbangan, verifikasi plugin Jetson:

```bash
gst-inspect-1.0 nvarguscamerasrc nvvidconv x264enc rtph264pay mp4mux appsink
```

Sender membuat satu direktori session berisi `video.mp4`,
`detections.jsonl`, dan `metadata.json`. Untuk mengaktifkan button website,
jalankan agent di Jetson:

```bash
cd <repository-folder>
set -a; source jetson/.env; set +a
python3 jetson/recording_agent.py
```

Service ini menjalankan split pipeline sebagai satu child process, mencegah
dua recorder berjalan bersamaan, dan mengirim SIGINT saat `STOP & SAVE` agar
MP4 ditutup dengan EOS. Untuk deployment penerbangan, gunakan template
`jetson/buv-recording-agent.service.example` sebagai service `systemd` dan isi
`JETSON_RECORDING_AGENT_TOKEN` di Jetson serta GCS.

## End-to-end hardware test

Lakukan smoke test tanpa model terlebih dahulu. Dengan cara ini kamera,
koneksi modem, preview UDP, dan penyimpanan lokal dapat diverifikasi secara
terpisah dari YOLO/SAHI.

### 1. Verifikasi koneksi Jetson dan GCS

Jika Jetson dan laptop berada di jaringan modem yang sama, IP LAN dapat
digunakan. Jika Jetson hanya memiliki koneksi seluler atau berada di jaringan
berbeda, gunakan IP/hostname Tailscale. Tidak diperlukan port forwarding publik.

Jalankan di kedua perangkat:

```bash
tailscale ip -4
tailscale ping <IP_PERANGKAT_LAIN>
```

Catat `<JETSON_IP>`. Jetson harus dapat menjangkau GCS pada TCP
5001 dan UDP 5000; GCS harus dapat menjangkau Jetson pada TCP 5101.

### 2. Test kamera di Jetson

Untuk kamera CSI/Argus:

```bash
sudo systemctl restart nvargus-daemon
gst-inspect-1.0 nvarguscamerasrc nvvidconv x264enc rtph264pay mp4mux appsink
gst-launch-1.0 -e \
  nvarguscamerasrc sensor-id=0 num-buffers=30 ! \
  'video/x-raw(memory:NVMM),width=1920,height=1080,format=NV12,framerate=30/1' ! \
  fakesink sync=false
```

Jika mode 1920x1080 tidak didukung kamera, gunakan mode Argus yang tersedia,
misalnya 1280x720, lalu sesuaikan `JETSON_HIGH_WIDTH` dan
`JETSON_HIGH_HEIGHT`.

### 3. Siapkan konfigurasi

Di GCS/laptop:

```bash
cp src-tauri/src-py/.env.example src-tauri/src-py/.env
```

Edit nilai berikut di `src-tauri/src-py/.env`:

```env
CAMERA_SOURCE=jetson_udp
JETSON_RECORDING_AGENT_URL=http://<JETSON_IP>:5101
JETSON_RECORDING_AGENT_TOKEN=<TOKEN_BERSAMA>
```

Di Jetson:

```bash
cp jetson/.env.example jetson/.env
```

Edit `jetson/.env`:

```env
JETSON_RECORDING_AGENT_TOKEN=<TOKEN_BERSAMA>
JETSON_RECORD_DIR=/media/<user>/<ssd-label>/flight-recordings
```

`JETSON_GCS_HOST` bersifat opsional dan hanya menjadi fallback untuk caller
lama. Pada koneksi langsung GCS ke Jetson, setiap `START RECORDING` otomatis
memperbarui tujuan stream ke IP GCS yang melakukan request sehingga perubahan
IP tidak memerlukan edit `/etc/buv/jetson-recording.env` atau restart service.
Override ke alamat yang berbeda dari IP pemanggil ditolak secara default;
aktifkan `JETSON_ALLOW_GCS_HOST_OVERRIDE=true` hanya jika deployment memakai
proxy atau routing khusus.

Untuk smoke test pertama, biarkan `JETSON_MODEL_WEIGHTS` tetap dikomentari.
Pastikan mountpoint SSD aktif dan `JETSON_RECORD_DIR` dapat ditulis oleh user
yang menjalankan agent. Untuk telemetry aktual tanpa Mission Planner, pastikan
flight controller muncul sebagai `/dev/ttyACM0` dan diagnostics MAVLink Router
menunjukkan heartbeats/bytes received bertambah.

### 4. Jalankan backend dan recording agent

Di GCS/laptop:

```bash
docker compose config --quiet
docker compose up --build -d backend
docker compose logs -f backend
```

Di terminal GCS yang lain, aktifkan receiver:

```bash
curl http://127.0.0.1:5001/api/v1/health
curl -X POST http://127.0.0.1:5001/api/v1/camera/start
curl http://127.0.0.1:5001/api/v1/camera/status
```

Di Jetson, jalankan agent dan biarkan terminalnya terbuka:

```bash
set -a
source jetson/.env
set +a
python3 jetson/recording_agent.py
```

Test status agent dari GCS:

```bash
curl -sS \
  -H "Authorization: Bearer <TOKEN_BERSAMA>" \
  http://<JETSON_IP>:5101/recording/status
```

Status awal yang diharapkan adalah `IDLE`.

### 5. Test tombol recording

Jalankan frontend:

```bash
npm install       # cukup sekali jika dependency belum terpasang
npm run tauri dev
```

Di dashboard:

1. Pastikan preview kamera muncul.
2. Klik `START RECORDING`.
3. Tunggu status `RECORDING` dan biarkan berjalan beberapa detik.
4. Klik `STOP & SAVE`.

Hasil yang diharapkan:

- Preview GCS menerima low-res sekitar 960x540 pada 15 FPS.
- Status berubah dari `STARTING` menjadi `RECORDING`, lalu `COMPLETED`.
- Jetson membuat `video.mp4`, `telemetry.jsonl`, `detections.jsonl`, dan
  `metadata.json`.
- Tidak ada video relay baru yang disimpan di laptop/GCS untuk
  `CAMERA_SOURCE=jetson_udp`.

Periksa hasil di Jetson:

```bash
find /media/<user>/<ssd-label>/flight-recordings -maxdepth 2 -type f -print
ls -lh /media/<user>/<ssd-label>/flight-recordings/*/video.mp4
gst-discoverer-1.0 /media/<user>/<ssd-label>/flight-recordings/<session-id>/video.mp4
```

### 6. Aktifkan YOLO/SAHI setelah smoke test berhasil

Setelah capture, network, dan recording berhasil, isi konfigurasi model di
`jetson/.env`:

```env
JETSON_MODEL_WEIGHTS=/absolute/path/to/best.pt
JETSON_MODEL_SAHI=true
JETSON_MODEL_SLICE_WIDTH=640
JETSON_MODEL_SLICE_HEIGHT=640
JETSON_MODEL_OVERLAP=0.2
```

Restart recording agent, lakukan recording baru, lalu periksa:

```bash
tail -f /media/<user>/<ssd-label>/flight-recordings/<session-id>/detections.jsonl
curl http://127.0.0.1:5001/api/v1/detection/overlay
```

Pada mode capture-only, `detections.jsonl` berisi row per frame dengan
`detections=[]` dan `bbox=null`. Pada mode YOLO, row berisi bbox bila objek
terdeteksi; frontend menggambar `bbox_network` pada preview low-res.

Jika preview hilang, periksa log backend dan pastikan UDP `5000`, payload type,
serta IP GCS cocok. Jika tombol recording gagal, periksa token dan koneksi TCP
ke Jetson port `5101`. Orin Nano menggunakan `x264enc` software; pantau beban
dengan `tegrastats` dan turunkan resolusi/FPS jika pipeline tidak mampu menjaga
frame rate.

Untuk mengekstrak video menjadi image yang tetap mengikuti `frame_id`:

```bash
python src-tauri/src-py/extract_recording_frames.py <direktori-session>
```

Roadmap lengkap tersedia di
`docs/2026-06-06-mission-planner-vision-refactor-plan.md`.
