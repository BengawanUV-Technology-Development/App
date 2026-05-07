# Store (Global State Management)
Folder ini berisi *state management* global menggunakan Zustand. Tujuannya adalah mendistribusikan data ke seluruh komponen React secara efisien tanpa harus melakukan *prop-drilling* (mengoper data dari komponen induk ke anak secara berantai) yang dapat menyebabkan *re-render* massal.

## Daftar File & Fungsinya
* **`telemetryStore.js`**: Menyimpan data berfrekuensi tinggi (5-10Hz) seperti "The Big 6" (Altitude, Speed, Battery, dll) dan data orientasi HUD (Pitch, Roll, Heading).
    * *Interaksi:* Menerima pasokan data langsung dari `services/websocket.js` di luar siklus React, dan datanya dikonsumsi oleh `components/rightsidebar/` serta `components/centerarea/HUDOverlay.jsx`.
* **`droneStateStore.js`**: Menyimpan status sistem yang krusial seperti status *Armed/Disarmed*, *Flight Mode* aktif, dan status koneksi *WebSocket*.
    * *Interaksi:* Diperbarui berdasarkan *feedback* dari backend (via `websocket.js` atau `api.js`). Dikonsumsi oleh `components/topbar/` dan `components/leftsidebar/`.
* **`uiStore.js`**: Mengelola status tampilan antarmuka, seperti apakah panel *Waypoint* sedang terbuka atau tertutup.
    * *Interaksi:* Diisolasi dari logika *drone* agar interaksi UI tidak mengganggu data penerbangan.

## Aturan Penggunaan
Jangan gunakan `useState` lokal di komponen jika data tersebut perlu diakses oleh komponen lain di luar zonanya. Masukkan ke dalam store.