# Bottom Bar (Status Zone / Logs & Config)

Zona bawah digunakan untuk memberikan umpan balik tekstual terperinci kepada operator dan melakukan pengaturan konfigurasi yang cepat tanpa harus berpindah layar.

## Daftar File & Fungsinya
* **`BottomBar.jsx`**: Induk wadah zona bawah.
* **`MessageStream.jsx`**: Konsol log mirip terminal. Menampilkan rentetan pesan MAVLink dari *Flight Controller* secara *real-time*. Dilengkapi fitur *auto-scroll* ke pesan terbaru.
* **`ConfigQuick.jsx`**: Panel form sederhana untuk mengubah parameter penting saat terbang, seperti ketinggian RTL atau kecepatan *Waypoint*, beserta eksekusi kalibrasi sensor.