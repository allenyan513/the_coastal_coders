import { useState } from "react";
import { ZLine } from "./api";

const W = 800;
const H = 300;
const PAD = { top: 16, right: 110, bottom: 32, left: 44 };

// Two categorical colours, checked for colour-blind separation and contrast on white.
const COLORS = { fish: "#1f5eff", water: "#eb6834" };

/**
 * A fish line and a water line on one shared scale: how far each is from its own usual level,
 * in standard deviations. 0 is usual, above is higher than usual, below is lower. Units differ,
 * so the two lines are never drawn against two different axes.
 */
export function CompareChart({ fish, water }: { fish: ZLine; water: ZLine }) {
  const [hoverT, setHoverT] = useState<number | null>(null);
  const lines = [
    { key: "fish" as const, line: fish },
    { key: "water" as const, line: water },
  ].filter((l) => l.line.points.length > 0);
  if (lines.length === 0) return <p className="meta">Nothing to compare at this site.</p>;

  const all = lines.flatMap((l) => l.line.points);
  const times = all.map((p) => Date.parse(p.date));
  const t0 = Math.min(...times);
  const t1 = Math.max(...times);
  const top = Math.max(2, Math.ceil(Math.max(...all.map((p) => Math.abs(p.z)))));
  const ticks: number[] = [];
  for (let v = -top; v <= top; v += top > 3 ? 2 : 1) ticks.push(v);

  const x = (t: number) => PAD.left + (t1 === t0 ? 0.5 : (t - t0) / (t1 - t0)) * (W - PAD.left - PAD.right);
  const y = (z: number) => PAD.top + (1 - (z + top) / (2 * top)) * (H - PAD.top - PAD.bottom);
  const GAP_MS = 120 * 24 * 60 * 60 * 1000;
  const path = (pts: ZLine["points"]) =>
    pts.map((p, i) => {
      const t = Date.parse(p.date);
      const jump = i === 0 || t - Date.parse(pts[i - 1].date) > GAP_MS;
      return `${jump ? "M" : "L"}${x(t).toFixed(1)},${y(p.z).toFixed(1)}`;
    }).join(" ");

  const years: number[] = [];
  const firstYear = new Date(t0).getUTCFullYear();
  const lastYear = new Date(t1).getUTCFullYear();
  const every = Math.max(1, Math.ceil((lastYear - firstYear + 1) / 10));
  for (let yr = firstYear; yr <= lastYear; yr += every) years.push(yr);

  // Hover: the point on each line closest in time to the mouse.
  const nearest = (pts: ZLine["points"], t: number) =>
    pts.reduce((best, p) => (Math.abs(Date.parse(p.date) - t) < Math.abs(Date.parse(best.date) - t) ? p : best), pts[0]);
  const onMove = (e: React.MouseEvent<SVGSVGElement>) => {
    const box = e.currentTarget.getBoundingClientRect();
    const mx = ((e.clientX - box.left) / box.width) * W;
    const frac = Math.min(1, Math.max(0, (mx - PAD.left) / (W - PAD.left - PAD.right)));
    setHoverT(t0 + frac * (t1 - t0));
  };
  const hovered = hoverT === null ? [] : lines.map((l) => ({ ...l, p: nearest(l.line.points, hoverT) }));
  const sign = (z: number) => `${z >= 0 ? "+" : "−"}${Math.abs(z).toFixed(1)}`;
  const round = (v: number) => String(Number(v.toFixed(2)));

  return (
    <div style={{ position: "relative" }}>
      <div className="row" style={{ gap: 16, fontSize: 12, marginBottom: 4 }}>
        {lines.map((l) => (
          <span key={l.key} className="row" style={{ gap: 6, alignItems: "center" }}>
            <i style={{ width: 14, height: 3, borderRadius: 2, background: COLORS[l.key], display: "inline-block" }} />
            {l.key === "fish" ? "Fish" : "Water"}: {l.line.label}
          </span>
        ))}
      </div>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        width="100%"
        role="img"
        aria-label={`${lines.map((l) => l.line.label).join(" and ")}, each as standard deviations from its own average`}
        onMouseMove={onMove}
        onMouseLeave={() => setHoverT(null)}
        style={{ display: "block", cursor: "crosshair" }}
      >
        {ticks.map((v) => (
          <g key={v}>
            <line x1={PAD.left} x2={W - PAD.right} y1={y(v)} y2={y(v)} stroke={v === 0 ? "var(--muted-2)" : "var(--border-2)"} />
            <text x={PAD.left - 8} y={y(v)} textAnchor="end" dominantBaseline="middle" fontSize="11" fill="var(--muted)">
              {v === 0 ? "usual" : sign(v)}
            </text>
          </g>
        ))}
        {years.map((yr) => {
          const t = Date.UTC(yr, 0, 1);
          if (t < t0 || t > t1) return null;
          return <text key={yr} x={x(t)} y={H - 10} textAnchor="middle" fontSize="11" fill="var(--muted)">{yr}</text>;
        })}
        {lines.map((l) => (
          <path key={l.key} d={path(l.line.points)} fill="none" stroke={COLORS[l.key]} strokeWidth="2"
                strokeLinejoin="round" strokeLinecap="round" opacity={0.9} />
        ))}
        {/* Direct labels at the end of each line */}
        {lines.map((l) => {
          const last = l.line.points[l.line.points.length - 1];
          return (
            <text key={l.key} x={W - PAD.right + 8} y={y(last.z)} dominantBaseline="middle" fontSize="11" fill="var(--text-2)">
              {l.key === "fish" ? "Fish" : "Water"}
            </text>
          );
        })}
        {hoverT !== null && (
          <g pointerEvents="none">
            <line x1={x(hoverT)} x2={x(hoverT)} y1={PAD.top} y2={H - PAD.bottom} stroke="var(--muted-2)" strokeDasharray="3 3" />
            {hovered.map((h) => (
              <circle key={h.key} cx={x(Date.parse(h.p.date))} cy={y(h.p.z)} r="5" fill={COLORS[h.key]} stroke="var(--panel)" strokeWidth="2" />
            ))}
          </g>
        )}
      </svg>
      {hoverT !== null && (
        <div
          className="panel"
          style={{
            position: "absolute", top: 28, left: `${(x(hoverT) / W) * 100}%`,
            transform: x(hoverT) > W / 2 ? "translateX(calc(-100% - 12px))" : "translateX(12px)",
            padding: "6px 10px", pointerEvents: "none", fontSize: 12, whiteSpace: "nowrap",
            boxShadow: "0 2px 8px rgba(16, 24, 40, 0.12)",
          }}
        >
          {hovered.map((h) => (
            <div key={h.key} className="row" style={{ gap: 6, alignItems: "center" }}>
              <i style={{ width: 8, height: 8, borderRadius: 4, background: COLORS[h.key], display: "inline-block" }} />
              <span className="meta">{h.p.date}</span>
              <span className="num" style={{ color: "var(--text)" }}>
                {round(h.p.value)}{h.line.unit ? ` ${h.line.unit}` : ""} ({sign(h.p.z)})
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
