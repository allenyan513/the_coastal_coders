import { useEffect, useState } from "react";

export type LensDot = { x: number; y: number; className: string; color?: string };

/** A round magnifying glass that follows the pointer over a frame. It sits inside the frame,
 * lets every click through, and shows the same picture and dots, only bigger. */
export function Magnifier({ src, dots, zoom = 3, size = 220 }: { src: string; dots: LensDot[]; zoom?: number; size?: number }) {
  const [at, setAt] = useState<{ x: number; y: number; w: number; h: number } | null>(null);
  const [host, setHost] = useState<HTMLElement | null>(null);

  useEffect(() => {
    const stage = host?.parentElement;
    if (!stage) return;
    const move = (e: PointerEvent) => {
      const box = stage.getBoundingClientRect();
      setAt({ x: e.clientX - box.left, y: e.clientY - box.top, w: box.width, h: box.height });
    };
    const leave = () => setAt(null);
    stage.addEventListener("pointermove", move);
    stage.addEventListener("pointerleave", leave);
    return () => {
      stage.removeEventListener("pointermove", move);
      stage.removeEventListener("pointerleave", leave);
    };
  }, [host]);

  const r = size / 2;
  return (
    <div ref={setHost} className="zoom-host" aria-hidden>
      {at && (
        <div className="zoom-lens" style={{ width: size, height: size, left: at.x - r, top: at.y - r }}>
          <div
            className="zoom-inner"
            style={{ width: at.w * zoom, height: at.h * zoom, left: r - at.x * zoom, top: r - at.y * zoom }}
          >
            <img src={src} alt="" draggable={false} />
            {dots.map((d, i) => (
              <span key={i} className={d.className} style={{ left: `${d.x * 100}%`, top: `${d.y * 100}%`, background: d.color }} />
            ))}
          </div>
          <span className="zoom-badge num">{zoom}×</span>
        </div>
      )}
    </div>
  );
}
