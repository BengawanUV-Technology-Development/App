import { useState } from "react";
import ConfirmDialog from "../common/ConfirmDialog";

/**
 * ArmDisarmButton
 *
 * Tombol ARM / DISARM kendaraan.
 * Saat `readOnly={true}`, tombol sepenuhnya dinonaktifkan dan menampilkan
 * tooltip penjelasan — tidak ada API call yang dikirim.
 */
function ArmDisarmButton({ isArmed, isConnected, onArm, onDisarm, readOnly = false }) {
  const [confirmOpen, setConfirmOpen] = useState(false);

  const isDisabled = readOnly || !isConnected;

  const handleClick = () => {
    if (readOnly) return;
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
        disabled={isDisabled}
        title={readOnly ? "Command dinonaktifkan – mode read-only (UDP mirror)" : undefined}
        aria-disabled={isDisabled}
      >
        {isArmed ? "DISARM" : "ARM"}
      </button>
      <ConfirmDialog
        open={confirmOpen && !readOnly}
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
