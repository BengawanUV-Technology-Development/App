// src/components/rightsidebar/TelemetryGrid.jsx
import React from 'react';
import useTelemetryStore from '../../store/telemetryStore';
import TelemetryItem from './TelemetryItem';
import styles from './RightSidebar.module.css';

const TelemetryGrid = () => {
  // Cara yang lebih aman dan langsung untuk memanggil state Zustand
  const telemetry = useTelemetryStore();

  // Ekstrak data dengan Fallback '?? 0' untuk mencegah error .toFixed()
  // Jika telemetry.altitude undefined, maka altitude = 0
  const altitude = telemetry.altitude ?? 0;
  const speed = telemetry.speed ?? 0;
  const battery = telemetry.battery ?? 100; // Default baterai 100%
  const distToHome = telemetry.distToHome ?? 0;
  const vSpeed = telemetry.vSpeed ?? 0;
  const wind = telemetry.wind ?? 0;

  // Helper untuk menentukan status peringatan
  const getBatteryStatus = (batValue) => {
    if (batValue <= 20) return 'critical';
    if (batValue <= 40) return 'warning';
    return 'normal';
  };

  // Format array untuk di-render oleh komponen Child
  const theBig6 = [
    { label: 'Altitude', value: altitude.toFixed(1), unit: 'm', status: 'normal' },
    { label: 'Speed (GS)', value: speed.toFixed(1), unit: 'm/s', status: 'normal' },
    { label: 'Battery', value: battery.toFixed(1), unit: '%', status: getBatteryStatus(battery) },
    { label: 'Dist to Home', value: distToHome.toFixed(0), unit: 'm', status: 'normal' },
    { label: 'V-Speed', value: (vSpeed > 0 ? '+' : '') + vSpeed.toFixed(1), unit: 'm/s', status: 'normal' },
    { label: 'Wind', value: wind.toFixed(1), unit: 'm/s', status: 'normal' },
  ];

  return (
    <div className={styles.grid}>
      {theBig6.map((item, index) => (
        <TelemetryItem 
          key={index}
          label={item.label}
          value={item.value}
          unit={item.unit}
          status={item.status}
        />
      ))}
    </div>
  );
};

export default TelemetryGrid;