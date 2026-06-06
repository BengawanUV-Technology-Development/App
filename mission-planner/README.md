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

Port `5000` hanya dapat digunakan satu proses. Jika bridge Mission Planner nyata
sedang berjalan, jalankan fake bridge pada port lain:

```powershell
python mission-planner/fake_bridge.py --port 5002
python mission-planner/verify_bridge.py --base-url http://127.0.0.1:5002
```

Untuk ikut menguji endpoint command pada fake bridge:

```powershell
python mission-planner/verify_bridge.py --test-mode FBWA
```

Saat `--test-mode` digunakan, verifier tidak hanya memeriksa response command.
Verifier juga menunggu telemetry mengonfirmasi mode tujuan selama maksimal lima
detik.

## Menjalankan di Mission Planner

1. Hubungkan Mission Planner ke SITL atau flight controller.
2. Pastikan unit Mission Planner menggunakan metric karena beberapa nilai `cs`
   mengikuti unit tampilan Mission Planner.
3. Buka `Flight Data > Scripts`.
4. Muat dan jalankan `mission_planner_bridge.py`.
   Bridge akan menutup listener dari versi script sebelumnya sebelum membuka
   port `5000` kembali.

   Untuk upgrade pertama dari bridge versi sebelum fitur reload-safe, tutup dan
   buka kembali Mission Planner satu kali. Listener versi lama tidak menyimpan
   referensi yang dapat ditutup oleh script baru.
5. Periksa:

   ```text
   http://127.0.0.1:5000/api/v1/health
   http://127.0.0.1:5000/api/v1/telemetry
   ```

   Membuka `http://127.0.0.1:5000/` akan menghasilkan `Route not found`. Itu
   normal karena bridge hanya menyediakan route `/api/v1/...`.

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
  -Body '{"request_id":"manual-sitl-test","mode":"FBWA"}'
```

Untuk command SITL yang sekaligus memverifikasi perubahan mode dari telemetry:

```powershell
python mission-planner/verify_bridge.py --test-mode FBWA
```

Gunakan mode yang memang tersedia untuk vehicle SITL:

- Plane biasa: `MANUAL`, `FBWA`, `AUTO`, atau `RTL`.
- QuadPlane dengan konfigurasi `Q_ENABLE`: `Q_HOVER`, `Q_STABILIZE`, atau
  `Q_LAND`.

Response command hanya berarti Mission Planner berhasil mengirim permintaan.
Flight controller masih dapat menolak atau langsung mengembalikan mode karena
mode tidak didukung, mission belum siap, atau safety/failsafe. Verifier
memastikan perubahan akhirnya dikonfirmasi melalui telemetry.

Temuan pengujian SITL:

- Dengan `Q_ENABLE=0`, permintaan `Q_HOVER` diterima Mission Planner tetapi
  telemetry tetap melaporkan `Manual`.
- Setelah `Q_ENABLE=1`, permintaan yang sama berhasil dan telemetry
  mengonfirmasi `QHOVER`.
- Konfigurasi parameter tetap dilakukan melalui Mission Planner, bukan melalui
  bridge BUV.

## Batasan Spike

- Script menargetkan IronPython 2.7 yang tertanam dalam Mission Planner.
- Telemetry diambil dari objek `cs` Mission Planner.
- Script belum menyediakan arm/disarm atau mission command.
- Script sudah diuji dengan Mission Planner dan SITL untuk health, telemetry,
  dan pengiriman permintaan perubahan mode.
- Menghentikan script tidak selalu langsung menghentikan daemon HTTP listener.
  Menjalankan ulang bridge versi terbaru akan mengganti listener lama.
- Jika server di dalam scripting Mission Planner tidak stabil, gunakan proses
  bridge terpisah tanpa mengubah kontrak API.
