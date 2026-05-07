# Components (User Interface Elements)

Folder ini adalah tulang punggung visual dari GCS. Seluruh komponen React di sini dirancang dengan filosofi *Functional-First* dan mematuhi arsitektur *3-Column Grid* untuk mencegah tumpang tindih visual (kognitif *overload* pada operator).

Setiap sub-folder di dalam direktori ini merepresentasikan **Zona Spesifik** pada layar. Komponen-komponen ini difokuskan hanya untuk *rendering* antarmuka, sedangkan logika bisnis berat dioper ke `hooks/` dan `store/`.