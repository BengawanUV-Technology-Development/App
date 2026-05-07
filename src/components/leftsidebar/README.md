# Left Sidebar (Action Zone / C2)

Zona kiri didedikasikan untuk *Command & Control* (C2). Ini adalah zona berisiko tinggi (*safety-critical*). Desain tombol di sini mematuhi *Fitts's Law* (area klik besar).

## Daftar File & Fungsinya
* **`LeftSidebar.jsx`**: Induk wadah zona kiri.
* **`ArmDisarm.jsx`**: Komponen untuk tombol motor/propulsi. Menggunakan peringatan warna merah (*Danger*) dan terisolasi secara visual dari tombol lain.
* **`FlightModes.jsx`**: Tombol mode penerbangan (FBWA, AUTO, Q_HOVER, dll).
    * *Interaksi:* Memanggil fungsi eksekusi API dari `hooks/useDroneCommand.js` dan mencerminkan status terbaru dari `store/droneStateStore.js`.