import { useEffect, useRef } from "react";

const ICONS = {
  success: "✓",
  error: "✕",
  warning: "⚠",
  info: "ℹ",
};

export default function ToastContainer({ toasts, removeToast }) {
  return (
    <div className="toast-container" aria-live="polite">
      {toasts.map((t) => (
        <ToastItem key={t.id} toast={t} onClose={() => removeToast(t.id)} />
      ))}
    </div>
  );
}

function ToastItem({ toast, onClose }) {
  const timerRef = useRef(null);

  useEffect(() => {
    timerRef.current = setTimeout(onClose, toast.duration || 3500);
    return () => clearTimeout(timerRef.current);
  }, [onClose, toast.duration]);

  return (
    <div className={`toast-item toast-${toast.type || "info"}`} role="alert">
      <span className="toast-icon">{ICONS[toast.type] || ICONS.info}</span>
      <span className="toast-text">{toast.message}</span>
      <button className="toast-close" onClick={onClose} aria-label="닫기">×</button>
    </div>
  );
}
