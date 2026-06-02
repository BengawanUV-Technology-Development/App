// src/components/layout/MainLayout.jsx
import { useCallback, useEffect, useState } from 'react';
import useDroneStateStore from '../../store/droneStateStore';
import BottomBar from '../bottombar/BottomBar';
import CenterArea from '../centerarea/CenterArea';
import LeftSidebar from '../leftsidebar/LeftSidebar';
import RightSidebar from '../rightsidebar/RightSidebar';
import TopBar from '../topbar/TopBar';
import styles from './MainLayout.module.css';

const MainLayout = () => {
  const [bottomHeight, setBottomHeight] = useState(180); // Tinggi default diperkecil
  const [isDragging, setIsDragging] = useState(false);
  const connectionPhase = useDroneStateStore((state) => state.connectionPhase);
  const isConnected = useDroneStateStore((state) => state.isConnected);

  const handleMouseDown = useCallback((e) => {
    e.preventDefault();
    setIsDragging(true);
  }, []);

  useEffect(() => {
    const handleMouseMove = (e) => {
      if (!isDragging) return;
      // Kalkulasi tinggi baru dari posisi Y mouse terhadap tinggi layar
      const newHeight = window.innerHeight - e.clientY;

      // Batasi min 100px, max 60% dari layar
      if (newHeight >= 100 && newHeight <= window.innerHeight * 0.6) {
        setBottomHeight(newHeight);
      }
    };

    const handleMouseUp = () => setIsDragging(false);

    if (isDragging) {
      document.addEventListener('mousemove', handleMouseMove);
      document.addEventListener('mouseup', handleMouseUp);
      document.body.style.cursor = 'row-resize'; // Kunci kursor saat drag
    } else {
      document.body.style.cursor = 'default';
    }

    return () => {
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
    };
  }, [isDragging]);

  return (
    <div
      className={styles.gcsContainer}
      // Inject tinggi dinamis langsung ke Grid Rows
      style={{ gridTemplateRows: `40px 1fr 4px ${bottomHeight}px`, position: 'relative' }}
    >
      {connectionPhase !== 'DISCONNECTED' && !isConnected && (
        <div className="absolute inset-0 z-[100] flex items-center justify-center bg-black/80 backdrop-blur-sm">
          <div className="min-w-[320px] rounded-sm border-2 border-emerald-500/50 bg-slate-900 p-8 shadow-[0_0_50px_rgba(16,185,129,0.2)] flex flex-col items-center gap-6">
            <div className="relative">
              <div className="w-16 h-16 border-4 border-emerald-500/20 border-t-emerald-500 rounded-full animate-spin" />
              <div className="absolute inset-0 flex items-center justify-center">
                <div className="h-8 w-8 rounded-full bg-emerald-500/10 animate-pulse" />
              </div>
            </div>

            <div className="flex flex-col items-center gap-2 text-center">
              <h2 className="text-sm font-bold uppercase tracking-widest text-emerald-400">Mission Planner Link</h2>
              <p className="font-mono text-xs text-white animate-pulse">
                {connectionPhase === 'CONNECTING' ? '> Connecting to Vehicle...' : '> Getting Parameters / Syncing Telemetry...'}
              </p>
              <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-slate-800">
                <div
                  className="h-full bg-emerald-500 transition-all duration-1000"
                  style={{ width: connectionPhase === 'CONNECTING' ? '30%' : '75%' }}
                />
              </div>
            </div>
          </div>
        </div>
      )}

      <header className={styles.topBar}>
        <TopBar />
      </header>

      <aside className={styles.leftSidebar}>
        <LeftSidebar />
      </aside>

      <main className={styles.centerArea}>
        <CenterArea />
      </main>

      <aside className={styles.rightSidebar}>
        <RightSidebar />
      </aside>

      {/* Tuas Penarik */}
      <div
        className={`${styles.resizer} ${isDragging ? styles.dragging : ''}`}
        onMouseDown={handleMouseDown}
      />

      <footer className={styles.bottomBar}>
        <BottomBar />
      </footer>
    </div>
  );
};

export default MainLayout;