// src/components/topbar/TopBar.jsx
import React from 'react';
import ConnectionPanel from './ConnectionPanel';
import SystemClock from './SystemClock';
import styles from './TopBar.module.css';

const TopBar = () => {
  return (
    <div className={styles.container}>
      <ConnectionPanel />
      <SystemClock />
    </div>
  );
};

export default TopBar;