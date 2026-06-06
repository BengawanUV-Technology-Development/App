# Mission Planner Bridge

Folder ini berisi feasibility spike untuk menjadikan Mission Planner sebagai
sumber telemetry dan command kendaraan.

## Isi

- `mission_planner_bridge.py`: dijalankan dari jendela Python Script Mission
  Planner.
- `fake_bridge.py`: bridge simulasi untuk pengembangan tanpa Mission Planner.
- `verify_bridge.py`: memeriksa kontrak health dan telemetry tanpa mengirim
  command kendaraan.

## Menjalankan Fake Bridge

```powershell
python mission-planner/fake_bridge.py
```

Pada terminal lain:

```powershell
python mission-planner/verify_bridge.py
```

Untuk ikut menguji endpoint command pada fake bridge:

```powershell
python mission-planner/verify_bridge.py --test-mode Q_HOVER
```

## Menjalankan di Mission Planner

1. Hubungkan Mission Planner ke SITL atau flight controller.
2. Pastikan unit Mission Planner menggunakan metric karena beberapa nilai `cs`
   mengikuti unit tampilan Mission Planner.
3. Buka `Flight Data > Scripts`.
4. Muat dan jalankan `mission_planner_bridge.py`.
5. Periksa:

   ```text
   http://127.0.0.1:5000/api/v1/health
   http://127.0.0.1:5000/api/v1/telemetry
   ```

6. Jalankan verifier:

   ```powershell
   python mission-planner/verify_bridge.py
   ```

Bridge hanya bind ke `127.0.0.1`, sehingga tidak dapat diakses langsung dari
komputer lain.

## Endpoint Awal

```text
GET  /api/v1/health
GET  /api/v1/telemetry
POST /api/v1/commands/set-flight-mode
```

Jangan menguji command pada wahana nyata untuk feasibility spike. Gunakan SITL:

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:5000/api/v1/commands/set-flight-mode `
  -ContentType application/json `
  -Body '{"request_id":"manual-sitl-test","mode":"Q_HOVER"}'
```

## Batasan Spike

- Script menargetkan IronPython 2.7 yang tertanam dalam Mission Planner.
- Telemetry diambil dari objek `cs` Mission Planner.
- Script belum menyediakan arm/disarm atau mission command.
- Script belum diuji di dalam Mission Planner dari workspace ini.
- Jika server di dalam scripting Mission Planner tidak stabil, gunakan proses
  bridge terpisah tanpa mengubah kontrak API.
