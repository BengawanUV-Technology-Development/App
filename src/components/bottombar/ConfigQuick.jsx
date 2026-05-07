// src/components/bottombar/ConfigQuick.jsx
import React from 'react';
import styles from './BottomBar.module.css';
import { calibrateGyro } from '../../services/api'; // 1. Import fungsi API

const ConfigQuick = () => {

  // 2. Buat fungsi handler untuk kalibrasi
  const handleCalibrate = async () => {
    // Safety check: Konfirmasi sebelum kalibrasi
    if (window.confirm('Pastikan drone dalam posisi statis dan datar (level). Mulai kalibrasi Gyro?')) {
      try {
        const res = await calibrateGyro();
        
        if (res.success) {
          // Jika backend membalas OK
          alert('Perintah kalibrasi berhasil dikirim ke Flight Controller.');
        } else {
          // Jika gagal
          alert(`Gagal mengirim kalibrasi: ${res.error}`);
        }
      } catch (error) {
        console.error('Error saat memanggil API:', error);
      }
    }
  };

  return (
    <div className={styles.configContainer}>
      <div className={styles.header}>Quick Config</div>
      
      <div className={styles.configList}>
        
        {/* Input Parameter (Bisa dihubungkan ke fungsi setParameter nanti) */}
        <div className={styles.configItem}>
          <span className={styles.configLabel}>RTL Alt</span>
          <div className={styles.configInputGroup}>
            <input type="text" className={`${styles.configInput} telemetry-font`} defaultValue="100" />
            <span className={styles.configUnit}>m</span>
          </div>
        </div>

        <div className={styles.configItem}>
          <span className={styles.configLabel}>WP Speed</span>
          <div className={styles.configInputGroup}>
            <input type="text" className={`${styles.configInput} telemetry-font`} defaultValue="15.0" />
            <span className={styles.configUnit}>m/s</span>
          </div>
        </div>

        {/* 3. Pasang fungsi handler ke onClick tombol */}
        <button 
          className={styles.actionBtn}
          onClick={handleCalibrate}
        >
          CALIBRATE GYRO
        </button>
        
      </div>
    </div>
  );
};

export default ConfigQuick;