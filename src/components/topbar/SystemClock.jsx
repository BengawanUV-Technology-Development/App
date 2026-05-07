// src/components/topbar/SystemClock.jsx
import React, { useState, useEffect } from 'react';
import styles from './TopBar.module.css';

const SystemClock = () => {
  const [time, setTime] = useState(new Date());

  useEffect(() => {
    const timer = setInterval(() => {
      setTime(new Date());
    }, 1000); // Update setiap 1 detik

    return () => clearInterval(timer); // Bersihkan timer saat komponen unmount
  }, []);

  // Format jam (HH:MM:SS)
  const timeString = time.toLocaleTimeString('en-US', { hour12: false });
  // Format tanggal (YYYY-MM-DD)
  const dateString = time.toISOString().split('T')[0];

  return (
    <div className={styles.clockPanel}>
      <div className={`telemetry-font ${styles.clockTime}`}>
        {timeString} UTC+7
      </div>
      <div className={styles.clockDate}>
        {dateString}
      </div>
    </div>
  );
};

export default SystemClock;