import { useState } from "react";

type Point = { date: string; value: number };

// The drawing is made at this size and scaled to fit the page, so it works at any width.
const W = 800;
const H = 300;
const PAD = { top: 16, right: 16, bottom: 32, left: 56 };

/**
 * One measurement over time, as a line. Hovering shows the nearest reading.
 * Dates go along the bottom and values up the side. Plain SVG, so no chart library is needed.
 */
export function WaterChart({ points, label, unit }: { points: Point[]; label: string; unit: string }) {
  const [hover, setHover] = useState<number | null>(null);

  if (points.length === 0) return <p className="meta">No readings of this measurement at this site.</p>;

  // 1. Turn every date into a number (milliseconds), so dates can be placed along a line.
  const times = points.map((p) => Date.parse(p.date));
  const t0 = Math.min(...times);
  const t1 = Math.max(...times);

  // 2. The value range, rounded out to tidy numbers for the side labels.
  const ticks = niceTicks(Math.min(...points.map((p) => p.value)), Math.max(...points.map((p) => p.value)));
  const v0 = ticks[0];
  const v1 = ticks[ticks.length - 1];

  // 3. Scales: turn a time or a value into a position inside the drawing.
  //    SVG's y grows downwards, so a bigger value needs a smaller y.
  const x = (t: number) => PAD.left + (t1 === t0 ? 0.5 : (t - t0) / (t1 - t0)) * (W - PAD.left - PAD.right);
  const y = (v: number) => PAD.top + (v1 === v0 ? 0.5 : 1 - (v - v0) / (v1 - v0)) * (H - PAD.top - PAD.bottom);

  // 4. The line: "M" moves to a point without drawing, "L" draws to it.
  //    Where no one sampled for months, the line lifts and starts again, so it doesn't invent readings across the gap.
  const GAP_MS = 120 * 24 * 60 * 60 * 1000; // 120 days
  const path = points
    .map((p, i) => `${i === 0 || times[i] - times[i - 1] > GAP_MS ? "M" : "L"}${x(times[i]).toFixed(1)},${y(p.value).toFixed(1)}`)
    .join(" ");

  // 5. One label per year along the bottom, skipping some when there are many.
  const firstYear = new Date(t0).getUTCFullYear();
  const lastYear = new Date(t1).getUTCFullYear();
  const every = Math.max(1, Math.ceil((lastYear - firstYear + 1) / 10));
  const years: number[] = [];
  for (let yr = firstYear; yr <= lastYear; yr += every) years.push(yr);

  // 6. Hovering: find the reading closest in time to the mouse.
  const onMove = (e: React.MouseEvent<SVGSVGElement>) => {
    const box = e.currentTarget.getBoundingClientRect();
    const mx = ((e.clientX - box.left) / box.width) * W;
    let best = 0;
    for (let i = 1; i < times.length; i++) if (Math.abs(x(times[i]) - mx) < Math.abs(x(times[best]) - mx)) best = i;
    setHover(best);
  };
  const h = hover === null ? null : points[hover];
  const unitText = unit ? ` ${unit}` : "";

  return (
    <div style={{ position: "relative" }}>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        width="100%"
        role="img"
        aria-label={`${label} from ${points[0].date} to ${points[points.length - 1].date}, ${points.length} readings`}
        onMouseMove={onMove}
        onMouseLeave={() => setHover(null)}
        style={{ display: "block", cursor: "crosshair" }}
      >
        {/* Light grid lines and the value labels up the side */}
        {ticks.map((v) => (
          <g key={v}>
            <line x1={PAD.left} x2={W - PAD.right} y1={y(v)} y2={y(v)} stroke="var(--border-2)" />
            <text x={PAD.left - 8} y={y(v)} textAnchor="end" dominantBaseline="middle" fontSize="11" fill="var(--muted)">
              {formatNumber(v)}
            </text>
          </g>
        ))}

        {/* Year labels along the bottom */}
        {years.map((yr) => {
          const t = Date.UTC(yr, 0, 1);
          if (t < t0 || t > t1) return null;
          return (
            <text key={yr} x={x(t)} y={H - 10} textAnchor="middle" fontSize="11" fill="var(--muted)">
              {yr}
            </text>
          );
        })}

        {/* The readings */}
        <path d={path} fill="none" stroke="var(--accent)" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />

        {/* What the mouse is over: a guide line and a ringed dot */}
        {h && hover !== null && (
          <g pointerEvents="none">
            <line x1={x(times[hover])} x2={x(times[hover])} y1={PAD.top} y2={H - PAD.bottom} stroke="var(--muted-2)" strokeDasharray="3 3" />
            <circle cx={x(times[hover])} cy={y(h.value)} r="5" fill="var(--accent)" stroke="var(--panel)" strokeWidth="2" />
          </g>
        )}
      </svg>

      {/* The tooltip, kept inside the chart on both sides */}
      {h && hover !== null && (
        <div
          className="panel"
          style={{
            position: "absolute",
            top: 8,
            left: `${(x(times[hover]) / W) * 100}%`,
            transform: x(times[hover]) > W / 2 ? "translateX(calc(-100% - 12px))" : "translateX(12px)",
            padding: "6px 10px",
            pointerEvents: "none",
            fontSize: 12,
            whiteSpace: "nowrap",
            boxShadow: "0 2px 8px rgba(16, 24, 40, 0.12)",
          }}
        >
          <div className="meta">{h.date}</div>
          <div className="num" style={{ color: "var(--text)" }}>{formatNumber(h.value)}{unitText}</div>
        </div>
      )}

      {/* The same readings as a table, for anyone who can't use the chart */}
      <details style={{ marginTop: 8 }}>
        <summary className="meta" style={{ cursor: "pointer" }}>Show the readings as a table</summary>
        <div style={{ maxHeight: 240, overflowY: "auto", marginTop: 8 }}>
          <table>
            <thead><tr><th>Date</th><th className="right">{label}{unitText}</th></tr></thead>
            <tbody>
              {points.map((p, i) => <tr key={i}><td className="num">{p.date}</td><td className="num right">{formatNumber(p.value)}</td></tr>)}
            </tbody>
          </table>
        </div>
      </details>
    </div>
  );
}

/** About 5 evenly spaced, round numbers that cover lo to hi, such as 0, 5, 10, 15. */
function niceTicks(lo: number, hi: number): number[] {
  if (lo === hi) { lo -= 1; hi += 1; }
  const rough = (hi - lo) / 4;
  const power = 10 ** Math.floor(Math.log10(rough));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * power).find((s) => s >= rough) ?? 10 * power;
  const start = Math.floor(lo / step) * step;
  const out: number[] = [];
  for (let v = start; ; v += step) {
    out.push(Number(v.toFixed(10)));
    if (v >= hi) break; // stop at the first tick at or above the highest value
  }
  return out;
}

/** Up to 2 decimal places, without trailing zeros: 8.07, 12.5, 30. */
function formatNumber(v: number): string {
  return String(Number(v.toFixed(2)));
}
