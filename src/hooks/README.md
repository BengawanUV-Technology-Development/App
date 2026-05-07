# Hooks (Custom Logic Wrappers)

Folder ini berisi *Custom React Hooks* yang bertugas sebagai jembatan antara antarmuka (Components) dengan layanan jaringan (Services) dan status global (Store). Hooks membungkus logika rumit (seperti *loading state* atau *error handling*) agar file UI tetap bersih dan rapi.

## Daftar File & Fungsinya
* **`useDroneCommand.js`**: Membungkus fungsi dari `api.js` dengan penambahan state `isLoading` dan `error`.
    * *Interaksi:* Digunakan oleh `components/leftsidebar/` agar tombol ARM atau Mode bisa menampilkan indikator *loading* saat perintah sedang dikirim ke *drone*.
* **`useMapLogic.js`**: Mengelola status titik kordinat misi (*waypoints*) dan menyediakan fungsi helper untuk peta (tambah titik, hapus titik, hitung jarak).
    * *Interaksi:* Dikonsumsi oleh `components/centerarea/` (MapOverview dan WaypointPanel).
* **`useTelemetry.js`**: Mengelola siklus hidup (*lifecycle*) sambungan `websocket.js`, memastikan koneksi ditutup dengan aman saat GCS dimatikan.
    * *Interaksi:* Dipanggil oleh tombol "CONNECT" di `components/topbar/`.