# Top Bar (Header / Vital Connectivity)

Zona atas digunakan untuk pemantauan koneksi dasar tingkat sistem.

## Daftar File & Fungsinya
* **`TopBar.jsx`**: Induk wadah zona atas.
* **`ConnectionPanel.jsx`**: Tempat memilih port komunikasi (UDP/Serial) dan menyalakan/mematikan koneksi *WebSocket*. Menampilkan indikator LED *Heartbeat* virtual.
* **`SystemClock.jsx`**: Menampilkan waktu absolut (UTC/Lokal) yang terus berdetak tanpa memengaruhi atau membebani siklus *render* antarmuka lainnya.