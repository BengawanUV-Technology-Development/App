# Right Sidebar (Data Zone / Persistent Telemetry)

Zona ini bertugas menampilkan angka metrik penerbangan ("The Big 6") secara terus-menerus tanpa pernah tertutup oleh elemen UI lain.

## Daftar File & Fungsinya
* **`RightSidebar.jsx`**: Induk wadah zona kanan.
* **`TelemetryGrid.jsx`**: Mengambil nilai *Altitude*, *Speed*, *Battery*, dll dari `telemetryStore.js` dan menerapkan logika peringatan visual (contoh: baterai lemah berubah menjadi merah/kuning).
* **`TelemetryItem.jsx`**: Komponen atomik (*reusable*) untuk mencetak satu kotak metrik. Menggunakan tipografi *Monospace* agar deretan angka yang berkedip cepat tidak menyebabkan tampilan teks melompat-lompat (*layout shift*).