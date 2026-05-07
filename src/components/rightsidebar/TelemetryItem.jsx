// src/components/rightsidebar/TelemetryItem.jsx
import React from 'react';
import styles from './RightSidebar.module.css';

const TelemetryItem = ({ label, value, unit, status = 'normal' }) => {
  return (
    <div className={`${styles.item} ${styles[status]}`}>
      <div className={styles.label}>{label}</div>
      <div className={styles.valueContainer}>
        {/* Terapkan telemetry-font di sini agar angka monospace */}
        <span className={`telemetry-font ${styles.value}`}>
          {value}
        </span>
        <span className={styles.unit}>{unit}</span>
      </div>
    </div>
  );
};

export default TelemetryItem;