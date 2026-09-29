import { useEffect, useRef, useState } from "react";
import { useFocusTrap } from "./useFocusTrap";

export interface ConfirmRequest {
  title: string;
  description: string;
  confirmLabel?: string;
  danger?: boolean;
  onConfirm: () => void | Promise<void>;
}

/** Renders nothing until `open()` is called -- mount one per page and call
 * the returned `confirm(...)` from a destructive action's onClick instead of
 * running it directly. */
export function useConfirmDialog() {
  const [request, setRequest] = useState<ConfirmRequest | null>(null);
  const [busy, setBusy] = useState(false);

  const confirm = (request: ConfirmRequest) => setRequest(request);

  const dialog = request && (
    <ConfirmDialogView
      request={request}
      busy={busy}
      onCancel={() => setRequest(null)}
      onConfirm={async () => {
        setBusy(true);
        try {
          await request.onConfirm();
        } finally {
          setBusy(false);
          setRequest(null);
        }
      }}
    />
  );

  return { confirm, dialog };
}

function ConfirmDialogView({
  request,
  busy,
  onCancel,
  onConfirm,
}: {
  request: ConfirmRequest;
  busy: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useFocusTrap(ref);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onCancel();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onCancel]);

  return (
    <div
      className="modal-backdrop"
      onClick={(e) => {
        if (e.target === e.currentTarget) onCancel();
      }}
    >
      <div className="modal" role="alertdialog" aria-modal="true" aria-label={request.title} ref={ref}>
        <div className="modal__header">
          <h2>{request.title}</h2>
        </div>
        <div className="modal__body">
          <p style={{ fontSize: 14, color: "var(--text-muted)", margin: "0 0 20px" }}>{request.description}</p>
          <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
            <button type="button" className="btn btn--secondary" onClick={onCancel} disabled={busy}>
              Cancel
            </button>
            <button
              type="button"
              className={`btn ${request.danger ? "btn--danger" : "btn--primary"}`}
              onClick={onConfirm}
              disabled={busy}
              autoFocus
            >
              {request.confirmLabel ?? "Confirm"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
