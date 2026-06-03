function Toast({ message, tone = "success", onClose }) {
  if (!message) return null;

  return (
    <div className={`toast ${tone}`} role="status">
      <span>{message}</span>
      {onClose ? (
        <button type="button" className="button-ghost toast-close" onClick={onClose} aria-label="Close notification">
          ×
        </button>
      ) : null}
    </div>
  );
}

export default Toast;
