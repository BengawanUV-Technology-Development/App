# Services (Network & Communication Layer)

Lapisan ini bertanggung jawab 100% untuk komunikasi ke luar (eksternal) menuju Flight Controller atau backend Flask (MAVSDK). Komponen React **tidak boleh** melakukan *fetch* API atau membuka WebSocket secara langsung.

## Daftar File & Fungsinya
* **`api.js`**: Kumpulan fungsi REST API (`fetch`) untuk mengirim perintah spesifik yang membutuhkan kepastian respons HTTP (Command & Control). Berisi fungsi seperti `armDrone()`, `setMode()`, dan `uploadWaypoints()`.
    * *Interaksi:* Dipanggil oleh `hooks/useDroneCommand.js` dan komponen yang memiliki tombol aksi seperti `ConfigQuick.jsx`.
* **`websocket.js`**: Skrip Vanilla JS untuk menangani koneksi *WebSocket* dua arah secara persisten.
    * *Interaksi:* Menerima aliran data 10Hz dari backend dan **secara langsung menginjeksinya (bypass React render)** ke dalam `store/telemetryStore.js` menggunakan metode `.getState()`.

## Aturan Penggunaan
Jika backend mengubah *endpoint* API atau port, perubahannya cukup dilakukan di satu tempat di dalam folder ini.