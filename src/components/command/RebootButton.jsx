import { useState } from "react";
import ConfirmDialog from "../common/ConfirmDialog";

function RebootButton({ isConnected, isArmed, onReboot }) {
  const [confirmOpen, setConfirmOpen] = useState(false);

  return (
    <>
      <button
        type="button"
        className="button-ghost"
        disabled={!isConnected || isArmed}
        onClick={() => setConfirmOpen(true)}
      >
        REBOOT FC
      </button>
      <ConfirmDialog
        open={confirmOpen}
        title="Reboot flight controller?"
        message="Telemetry will disconnect temporarily. Reboot is only allowed while the vehicle is disarmed."
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

export default RebootButton;
