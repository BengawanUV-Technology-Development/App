
// src/components/leftsidebar/FlightModes.jsx
import { setMode } from '../../services/api'; // Import fungsi API
import useDroneStateStore from '../../store/droneStateStore';
import styles from './LeftSidebar.module.css';

const FlightModes = ({ activeMode, setActiveMode }) => {
  const isArmed = useDroneStateStore((state) => state.isArmed);
  const modes = ['FBWA', 'AUTO', 'Q_STABILIZE', 'Q_HOVER', 'Q_LAND', 'MANUAL'];

  const handleModeChange = async (mode) => {
    if (!isArmed) {
      window.alert('Arm vehicle terlebih dahulu sebelum mengganti flight mode.');
      return;
    }

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
            className={`${styles.modeButton} ${activeMode === mode ? styles.active : ''} ${!isArmed ? 'opacity-60 cursor-not-allowed' : ''}`}
            onClick={() => handleModeChange(mode)} // Panggil fungsi handler
            disabled={!isArmed}
          >
            {mode}
          </button>
        ))}
      </div>
    </div>
  );
};

export default FlightModes;