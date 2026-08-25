# Aktivasi chrony / NTP Ground–Jetson

Dokumen ini mengaktifkan kontrak R0: Ground Laptop menjadi chrony server dan
Jetson menjadi chrony client. Jetson tidak memakai Internet NTP secara langsung
sebagai sumber operasi.

Pada macOS/Linux, Ground menggunakan `chronyd`. Windows tidak menyediakan
`chronyd` native, sehingga profil Windows menggunakan Windows Time (`W32Time`)
sebagai NTP server kompatibilitas; Jetson tetap menggunakan chrony sebagai
client. Jika kepatuhan literal terhadap “Ground adalah chrony server” wajib,
gunakan macOS/Linux Ground.

Alamat Tailscale yang digunakan pada setup saat ini:

```text
Ground  100.114.81.87
Jetson  100.124.21.25
NTP     UDP/123
```

Jika alamat berubah, ganti nilai tersebut pada perintah di bawah. Password SSH
dan password administrator dimasukkan secara interaktif; jangan menaruhnya di
file konfigurasi atau repository.

## 1. Aktifkan Ground

Jalankan dari root repository `App` di Mac Ground:

```bash
./scripts/setup_chrony_ground_macos.sh \
  --ground-ip 100.114.81.87 \
  --jetson-ip 100.124.21.25
```

Script ini akan:

- memasang chrony melalui Homebrew bila belum tersedia;
- membuat konfigurasi server lokal dan mengizinkan hanya IP Jetson;
- menonaktifkan macOS Network Time agar tidak bersaing dengan chronyd;
- mendaftarkan `com.bengawan.chrony-ground` sebagai LaunchDaemon;
- membuat backup konfigurasi lama sebelum menggantinya.

Internet NTP tidak diperlukan. Jika ingin Ground juga mengambil referensi waktu
eksternal ketika tersedia, tambahkan misalnya `--upstream time.apple.com`.

## 2. Profil Ground Windows

Jalankan PowerShell **Run as administrator** pada Windows Ground. Cari alamat
IPv4 interface yang dipakai menuju Jetson, misalnya alamat Tailscale dengan
`tailscale ip -4`, lalu ganti nilai `$WindowsGroundIp` berikut:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
$WindowsGroundIp = "100.x.y.z"
.\scripts\setup_chrony_ground_windows.ps1 `
  -GroundIp $WindowsGroundIp `
  -JetsonIp "100.124.21.25"
```

Secara default Windows memakai clock lokal sebagai sumber dan tidak memerlukan
Internet NTP. Jika Windows juga ingin didisiplinkan oleh upstream, tambahkan:

```powershell
.\scripts\setup_chrony_ground_windows.ps1 `
  -GroundIp $WindowsGroundIp `
  -JetsonIp "100.124.21.25" `
  -Upstream "time.windows.com"
```

Helper ini mengaktifkan provider NTP Windows, membuat rule inbound UDP/123 yang
hanya mengizinkan IP Jetson, menyimpan backup registry W32Time, dan mengatur
service `W32Time` agar aktif saat boot. Microsoft mendokumentasikan konfigurasi
NTP server melalui `AnnounceFlags`, provider `NtpServer`, dan `w32tm` pada
[Windows Time Service Tools and Settings](https://learn.microsoft.com/en-us/windows-server/networking/windows-time-service/Windows-Time-Service-Tools-and-Settings).

Verifikasi read-only di Windows:

```powershell
.\scripts\verify_windows_time_server.ps1 -JetsonIp "100.124.21.25"
w32tm /query /source
w32tm /query /status
```

Rollback Windows menggunakan backup terbaru:

```powershell
.\scripts\setup_chrony_ground_windows.ps1 -Rollback
```

Atau tentukan file backup secara eksplisit dengan `-BackupFile`.

## 3. Aktifkan Jetson

Salin helper dan jalankan dari Mac Ground:

```bash
scp scripts/setup_chrony_jetson.sh \
  bengawan@100.124.21.25:/tmp/setup_chrony_jetson.sh

ssh -tt bengawan@100.124.21.25 \
  "sudo bash /tmp/setup_chrony_jetson.sh --ground-ip 100.114.81.87"
```

Script Jetson akan memasang chrony bila perlu, mematikan
`systemd-timesyncd`, membuat backup `/etc/chrony/chrony.conf`, dan mengaktifkan
service `chrony` saat boot.

## 4. Verifikasi

Di Ground macOS:

```bash
/opt/homebrew/bin/chronyc -h 127.0.0.1 -n tracking
/opt/homebrew/bin/chronyc -h 127.0.0.1 -n sources -v
python3 scripts/verify_chrony.py \
  --role ground-server \
  --chronyc-path /opt/homebrew/bin/chronyc
```

Di Ground Windows gunakan verifier PowerShell pada bagian sebelumnya. Di Jetson:

```bash
chronyc -n tracking
chronyc -n sources -v
```

Kriteria clock untuk short flight:

- `Leap status : Normal`;
- offset absolut maksimal 5 ms pada helper verifier;
- pada Jetson terdapat source Ground bertanda `^*`;
- tidak ada `systemd-timesyncd` aktif di Jetson;
- UDP/123 dari Jetson ke IP Ground dapat lewat interface Tailscale.

Jika Jetson belum memilih `^*`, periksa firewall Ground (macOS atau Windows),
interface Tailscale, dan pastikan Ground script sudah berjalan. Jangan
menjalankan dua time service pada Jetson.

## 5. Rollback macOS dan Jetson

Jika perlu kembali ke service bawaan sementara:

Di Ground:

```bash
sudo launchctl bootout system/com.bengawan.chrony-ground
sudo systemsetup -setusingnetworktime on
```

Di Jetson:

```bash
sudo systemctl disable --now chrony
sudo systemctl unmask systemd-timesyncd
sudo systemctl enable --now systemd-timesyncd
```

Konfigurasi lama tidak dihapus; script menyimpannya dengan suffix
`.pre-bengawan-<UTC timestamp>`.
