# Tauri + React + Python

Proyek ini adalah aplikasi desktop dengan Tauri sebagai pembungkus aplikasi, React sebagai frontend, dan Python Flask sebagai backend API.

Tujuan utamanya adalah membuat aplikasi desktop yang bisa mengambil data dari Python lewat HTTP API, misalnya untuk data koordinat, status perangkat, atau hasil proses komputasi lain.

## Gambaran Singkat

- Frontend jalan di React/Vite.
- Tauri dipakai untuk membungkus aplikasi jadi desktop app.
- Python Flask menyediakan API di `http://localhost:5001`.
- React mengambil data dari endpoint Python dengan `fetch()`.

Contoh endpoint yang dipakai sekarang:

- `GET /get-coordinates`
- Response contoh:

```json
{
	"lat": -7.5588,
	"lng": 110.8562,
	"alt": 100
}
```

## Alur Data

1. Python Flask dijalankan di port `5001`.
2. React memanggil API Python lewat `fetch('http://localhost:5001/get-coordinates')`.
3. Data JSON diterima oleh React.
4. Data ditampilkan di UI atau dipakai untuk proses lain.

## Struktur Peran Tiap Bagian

- `src/App.jsx` - frontend React yang memanggil API Python.
- `src-tauri/src-python/main.py` - backend Flask.
- `src-tauri/tauri.conf.json` - konfigurasi Tauri.
- `src-tauri/capabilities/default.json` - izin kemampuan Tauri.
- `src-tauri/Cargo.toml` - dependensi Rust dan plugin Tauri.

## Cara Menjalankan

### Mode Development

Kalau Python dijalankan terpisah:

1. Jalankan Flask:

```bash
cd src-tauri/src-python
python main.py
```

2. Jalankan Tauri/React:

```bash
npm run tauri dev
```

React akan mengambil data dari port `5001`.

### Mode Sidecar / Satu Paket

Kalau Python ingin ikut dibawa oleh aplikasi Tauri, Python biasanya di-compile menjadi executable lalu dijalankan sebagai sidecar.

Contoh alur:

1. Python dibuild menjadi `.exe`.
2. File executable disimpan di folder `src-tauri/binaries/`.
3. Tauri menjalankan executable itu saat app dibuka.
4. React tetap mengambil data lewat `http://localhost:5001`.

## Contoh Kode Frontend

```javascript
const response = await fetch('http://localhost:5001/get-coordinates');
const data = await response.json();
console.log(data);
```

## Perbandingan: Python Terpisah vs Python Jadi Sidecar

| Opsi | Cara Jalan | Kelebihan | Kekurangan |
|---|---|---|---|
| Python terpisah | Python dan Tauri dijalankan sebagai 2 proses berbeda | Simpel untuk development, debug Python mudah, tidak perlu build exe dulu | User harus menyalakan Python manual, rawan port belum aktif |
| Python sidecar | Python dibundel lalu dijalankan otomatis oleh Tauri | Lebih rapi untuk distribusi, user cukup buka 1 aplikasi saja | Setup build lebih rumit, perlu compile Python jadi executable |

## Kapan Pakai Yang Mana

- Pakai **Python terpisah** kalau kamu masih sering ubah-ubah logika backend dan ingin debugging cepat.
- Pakai **sidecar** kalau kamu sudah ingin aplikasi siap dibagikan ke user lain dengan pengalaman buka satu aplikasi saja.

## Catatan Penting

- Pastikan port Python sama dengan yang dipakai frontend, yaitu `5001`.
- Kalau port berubah, update juga URL `fetch()` di React.
- Kalau Flask belum jalan, status di UI akan gagal konek.

## Docker

Kalau kamu mau pakai Docker, yang paling cocok untuk proyek ini adalah **backend Python**. Tauri desktop app biasanya tetap dijalankan langsung di host, sedangkan Python bisa dijalankan di container supaya lebih rapi dan mudah dipisahkan.

### Apa yang Di-Docker

- Python Flask backend.
- Dependency Python seperti Flask dan Flask-CORS.
- Port API, misalnya `5001`, di-expose ke host.

Yang biasanya **tidak perlu** di-docker:

- Frontend React untuk aplikasi desktop Tauri.
- Tauri app itu sendiri, karena hasil akhirnya adalah aplikasi desktop, bukan web server biasa.

### Gambaran Kerja Docker

1. Kamu membuat image Docker untuk Python backend.
2. Container dijalankan dan membuka port `5001`.
3. App Tauri di host memanggil API ke `http://localhost:5001`.
4. React menerima data JSON dari Flask seperti biasa.

### Alur File yang Biasanya Dibuat

Kalau kamu mau bikin sendiri, biasanya file-nya seperti ini:

- `src-tauri/src-python/Dockerfile` untuk build image Python.
- `src-tauri/src-python/requirements.txt` untuk dependency Python.
- `docker-compose.yml` kalau mau jalankan Python container dengan mudah.

### Contoh Isi Docker yang Perlu Dipikirkan

Di Dockerfile Python, biasanya ada isi seperti ini:

- base image Python, misalnya `python:3.12-slim`
- copy file backend ke image
- install dependency dari `requirements.txt`
- expose port `5001`
- jalankan `main.py`

Di `docker-compose.yml`, biasanya ada:

- service untuk backend Python
- mapping port `5001:5001`
- optional environment variable kalau dibutuhkan

### Cara Menjalankan

Kalau backend Python sudah di-docker, jalankan seperti ini:

```bash
docker compose up --build
```

Lalu jalankan Tauri seperti biasa:

```bash
npm run tauri dev
```

React tetap fetch ke:

```text
http://localhost:5001/get-coordinates
```

### Kenapa Cocok untuk Proyek Ini

- Backend Python bisa dipisahkan dari app desktop.
- Setup development lebih rapi.
- Port API jelas dan mudah dijelaskan saat presentasi.
- Mudah dipakai kalau kamu mau bilang aplikasi ini punya frontend Tauri dan backend Python yang berjalan bersamaan.

### Kalau Mau Distribusi

Untuk distribusi aplikasi desktop, biasanya Docker bukan bagian utama yang dipakai user akhir. Docker lebih cocok untuk development, testing, atau kalau backend Python ingin dijalankan sebagai service terpisah.

Jadi singkatnya:

- **Docker dipakai untuk Python backend**
- **Tauri tetap jalan di host sebagai desktop app**
- **React fetch data dari port Python**

## Recommended IDE Setup

- [VS Code](https://code.visualstudio.com/) + [Tauri](https://marketplace.visualstudio.com/items?itemName=tauri-apps.tauri-vscode) + [rust-analyzer](https://marketplace.visualstudio.com/items?itemName=rust-lang.rust-analyzer)
