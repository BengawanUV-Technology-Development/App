# Layout (The Skeleton)

Folder ini bertanggung jawab atas tata letak global tingkat teratas.

## Daftar File & Fungsinya
* **`MainLayout.jsx`**: Komponen induk yang menyatukan kelima zona (Top, Left, Center, Right, Bottom) ke dalam satu halaman utuh (Single-Page Dashboard).
* **`MainLayout.module.css`**: Mendefinisikan struktur CSS Grid yang kaku (*rigid*). Di sini juga terdapat logika fitur *Resizer* (tuas penarik) untuk memperbesar/memperkecil panel *Bottom Bar* secara dinamis.
    * *Interaksi:* Menjadi wadah absolut bagi semua komponen zona lainnya. Tidak mengelola *state* data penerbangan, melainkan murni untuk tata letak (*layouting*).