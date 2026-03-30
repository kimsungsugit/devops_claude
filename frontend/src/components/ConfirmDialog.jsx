import { useEffect, useRef } from "react";

export default function ConfirmDialog({ title, message, confirmLabel, danger, onConfirm, onCancel }) {
  const confirmRef = useRef(null);

  useEffect(() => {
    const handler = (e) => {
      if (e.key === "Escape") onCancel();
      if (e.key === "Enter") onConfirm();
    };
    window.addEventListener("keydown", handler);
    confirmRef.current?.focus();
    return () => window.removeEventListener("keydown", handler);
  }, [onConfirm, onCancel]);

  return (
    <div className="confirm-overlay" onClick={onCancel}>
      <div className="confirm-dialog" onClick={(e) => e.stopPropagation()} role="alertdialog" aria-modal="true" aria-labelledby="confirm-title">
        <h3 id="confirm-title">{title || "확인"}</h3>
        <p>{message}</p>
        <div className="confirm-actions">
          <button onClick={onCancel}>취소</button>
          <button
            ref={confirmRef}
            className={danger ? "confirm-danger" : ""}
            onClick={onConfirm}
          >
            {confirmLabel || "확인"}
          </button>
        </div>
      </div>
    </div>
  );
}
