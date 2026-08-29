# Coordinate-Estimator Audit and app-mavproxy MVP Adapter

Dokumen ini mencatat audit repository referensi dan kontrak adapter yang dapat
dipakai offline maupun oleh live Ground ingest. Statusnya tidak menyatakan
akurasi geodetik atau qualification penerbangan.

## 1. Repository yang diaudit

Repository:

```text
https://github.com/BengawanUV-Technology-Development/Coordinate-Estimator
commit: cf1d868 (main)
```

Strukturnya kecil dan tidak berbentuk library:

```text
Coordinate-Estimator/
├── target_localization.py   # entry point dan seluruh pipeline eksperimen
├── create_video.py          # membuat MP4 dari 60 PNG Blender (path Windows)
├── README.md                # dokumentasi eksperimen/synthetic benchmark
├── requirements.txt         # numpy, OpenCV, Ultralytics
├── input_rendered.mp4       # sample asset
└── output_annotated.mp4     # sample output
```

Tidak ditemukan calibration file, extrinsic file, test suite formal, sample
telemetry CSV yang dapat dipakai ulang, atau package API terpisah. Entry point
referensi adalah:

```bash
python target_localization.py [--video ...] [--telemetry ...]
```

Mode `yolo` pada referensi juga berbeda dari R2 app-mavproxy: ia memuat
`yolo11n.pt`, memilih confidence terbesar dari semua kelas, lalu memakai
fallback color detector. Adapter app-mavproxy tidak membuat detector kedua dan
menerima detection dari `postflight.offline_yolo`.

## 2. Implementasi algoritma aktual

### Camera model dan ray

`build_intrinsic_matrix()` menghitung:

```text
fx = focal_length_mm * image_width / sensor_width_mm
fy = fx
cx = image_width / 2
cy = image_height / 2
```

Script memakai konstanta eksperimen `1920x1080`, focal length `6.0 mm`, dan
sensor width `6.287 mm`. Nilai tersebut bukan hasil kalibrasi Arducam yang
tervalidasi. Tidak ada distortion correction.

`unproject_pixel_to_ray()` melakukan:

```text
d_cam_cv      = K^-1 [u, v, 1]
d_cam_blender = [d_cam_cv.x, -d_cam_cv.y, -d_cam_cv.z]
d_world       = R_world d_cam_blender
```

Ray kemudian dinormalisasi. Ini adalah camera convention bergaya Blender:
camera melihat ke arah `-Z`, dengan inversi sumbu image `Y`.

### Rotasi dan coordinate frames

`get_rotation_matrix()` membuat `Rx`, `Ry`, dan `Rz` dari Euler degrees. Default
aktualnya adalah:

```text
R_world = Rx @ Ry @ Rz
```

Script juga menyediakan `ZYX`, `YXZ`, dan `ZXY`, tetapi default adapter dikunci
ke `XYZ` agar tidak diam-diam mengganti convention. Repository tidak
mendokumentasikan NED/ENU, quaternion, atau hubungan body-to-camera.

Reference memperlakukan `R_world` sebagai rotasi camera-frame ke world-frame.
Itu berbeda dari jaminan bahwa `roll/pitch/yaw` MAVLink kendaraan sudah
merupakan camera-world attitude.

Reference tidak mendefinisikan NED/ENU atau transform body-to-camera. Adapter
memilih konvensi lokal eksplisit `X=east`, `Y=north`, `Z=up` hanya untuk MVP;
tidak ada konversi MAVLink NED otomatis. Karena itu attitude source dan
mounting convention harus divalidasi sebelum status calibrated dapat digunakan.

### Ground intersection dan output

`ray_ground_intersection()` menggunakan bidang horizontal:

```text
t = (z_ground - P_cam.z) / ray_world.z
P_ground = P_cam + t * ray_world
```

Intersection ditolak bila ray paralel, `t <= 0`, atau ray mengarah menjauhi
bidang. Output referensi hanya local `[X, Y]`; tidak ada latitude/longitude,
WGS84, origin UAV, atau target ground truth conversion di kodenya.

### Tracking dan altitude pada reference

Reference menambahkan sliding window dan Kalman filter 2D. Bagian tersebut
bukan bagian MVP adapter karena app-mavproxy sudah memiliki detection/frame
identity dan task ini berhenti pada satu detection.

Telemetry reference adalah CSV berisi `cam_x`, `cam_y`, `cam_z`,
`roll_deg`, `pitch_deg`, `yaw_deg`, serta `target_x/y/z`. `target_z` dari baris
pertama dijadikan `z_ground`, dan `cam_z` dari baris pertama hanya ditampilkan
sebagai altitude. Tidak ada semantik AGL, AMSL, relative-home, atau terrain
relative. Karena itu AMSL maupun `relative_altitude` app tidak boleh dipakai
sebagai AGL tanpa deklarasi dan validasi terpisah.

