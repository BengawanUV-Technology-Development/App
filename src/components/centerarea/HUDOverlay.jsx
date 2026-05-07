// src/components/centerarea/HUDOverlay.jsx
import React, { useRef, useEffect } from 'react';
import useTelemetryStore from '../../store/telemetryStore';
import { renderHUD } from '../../utils/hudRenderer';
import styles from './CenterArea.module.css';

const HUDOverlay = () => {
  const canvasRef = useRef(null);
  const pitch = useTelemetryStore((state) => state.pitch) ?? 0;
  const roll = useTelemetryStore((state) => state.roll) ?? 0;
  const heading = useTelemetryStore((state) => state.heading) ?? 0;

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

  return <canvas ref={canvasRef} className={styles.hudLayer} />;
};

export default HUDOverlay;