
// src/components/leftsidebar/FlightModes.jsx
import React from 'react';
import styles from './LeftSidebar.module.css';
import { setMode } from '../../services/api'; // Import fungsi API

const FlightModes = ({ activeMode, setActiveMode }) => {
  const modes = ['FBWA', 'AUTO', 'Q_STABILIZE', 'Q_HOVER', 'Q_LAND', 'MANUAL'];

  const handleModeChange = async (mode) => {
    // Kirim request ke backend Flask
    const res = await setMode(mode);
    
    // Jika backend merespon sukses, barulah state UI diperbarui
    if (res.success) {
      setActiveMode(mode);
    } else {
      console.error("Gagal mengubah mode:", res.error);
      // Opsional: Tampilkan notifikasi error ke operator
    }
  };

  return (
    <div className={styles.section}>
      <div className={styles.sectionTitle}>Flight Modes</div>
      <div className={styles.modeGrid}>
        {modes.map((mode) => (
          <button
            key={mode}
            className={`${styles.modeButton} ${activeMode === mode ? styles.active : ''}`}
            onClick={() => handleModeChange(mode)} // Panggil fungsi handler
          >
            {mode}
          </button>
        ))}
      </div>
    </div>
  );
};

export default FlightModes;