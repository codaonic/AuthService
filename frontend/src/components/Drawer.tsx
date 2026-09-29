import { ReactNode, useEffect, useRef } from "react";
import { CloseIcon } from "./Icons";
import { useFocusTrap } from "./useFocusTrap";

export function Drawer({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  useFocusTrap(ref);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div
      className="drawer-backdrop"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="drawer" role="dialog" aria-modal="true" aria-label={title} ref={ref}>
        <div className="drawer__header">
          <h2>{title}</h2>
          <button type="button" className="modal__close" aria-label="Close" onClick={onClose}>
            <CloseIcon width={18} height={18} />
          </button>
        </div>
        <div className="drawer__body">{children}</div>
      </div>
    </div>
  );
}
