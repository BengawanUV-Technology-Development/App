// src/components/layout/MainLayout.jsx
import React, { useState, useEffect, useCallback } from 'react';
import styles from './MainLayout.module.css';
import TopBar from '../topbar/TopBar';
import LeftSidebar from '../leftsidebar/LeftSidebar';
import CenterArea from '../centerarea/CenterArea';
import RightSidebar from '../rightsidebar/RightSidebar';
import BottomBar from '../bottombar/BottomBar';

const MainLayout = () => {
  const [bottomHeight, setBottomHeight] = useState(180); // Tinggi default diperkecil
  const [isDragging, setIsDragging] = useState(false);

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
      style={{ gridTemplateRows: `40px 1fr 4px ${bottomHeight}px` }}
    >
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