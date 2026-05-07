// src/utils/hudRenderer.js

const HUD_COLOR = '#00E5FF'; // Cyan sesuai desain Anda
const DANGER_COLOR = '#FF1744';

export const renderHUD = (ctx, width, height, telemetry) => {
  const { pitch, roll, heading } = telemetry;
  
  // Bersihkan frame sebelumnya (wajib di setiap frame baru)
  ctx.clearRect(0, 0, width, height);

  const cx = width / 2;
  const cy = height / 2;

  // --- 1. MENGGAMBAR PITCH & ROLL LADDER ---
  ctx.save(); // Simpan state canvas normal
  
  // Geser titik pusat rotasi ke tengah layar
  ctx.translate(cx, cy);
  
  // Terapkan efek ROLL (rotasi) - konversi derajat ke radian
  ctx.rotate((roll * Math.PI) / 180);
  
  // Terapkan efek PITCH (translasi vertikal)
  // Misal: 1 derajat pitch = 4 pixel pergeseran di layar
  const pitchScale = 4; 
  ctx.translate(0, pitch * pitchScale);

  // Gambar Garis Horizon Utama
  ctx.strokeStyle = HUD_COLOR;
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(-150, 0);
  ctx.lineTo(-50, 0);
  ctx.moveTo(50, 0);
  ctx.lineTo(150, 0);
  ctx.stroke();

  // Gambar Garis Pitch (Setiap 10 derajat)
  ctx.lineWidth = 1;
  ctx.textAlign = 'right';
  ctx.textBaseline = 'middle';
  ctx.font = '12px "Courier New", Courier, monospace';
  ctx.fillStyle = HUD_COLOR;

  for (let i = -60; i <= 60; i += 10) {
    if (i === 0) continue; // Lewati horizon yang sudah digambar
    
    const y = -i * pitchScale; // Y naik/turun sesuai skala pitch
    const isDive = i < 0;      // Menukik (garis putus-putus)
    const lineLen = isDive ? 40 : 60;

    ctx.beginPath();
    if (isDive) ctx.setLineDash([5, 5]); // Garis putus-putus untuk dive
    else ctx.setLineDash([]);
    
    // Garis Kiri
    ctx.moveTo(-80, y);
    ctx.lineTo(-80 + lineLen, y);
    // Garis Kanan
    ctx.moveTo(80, y);
    ctx.lineTo(80 - lineLen, y);
    ctx.stroke();

    // Angka Derajat
    ctx.fillText(Math.abs(i), -85, y);
    ctx.textAlign = 'left';
    ctx.fillText(Math.abs(i), 85, y);
    ctx.textAlign = 'right';
  }

  ctx.restore(); // Kembalikan state canvas ke normal (hapus efek rotasi untuk menggambar UI statis)


  // --- 2. MENGGAMBAR HEADING TAPE (PITA KOMPAS DI ATAS) ---
  ctx.save();
  ctx.fillStyle = 'rgba(0, 0, 0, 0.4)';
  ctx.fillRect(cx - 150, 10, 300, 30); // Background pita kompas
  
  ctx.strokeStyle = HUD_COLOR;
  ctx.fillStyle = HUD_COLOR;
  ctx.lineWidth = 2;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'top';
  ctx.font = '14px "Courier New"';

  // Gambar segitiga penunjuk tengah
  ctx.beginPath();
  ctx.moveTo(cx, 40);
  ctx.lineTo(cx - 5, 45);
  ctx.lineTo(cx + 5, 45);
  ctx.fill();

  // Logika geser kompas (disederhanakan)
  ctx.beginPath();
  ctx.rect(cx - 150, 10, 300, 30);
  ctx.clip(); // Potong agar angka kompas tidak keluar dari background hitam

  const headingSpacing = 10; // Piksel per derajat kompas
  for (let i = -30; i <= 30; i++) {
    const currentHeading = Math.floor(heading) + i;
    // Normalisasi 0-359
    let displayHeading = currentHeading % 360;
    if (displayHeading < 0) displayHeading += 360;

    const x = cx + (i * headingSpacing) - ((heading % 1) * headingSpacing);

    if (displayHeading % 10 === 0) {
      ctx.beginPath();
      ctx.moveTo(x, 10);
      ctx.lineTo(x, 20);
      ctx.stroke();
      ctx.fillText(displayHeading.toString().padStart(3, '0'), x, 22);
    }
  }
  ctx.restore();


  // --- 3. MENGGAMBAR FLIGHT PATH VECTOR (CROSSHAIR STATIS) ---
  ctx.strokeStyle = DANGER_COLOR;
  ctx.lineWidth = 2;
  ctx.setLineDash([]);
  ctx.beginPath();
  // Bulatan tengah
  ctx.arc(cx, cy, 8, 0, Math.PI * 2);
  // Garis sayap
  ctx.moveTo(cx - 20, cy);
  ctx.lineTo(cx - 8, cy);
  ctx.moveTo(cx + 8, cy);
  ctx.lineTo(cx + 20, cy);
  // Garis ekor atas
  ctx.moveTo(cx, cy - 20);
  ctx.lineTo(cx, cy - 8);
  ctx.stroke();
};