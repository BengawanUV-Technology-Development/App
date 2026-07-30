# Jetson Computer Vision Pipeline (Phase 16 & 17)
**Handover Document for CV Developer**

Dokumen ini berisi panduan dan *contract* API untuk *developer* yang akan mengerjakan bagian Computer Vision (Object Detection) menggunakan perangkat *companion computer* seperti NVIDIA Jetson (atau Raspberry Pi).

## 1. Arsitektur Komunikasi
Jetson bertugas murni sebagai **Sensor (Mata)**.
- Jetson TIDAK mengambil keputusan misi.
- Jetson TIDAK langsung mengirim peringatan ke kru darat.
- Tugas Jetson HANYALAH mendeteksi objek, menghitung koordinat (jika bisa), lalu **menembakkan HTTP POST Request** ke backend Flask (Ground Control Station).

Otak pengambil keputusan (AI Agent / Gemini) berada di *backend* Flask (`main.py`), bukan di Jetson.

## 2. API Endpoint Contract
Setiap kali Jetson mendeteksi korban dengan tingkat keyakinan (confidence) yang valid, skrip Python di Jetson harus mengirimkan *payload* JSON ke *endpoint* berikut:

**URL Endpoint:** `POST http://<IP_GROUND_CONTROL_STATION>:5001/api/v1/detection/ingest`
*(Catatan: Ganti `<IP_GROUND_CONTROL_STATION>` dengan IP komputer GCS Anda atau `127.0.0.1` jika berjalan di mesin yang sama).*

### Format JSON (Payload)
Jetson harus mengirimkan *payload* JSON dengan struktur persis seperti ini:

```json
{
  "detection_id": "DET-123456789",
  "timestamp": "2026-07-30T10:00:00Z",
  "drone_id": "BENGAWAN-UAV-01",
  "detection_data": {
    "class": "person",
    "count": 1,
    "confidence_avg": 0.85,
    "image_snapshot_url": "https://url-ke-foto-hasil-crop.com/snapshot.jpg" 
  },
  "reconstructed_location": {
    "latitude": -7.558412,
    "longitude": 110.85621,
    "estimated_margin_error_m": 1.2
  }
}
```

### Penjelasan Field:
1. `detection_id`: String unik untuk deteksi ini (bisa menggunakan `uuid` atau UNIX timestamp).
2. `timestamp`: Waktu saat objek terdeteksi (format ISO 8601).
3. `detection_data.count`: Jumlah objek ("person") yang terdeteksi dalam satu *frame*.
4. `detection_data.confidence_avg`: Rata-rata tingkat akurasi / *confidence score* dari model YOLO (0.0 sampai 1.0).
5. `reconstructed_location`: (Tahap Lanjut/Fase 17). Ini adalah hasil konversi dari *Bounding Box* piksel ke koordinat GPS Dunia Nyata menggunakan data telemetri (Pitch, Roll, Yaw, Altitude, Gimbal Angle). Jika fitur perhitungan ini belum jadi, Anda bisa mengirimkan koordinat dummy atau `null` terlebih dahulu.

## 3. Skrip Referensi (Mock)
Sebagai referensi cara melakukan HTTP POST tanpa menginstal *library* berat, Anda bisa melihat file `src-tauri/src-py/mock_jetson.py`. Skrip tersebut adalah *stub/mock* murni yang menstimulasikan pengiriman data seperti format di atas.

## 4. Langkah Pengembangan (To-Do list untuk CV Dev):
- [ ] Buat skrip `jetson_cv.py` (bisa menggunakan OpenCV & PyTorch/Ultralytics YOLOv8).
- [ ] Buka *stream* kamera RTSP atau webcam.
- [ ] Lakukan inferensi `model.predict()`.
- [ ] *Filter* hanya *bounding box* dengan kelas "person" (atau kelas relevan lainnya) dan *confidence* > 0.60.
- [ ] Kumpulkan data jumlah orang, lalu bangun *dictionary* Python sesuai format JSON di atas.
- [ ] Gunakan `urllib.request` atau `requests` untuk menembak ke *endpoint* Ingest.
- [ ] *(Opsional)* Terapkan logika *debouncing* (misalnya: hanya kirim HTTP POST 1 kali setiap 3 detik jika mendeteksi objek yang sama, agar server tidak kebanjiran *request* (DDoS)).
