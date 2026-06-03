import { useState } from "react";
import ConfirmDialog from "../common/ConfirmDialog";

function QuickActions({ isConnected, isArmed, onReboot }) {
  const [confirmOpen, setConfirmOpen] = useState(false);

  return (
    <>
      <button
        type="button"
        className="button-danger"
        onClick={() => setConfirmOpen(true)}
        disabled={!isConnected || isArmed}
      >
        Reboot FC
      </button>
      <ConfirmDialog
        open={confirmOpen}
        title="Reboot flight controller?"
        message="This asks the flight controller to reboot and temporarily drops telemetry."
        confirmLabel="Reboot"
        onCancel={() => setConfirmOpen(false)}
        onConfirm={() => {
          setConfirmOpen(false);
          onReboot();
        }}
      />
    </>
  );
}

export default QuickActions;