## 3. Mapping ke app-mavproxy

| Coordinate-Estimator input | app-mavproxy source | Status | Catatan |
| --- | --- | --- | --- |
| bbox/image point | `detections.jsonl.bbox_xyxy_normalized` | AVAILABLE | Adapter memakai bbox center sesuai perilaku reference. |
| `frame_id` | detection + `frames.jsonl` | AVAILABLE | Divalidasi oleh existing synchronization. |
| capture time | `frames.jsonl.capture_utc_ns` | AVAILABLE | Tidak dihitung dari `timestamp * fps`. |
| UAV latitude/longitude | synchronized detection / telemetry payload | AVAILABLE | Dipakai sebagai origin local projection. |
| UAV roll/pitch/yaw | synchronized detection / telemetry payload | AVAILABLE | Convention camera-vs-body tetap harus dinyatakan. |
| quaternion | synchronized telemetry bila tersedia | NEEDS_ADAPTER | Reference tidak memakai quaternion; MVP tetap membutuhkan Euler. |
| camera `fx/fy/cx/cy` | belum ada artifact calibration Arducam | MISSING | Adapter tidak mengisi default reference secara otomatis. |
| distortion coefficients | belum ada artifact calibration | MISSING | Reference tidak melakukan correction. |
| camera mounting extrinsics | belum ada pengukuran/contract | MISSING | Body attitude tidak boleh dianggap camera attitude. |
| camera `P_cam.x/y` | belum ada local camera position | NEEDS_ADAPTER | MVP menetapkan origin horizontal UAV `(0,0)` secara eksplisit. |
| camera altitude to ground | `relative_altitude`/AMSL tersedia | MISSING | Flat-ground adapter hanya menerima AGL eksplisit. |
| ground plane | reference `Z=z_ground` | NEEDS_ADAPTER | MVP memakai `ground_plane_z_m=0` dan altitude AGL. |
| local XY to geodetic | tidak ada di reference | NEEDS_ADAPTER | Adapter memetakan `X=east`, `Y=north` dengan small-distance WGS84 approximation. |

## 4. Adapter yang diintegrasikan

File `postflight/coordinate_reconstruction.py` mengadaptasi empat operasi
geometri reference tanpa mengubah synchronization mechanism:

```text
synchronized detection
    ↓ postflight.synchronization (existing)
frame_id → capture_utc_ns → interpolated UAV state
    ↓ CoordinateReconstructionAdapter
bbox center → Blender-compatible ray → flat ground intersection
    ↓
local X/Y (east/north) → estimated target latitude/longitude
```

`run_coordinate_reconstruction_from_artifacts()` memanggil
`synchronize_detections()` yang existing, sehingga mission identity,
`source_time_valid`, bracket source timestamp, dan complete-state guard tetap
berlaku. Adapter tidak menerima record dengan
`telemetry_sync_status != "synchronized"`; synthetic clock artifact akan
menghasilkan `NOT_AVAILABLE`. Jalur live Ground memakai adapter yang sama
setelah `frame_id` dan `capture_utc_ns` diterima dari event Jetson; ia menulis
hasil ke `detections_with_telemetry.jsonl` dan tidak mengubah telemetry receiver.
Coordinate live tetap disabled secara default sampai konfigurasi eksplisit
diaktifkan.

Calibration JSON adapter membutuhkan field eksplisit berikut:

```text
camera_id
image_width, image_height
fx, fy, cx, cy
distortion_coefficients (optional, preserved but not corrected by reference)
mounting_rpy_deg (required when attitude frame is body)
validated (must be explicitly true to emit CALIBRATED_ESTIMATE)
```

`CameraCalibration.from_reference_optics()` tersedia hanya untuk mereproduksi
parameterisasi reference bila nilai optical memang diberikan oleh caller; ia
tidak menganggap angka reference sebagai calibration Arducam.

Status output:

```text
NOT_AVAILABLE             # input/identity/state/calibration/ground ray invalid
ESTIMATED_UNCALIBRATED    # geometri menghasilkan angka, tetapi calibration belum divalidasi
CALIBRATED_ESTIMATE       # hanya jika calibration dan convention sudah divalidasi
```

Altitude harus dinyatakan `AGL`. `AMSL`, `RELATIVE_HOME`, dan
`TERRAIN_RELATIVE` ditolak oleh flat-ground MVP agar tidak disamakan dengan
AGL. Adapter memakai `camera_attitude_frame=body` secara default dan
mengomposisikan `R_world_body @ R_body_camera` memakai rotation order reference;
mounting extrinsics wajib tersedia. Mode `camera_world` hanya boleh dipakai
bila input attitude memang sudah merupakan pose kamera.

