import { MouseEvent, ReactNode, useMemo } from "react";
import { Dot } from "./api";

type Props = {
  src: string;
  dots: Dot[];
  showDots: boolean;
  showGrid: boolean;
  aspect?: string;
  onAdd: (x: number, y: number) => void;
  onRemove: (dot: Dot) => void;
  onLoad?: () => void;
  onError?: () => void;
  children?: ReactNode;
};

/** A frozen frame. Click empty water to add a dot, click a dot to remove it. */
export function DotStage({ src, dots, showDots, showGrid, aspect, onAdd, onRemove, onLoad, onError, children }: Props) {
  const cells = useMemo(() => {
    const out = Array(15).fill(0);
    dots.forEach((d) => { out[Math.min(2, Math.floor(d.y * 3)) * 5 + Math.min(4, Math.floor(d.x * 5))] += 1; });
    return out;
  }, [dots]);

  const add = (e: MouseEvent<HTMLDivElement>) => {
    const box = e.currentTarget.getBoundingClientRect();
    onAdd((e.clientX - box.left) / box.width, (e.clientY - box.top) / box.height);
  };

  return (
    <div className="stage" style={{ cursor: "crosshair", aspectRatio: aspect }} onClick={add}>
      <img src={src} alt="Frozen video frame" draggable={false} onLoad={onLoad} onError={onError} />
      {showGrid && <div className="gridlines">{cells.map((n, i) => <div key={i}>{n > 0 && <span>{n}</span>}</div>)}</div>}
      {showDots && dots.map((d, i) => (
        <button
          key={i}
          className={`dot ${d.source}`}
          style={{ left: `${d.x * 100}%`, top: `${d.y * 100}%` }}
          aria-label={`Remove dot ${i + 1}`}
          onClick={(e) => { e.stopPropagation(); onRemove(d); }}
        />
      ))}
      {children}
    </div>
  );
}
