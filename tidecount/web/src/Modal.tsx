import { ReactNode, useEffect, useRef } from "react";

/** A dialog over the page. Escape and a click on the backdrop close it, unless `locked` while work is in flight. */
export function Modal({ title, onClose, children, wide, locked }: { title: string; onClose: () => void; children: ReactNode; wide?: boolean; locked?: boolean }) {
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape" && !locked) onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, locked]);
  // Focus lands in the dialog, so the keyboard starts there and screen readers announce it.
  useEffect(() => {
    if (!box.current?.contains(document.activeElement)) box.current?.focus();
  }, []);
  return (
    <div className="help-back" onMouseDown={(e) => { if (e.target === e.currentTarget && !locked) onClose(); }}>
      <div ref={box} tabIndex={-1} className={`help edit-dialog ${wide ? "wide" : ""}`} role="dialog" aria-modal="true" aria-label={title}>
        <div className="dialog-head">
          <h2>{title}</h2>
          <button className="dialog-x" aria-label="Close" disabled={locked} onClick={onClose}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" aria-hidden><path d="M6 6l12 12M18 6L6 18" /></svg>
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}
