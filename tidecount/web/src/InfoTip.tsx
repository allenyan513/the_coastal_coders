import { ReactNode, useId, useState } from "react";
import { createPortal } from "react-dom";

const WIDTH = 230;

/**
 * A small "?" that shows an explanation in the app's dark tooltip (the same .tip bubble the
 * Species wiki uses). It opens on hover, on keyboard focus and on a tap, so it works on touch
 * screens too. The bubble is placed in fixed position on the page, so a scrolling panel can't clip it.
 */
export function InfoTip({ label, children }: { label: string; children: ReactNode }) {
  const [pos, setPos] = useState<{ left: number; top: number; arrow: number; below: boolean } | null>(null);
  const id = useId();

  const place = (el: HTMLElement) => {
    const r = el.getBoundingClientRect();
    const left = Math.max(8, Math.min(r.left + r.width / 2 - WIDTH / 2, window.innerWidth - WIDTH - 8));
    // Open above; below when there isn't room.
    const above = r.top > 140;
    setPos({ left, top: above ? r.top - 8 : r.bottom + 8, below: !above, arrow: Math.max(10, Math.min(r.left - left + r.width / 2 - 6, WIDTH - 22)) });
  };

  return (
    <>
      <button
        type="button"
        className="info-tip"
        aria-label={label}
        aria-describedby={pos ? id : undefined}
        onMouseEnter={(e) => place(e.currentTarget)}
        onMouseLeave={() => setPos(null)}
        onFocus={(e) => place(e.currentTarget)}
        onBlur={() => setPos(null)}
        onClick={(e) => (pos ? setPos(null) : place(e.currentTarget))}
      >
        ?
      </button>
      {pos && createPortal(
        <span id={id} role="tooltip" className={`tip show${pos.below ? " below" : ""}`}
          style={{ left: pos.left, top: pos.top, ["--arrow" as string]: `${pos.arrow}px` }}>
          {children}
        </span>,
        document.body,
      )}
    </>
  );
}
