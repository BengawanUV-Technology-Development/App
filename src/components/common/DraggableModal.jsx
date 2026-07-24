import React, { useState, useRef, useEffect } from 'react';
import './DraggableModal.css';

function DraggableModal({ title, onClose, children, initialPosition = { x: 100, y: 100 } }) {
  const [position, setPosition] = useState(initialPosition);
  const [isDragging, setIsDragging] = useState(false);
  const [dragOffset, setDragOffset] = useState({ x: 0, y: 0 });
  const modalRef = useRef(null);

  const handleMouseDown = (e) => {
    setIsDragging(true);
    setDragOffset({
      x: e.clientX - position.x,
      y: e.clientY - position.y
    });
  };

  const handleMouseMove = (e) => {
    if (isDragging) {
      setPosition({
        x: e.clientX - dragOffset.x,
        y: e.clientY - dragOffset.y
      });
    }
  };

  const handleMouseUp = () => {
    setIsDragging(false);
  };

  useEffect(() => {
    if (isDragging) {
      document.addEventListener('mousemove', handleMouseMove);
      document.addEventListener('mouseup', handleMouseUp);
    } else {
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
    }
    return () => {
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
    };
  }, [isDragging, dragOffset]);

  return (
    <div 
      className="draggable-modal" 
      ref={modalRef}
      style={{ left: position.x, top: position.y }}
    >
      <div className="draggable-modal-header" onMouseDown={handleMouseDown}>
        <span className="draggable-modal-title">{title}</span>
        <button type="button" className="draggable-modal-close" onClick={onClose}>×</button>
      </div>
      <div className="draggable-modal-content">
        {children}
      </div>
    </div>
  );
}

export default DraggableModal;