## 5. Test status

Sebelum integrasi:

```text
Coordinate-Estimator repository: 0 formal tests (compile check passed)
app backend:                     41 tests passed
app postflight existing:          3 tests passed
app Jetson existing:              8 tests passed
```

Sesudah adapter dan live ingestion:

```text
postflight coordinate tests:     15 tests passed
postflight full suite:           20 tests passed
backend suite:                   51 tests passed
Jetson suite:                     8 tests passed
scripts suite:                    5 tests passed
frontend production build:       passed
Rust cargo test:                  passed, 0 test cases
```

Test baru mencakup center ray, left/right, forward/back, yaw, roll, pitch,
perubahan altitude, horizon rejection, local ENU conversion, altitude guard,
synthetic-clock rejection, typed calibration parsing, missing mounting guard,
uncalibrated status, dan full artifact path melalui existing source-time
synchronization.

Parity check terhadap fungsi aktual reference pada commit yang diaudit juga
lulus untuk intrinsic matrix, seluruh empat rotation order yang tersedia,
pixel-to-ray, dan ground intersection. Smoke check terhadap 47 record prototype
synthetic-clock menghasilkan `NOT_AVAILABLE` untuk 47/47 dengan error
`TELEMETRY_NOT_SYNCHRONIZED`.

## 6. Map target rendering smoke test

`src/components/map/OperationalMap.jsx` menerima prop `coordinate` yang
diubah menjadi source GeoJSON `coordinate-target`. Hanya status
`ESTIMATED_UNCALIBRATED` dan `CALIBRATED_ESTIMATE` dengan latitude/longitude
valid yang dirender. Dot amber berarti hasil belum calibrated; dot hijau
dicadangkan untuk hasil calibrated. Label juga membawa kelas, frame, dan
confidence.

Fixture `src/data/coordinateSmokeTest.js` berasal dari detection pedestrian
nyata `frame_id=1919` dan hasil adapter yang telah dihitung sebelumnya. Untuk
memastikan kontraknya:

```bash
npm run test:map
npm run build
```

Hasil: 3/3 map contract tests lulus dan production build lulus. Fixture dapat
dilihat dengan `npm run dev` lalu membuka
`http://localhost:5173/?coordinate_smoke_test=1`; peta akan fokus ke dot
`TARGET · SMOKE` pada latitude `-7.5898935539`, longitude `110.8653516205`.

Ini bukan qualification evidence: fixture masih menandai
`source_telemetry_status=prototype_synthetic_clock_aligned`, memakai asumsi
AGL 10 m, dan `calibration_validated=false`. Pada runtime normal, backend akan
mem-poll `/api/v1/detection/latest`, tetapi dot live hanya muncul jika event
tersinkron dan `VISION_COORDINATE_ENABLED=true` dengan input calibration yang
sesuai. Default aman menghasilkan `NOT_AVAILABLE`, sehingga tidak ada dot
palsu.

Perintah:

```bash
PYTHONPATH=. python3 -m unittest discover -s postflight/tests -p 'test_*.py'
```

## 7. Current MVP result and limitations

Positive detection `pedestrian` pada `frame_id=1919` sudah memiliki visual
verification dan exact frame metadata. Prototype telemetry sebelumnya sengaja
menggunakan synthetic clock alignment dan sekarang ditolak adapter. Footage
tersebut bertanggal 12 Agustus, sedangkan log telemetry yang tersedia bertanggal
25 Agustus; keduanya bukan mission/time pair yang valid. Live adapter/ingest
plumbing sudah tersedia, tetapi belum ada same-mission coordinate qualification.

Karena itu belum ada coordinate result yang boleh disebut physical atau
qualification evidence. Blocker yang tersisa:

1. telemetry dan footage harus direkam pada mission yang sama dengan UTC overlap;
2. calibration intrinsics Arducam harus diukur/disimpan;
3. mounting orientation dan body/camera frame convention harus diukur;
4. altitude AGL atau terrain-relative harus tersedia secara reliable;
5. ground-truth target GPS diperlukan untuk menghitung error horizontal meter.

Original flight footage dan telemetry evidence tidak disentuh oleh adapter.
Live coordinate reconstruction sekarang tersedia sebagai opt-in plumbing dengan
status non-qualification; DEM, tracking, multi-view, flight command, dan
manual detection tetap di luar scope. `postflight/replay.py` sekarang
menyediakan replay frame–telemetry receive-only; UI/3D replay interaktif tetap
belum diimplementasikan.
