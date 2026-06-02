// src/components/centerarea/HUDOverlay.jsx
import { useEffect, useRef } from 'react';
import useDroneStateStore from '../../store/droneStateStore';
import useTelemetryStore from '../../store/telemetryStore';
import { renderHUD } from '../../utils/hudRenderer';
import styles from './CenterArea.module.css';

const HUDOverlay = () => {
  const canvasRef = useRef(null);
  const pitch = useTelemetryStore((state) => state.pitch) ?? 0;
  const roll = useTelemetryStore((state) => state.roll) ?? 0;
  const heading = useTelemetryStore((state) => state.heading) ?? 0;
  const altitude = useTelemetryStore((state) => state.altitude) ?? 0;
  const battery = useTelemetryStore((state) => state.battery) ?? 0;
  const statusText = useTelemetryStore((state) => state.statusText) ?? '';
  const prearmMessage = useTelemetryStore((state) => state.prearmMessage) ?? '';
  const isConnected = useDroneStateStore((state) => state.isConnected);
  const isArmed = useDroneStateStore((state) => state.isArmed);

  const getHudMessage = () => {
    if (statusText) return statusText;
    if (prearmMessage) return prearmMessage;
    if (!isConnected) return 'PreArm: Vehicle not connected';
    if (!isArmed) return 'PreArm: Safety switch / GPS lock / EKF check required';
    if (battery > 0 && battery < 20) return 'PreArm: Battery below threshold';
    if (altitude > 0) return 'Status: Ready';
    return 'PreArm: Ready for arming checks';
  };

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    // Fungsi untuk menggambar ulang
    const draw = () => {
      const parent = canvas.parentElement;
      // Sinkronkan resolusi internal canvas dengan ukuran tampilannya di layar
      canvas.width = parent.clientWidth;
      canvas.height = parent.clientHeight;

      const ctx = canvas.getContext('2d');
      renderHUD(ctx, canvas.width, canvas.height, { pitch, roll, heading });
    };

    // Gunakan ResizeObserver agar HUD tidak melar saat layout berubah
    const resizeObserver = new ResizeObserver(() => draw());
    resizeObserver.observe(canvas.parentElement);

    // Render awal
    draw();

    return () => resizeObserver.disconnect();
  }, [pitch, roll, heading]);

  return (
    <>
      <canvas ref={canvasRef} className={styles.hudLayer} />
      <div className={styles.hudStatusBanner}>
        <span className={styles.hudStatusLabel}>PRE-ARM</span>
        <span className={styles.hudStatusText}>{getHudMessage()}</span>
      </div>
    </>
  );
};

export default HUDOverlay;