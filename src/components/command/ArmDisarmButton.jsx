import { useState } from "react";
import ConfirmDialog from "../common/ConfirmDialog";

function ArmDisarmButton({ isArmed, isConnected, onArm, onDisarm }) {
  const [confirmOpen, setConfirmOpen] = useState(false);

  const handleClick = () => {
    if (isArmed) {
      setConfirmOpen(true);
      return;
    }
    onArm();
  };

  return (
    <>
      <button
        type="button"
        className={isArmed ? "button-danger armed-pulse" : "button-primary"}
        onClick={handleClick}
        disabled={!isConnected}
      >
        {isArmed ? "DISARM" : "ARM"}
      </button>
      <ConfirmDialog
        open={confirmOpen}
        title="Disarm vehicle?"
        message="This sends a disarm command to the flight controller."
        confirmLabel="Disarm"
        onCancel={() => setConfirmOpen(false)}
        onConfirm={() => {
          setConfirmOpen(false);
          onDisarm();
        }}
      />
    </>
  );
}

export default ArmDisarmButton;
