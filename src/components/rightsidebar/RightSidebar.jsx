// src/components/rightsidebar/RightSidebar.jsx
import React from 'react';
import TelemetryGrid from './TelemetryGrid';
import styles from './RightSidebar.module.css';

const RightSidebar = () => {
  return (
    <div className={styles.container}>
      <div className={styles.sectionTitle}>Persistent Telemetry</div>
      
      {/* Panggil Grid Telemetri */}
      <TelemetryGrid />

      {/* Ruang tambahan di bawah The Big 6 bisa dipakai untuk indikator GPS, dll nantinya */}
    </div>
  );
};

export default RightSidebar;