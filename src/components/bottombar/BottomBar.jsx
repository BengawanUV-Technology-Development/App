// src/components/bottombar/BottomBar.jsx
import React from 'react';
import MessageStream from './MessageStream';
import ConfigQuick from './ConfigQuick';
import styles from './BottomBar.module.css';

const BottomBar = () => {
  return (
    <div className={styles.container}>
      <MessageStream />
      <ConfigQuick />
    </div>
  );
};

export default BottomBar;