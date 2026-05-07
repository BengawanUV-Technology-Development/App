# Center Area (Vision Zone - Nav & HUD)

Zona tengah adalah area observasi visual utama yang menggunakan trik CSS Z-Index agar elemen bisa bertumpuk (*layering*) tanpa mengganggu interaksi kursor (*mouse*).

## Daftar File & Fungsinya
* **`CenterArea.jsx`**: Induk pembungkus untuk area tengah. Menyuntikkan `useMapLogic` ke komponen anak-anaknya.
* **`MapOverview.jsx` (Layer 0)**: Menggunakan `react-leaflet`. Menampilkan peta dasar, menggambar titik *waypoint*, rute penerbangan, dan mendeteksi klik kursor untuk membuat misi baru.
* **`HUDOverlay.jsx` (Layer 1)**: Komponen `<canvas>` transparan. Secara kontinu memanggil `hudRenderer.js` setiap kali ada pembaruan *Pitch*, *Roll*, dan *Heading*.
    * *Sifat Khusus:* Menggunakan `pointer-events: none` agar klik *mouse* bisa tembus melewatinya dan mengenai peta di bawahnya.
* **`WaypointPanel.jsx` (Layer 2)**: Panel mengambang (*floating*) untuk melihat, mengedit ketinggian (Alt), dan menghapus daftar titik *waypoint*, serta tombol untuk *upload* misi ke FCU.