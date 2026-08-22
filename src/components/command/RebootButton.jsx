import { useState } from "react";
import ConfirmDialog from "../common/ConfirmDialog";

/**
 * RebootButton
 *
 * Tombol reboot flight controller.
 * Saat `readOnly={true}`, tombol sepenuhnya dinonaktifkan — tidak ada API
 * call yang dikirim.
 */
function RebootButton({ isConnected, isArmed, onReboot, readOnly = false }) {
  const [confirmOpen, setConfirmOpen] = useState(false);

  const isDisabled = readOnly || !isConnected || isArmed;

  return (
    <>
      <button
        type="button"
        className="button-ghost"
        disabled={isDisabled}
        onClick={() => !readOnly && setConfirmOpen(true)}
        title={readOnly ? "Command dinonaktifkan – mode read-only (UDP mirror)" : undefined}
        aria-disabled={isDisabled}
      >
        REBOOT FC
      </button>
      <ConfirmDialog
        open={confirmOpen && !readOnly}
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
