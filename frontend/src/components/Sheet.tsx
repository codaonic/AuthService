import { ReactNode, useEffect, useRef } from "react";
import { CloseIcon } from "./Icons";
import { useFocusTrap } from "./useFocusTrap";

/** A full-height panel from the right, for looking at and changing one thing
 * (a person, an application) without leaving the list. */
export function Sheet({
  label,
  title,
  subtitle,
  badge,
  summary,
  narrow,
  onClose,
  children,
}: {
  /** Read by screen readers, e.g. "Manage ana@example.com". */
  label: string;
  title: ReactNode;
  subtitle?: ReactNode;
  badge?: ReactNode;
  summary?: ReactNode;
  narrow?: boolean;
  onClose: () => void;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useFocusTrap(ref);

  // Escape closes the panel, but not while a dialog on top of it has focus.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && ref.current?.contains(document.activeElement)) onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div
      className="sheet-backdrop"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className={`sheet${narrow ? " sheet--narrow" : ""}`} role="dialog" aria-modal="true" aria-label={label} ref={ref}>
        <header className="sheet__header">
          <div className="sheet__title-row">
            <div style={{ minWidth: 0 }}>
              <h2 className="sheet__title">{title}</h2>
              {subtitle}
            </div>
            {badge}
            <button type="button" className="modal__close" aria-label="Close" onClick={onClose}>
              <CloseIcon width={18} height={18} />
            </button>
          </div>
          {summary}
        </header>
        <div className="sheet__body sheet__body--solo">{children}</div>
      </div>
    </div>
  );
}
