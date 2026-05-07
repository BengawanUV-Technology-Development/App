// src/components/leftsidebar/LeftSidebar.jsx
import React from 'react';
import ArmDisarm from './ArmDisarm';
import FlightModes from './FlightModes';
import styles from './LeftSidebar.module.css';
import { rebootFCU } from '../../services/api';


// Import Store
import useDroneStateStore from '../../store/droneStateStore';

const LeftSidebar = () => {
  // Mengambil state dan fungsi dari Zustand
  const isArmed = useDroneStateStore((state) => state.isArmed);
  const setArmed = useDroneStateStore((state) => state.setArmed);
  
  const activeMode = useDroneStateStore((state) => state.activeMode);
  const setFlightMode = useDroneStateStore((state) => state.setFlightMode);

  return (
    <div className={styles.container}>
      {/* Oper state dari Zustand ke komponen Child */}
      <ArmDisarm isArmed={isArmed} setIsArmed={setArmed} />
      <FlightModes activeMode={activeMode} setActiveMode={setFlightMode} />

      <div className={styles.section}>
        <div className={styles.sectionTitle}>System</div>
        <button 
          className={styles.sysButton}
          onClick={async () => {
            if (window.confirm('PERINGATAN: Anda yakin ingin mereboot Flight Controller?')) {
              await rebootFCU();
            }
          }}
        >
          Reboot FCU
        </button>
      </div>
    </div>
  );
};

export default LeftSidebar;
