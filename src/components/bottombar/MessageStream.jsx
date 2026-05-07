// src/components/bottombar/MessageStream.jsx
import React, { useRef, useEffect } from 'react';
import styles from './BottomBar.module.css';

const MessageStream = () => {
  // Referensi untuk auto-scroll ke bawah saat ada pesan baru
  const logEndRef = useRef(null);

  // Simulasi log MAVLink
  const logs = [
    { time: '10:45:12', type: 'info', text: 'MAVLink connection established on udp://:14550' },
    { time: '10:45:15', type: 'info', text: 'Downloading parameters (1/542)...' },
    { time: '10:45:20', type: 'success', text: 'Parameters downloaded successfully.' },
    { time: '10:46:01', type: 'warning', text: 'PreArm: 3D GPS lock required' },
    { time: '10:48:30', type: 'success', text: 'GPS Glonass Active. HDOP: 0.8' },
    { time: '10:50:00', type: 'error', text: 'PreArm: Gyros not calibrated' },
  ];

  // Auto-scroll ke pesan terbaru
  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [logs]);

  return (
    <div className={styles.streamContainer}>
      <div className={styles.header}>MAVLink Message Stream</div>
      <div className={styles.logArea}>
        {logs.map((log, index) => (
          <div key={index} className={`${styles.logLine} ${styles[log.type]} telemetry-font`}>
            <span className={styles.timestamp}>[{log.time}]</span>
            <span>{log.text}</span>
          </div>
        ))}
        {/* Elemen kosong untuk target auto-scroll */}
        <div ref={logEndRef} />
      </div>
    </div>
  );
};

export default MessageStream;