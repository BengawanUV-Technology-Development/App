# Utils (Pure Functions & Helpers)

Folder ini berisi fungsi matematika, konversi, atau algoritma murni yang tidak bergantung pada React (tidak menggunakan *hooks* atau JSX). Tujuannya untuk membongkar beban komputasi dari komponen.

## Daftar File & Fungsinya
* **`formatters.js`**: Fungsi untuk merapikan teks/angka (misal: memotong desimal GPS, konversi m/s ke km/jam, memformat detik ke MM:SS).
    * *Interaksi:* Dipanggil oleh UI di `components/rightsidebar/` dan `components/centerarea/`.
* **`mapHelpers.js`**: Berisi formula spasial, seperti kalkulasi jarak *Haversine* antar koordinat GPS.
    * *Interaksi:* Digunakan oleh `hooks/useMapLogic.js` untuk menghitung total jarak misi.
* **`hudRenderer.js`**: Algoritma Vanilla JavaScript untuk menggambar kokpit pesawat (Pitch, Roll, Heading) di atas elemen HTML5 `<canvas>`.
    * *Interaksi:* Jantung performa visualisasi. Secara eksklusif dipanggil oleh `components/centerarea/HUDOverlay.jsx` setiap kali ada perubahan data di `telemetryStore.js`.