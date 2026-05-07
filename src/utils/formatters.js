// src/utils/formatters.js

/**
 * Memformat koordinat GPS agar presisi hingga 6 desimal (standar akurasi ~11cm)
 */
export const formatGPS = (coordinate) => {
  if (typeof coordinate !== 'number') return '0.000000';
  return coordinate.toFixed(6);
};

/**
 * Mengonversi kecepatan dari meter per detik (m/s) ke kilometer per jam (km/h)
 */
export const msToKmh = (ms) => {
  return (ms * 3.6).toFixed(1);
};

/**
 * Memformat detik menjadi format MM:SS (untuk waktu penerbangan / Time in Air)
 */
export const formatFlightTime = (totalSeconds) => {
  const m = Math.floor(totalSeconds / 60).toString().padStart(2, '0');
  const s = (totalSeconds % 60).toString().padStart(2, '0');
  return `${m}:${s}`;
};