import React from 'react';
import styles from './LeftSidebar.module.css';
import { armDrone, disarmDrone } from '../../services/api';

const ArmDisarm = ({ isArmed, setIsArmed }) => {
  const handleArmToggle = async () => {
    if (isArmed) {
      const res = await disarmDrone();
      if (res.success) setIsArmed(false); // Update UI jika sukses
    } else {
      const res = await armDrone();
      if (res.success) setIsArmed(true);
    }
  };

  return (
    <div className={styles.section}>
      <div className={styles.sectionTitle}>Propulsion</div>
      <button 
        className={`${styles.armButton} ${isArmed ? styles.armed : ''}`}
        onClick={handleArmToggle}
      >
        {isArmed ? 'DISARM' : 'ARM'}
      </button>
    </div>
  );
};

export default ArmDisarm;