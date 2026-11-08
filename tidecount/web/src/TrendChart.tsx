import { useEffect, useMemo, useRef, useState } from "react";

/**
 * Population trend on the Report: the mean count at earlier surveys of this station, with this
 * report's mean added as the newest point on the right. Earlier surveys are made-up sample data for
 * now (we don't have the history yet), generated the same way every time from the station and species,
 * so the lines don't jump about between visits. Only the last point of this station's lines is real.
 */
export type TrendSeries = { key: string; label: string; color: string; current: number | null };
export type TrendStation = { id: string; label: string };

type Point = { date: string; value: number; real: boolean };
type Line = { key: string; label: string; color: string; dashed: boolean; points: Point[] };

const HISTORY = 8; // earlier surveys shown before this one
const STEP_DAYS = 45; // about one survey every six weeks

/** A small seeded random number generator, so sample data is the same on every visit. */
function seeded(text: string) {
  let h = 2166136261;
  for (const c of text) h = Math.imul(h ^ c.charCodeAt(0), 16777619);
  return () => {
    h = Math.imul(h ^ (h >>> 15), 2246822507);
    h = Math.imul(h ^ (h >>> 13), 3266489909);
    return ((h ^= h >>> 16) >>> 0) / 4294967296;
  };
}

const addDays = (date: string, days: number) => {
  const d = new Date(`${date}T12:00:00`);
  d.setDate(d.getDate() + days);
  return d.toISOString().slice(0, 10);
};
const shortDate = (date: string) => new Date(`${date}T12:00:00`).toLocaleDateString(undefined, { month: "short", year: "2-digit" });
const longDate = (date: string) => new Date(`${date}T12:00:00`).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });

/** The dates of earlier surveys. Every station shares them, so lines line up when compared. */
function surveyDates(seed: string, today: string) {
  const rand = seeded(`${seed}|dates`);
  return Array.from({ length: HISTORY }, (_, i) => addDays(today, -STEP_DAYS * (HISTORY - i) + Math.round((rand() - 0.5) * 10)));
}

/** Earlier surveys for one line, drifting towards `end` so the newest real point sits naturally on the end. */
function history(seed: string, end: number, dates: string[]): Point[] {
  const rand = seeded(seed);
  const slope = (rand() - 0.5) * 0.16; // each survey up to 8% above or below the next one
  return dates.map((date, i) => {
    const level = end * (1 - slope * (dates.length - i));
    const noise = 0.78 + rand() * 0.44;
    return { date, value: Math.max(0, Math.round(level * noise * 100) / 100), real: false };
  });
}

/** How this survey compares with the average of the three before it. */
function trendOf(points: Point[]) {
  const last = points[points.length - 1];
  const before = points.slice(-4, -1);
  if (!last?.real || before.length < 2) return null;
  const avg = before.reduce((a, p) => a + p.value, 0) / before.length;
  if (avg === 0) return null;
  return (last.value - avg) / avg;
}

export function TrendCard({
  series, stationId, stationLabel, stations, filmedOn,
}: {
  series: TrendSeries[];
  stationId: string;
  stationLabel: string;
  stations: TrendStation[];
  filmedOn: string;
}) {
  const [picked, setPicked] = useState<string[]>(["all"]);
  const [compare, setCompare] = useState("");
  const [hover, setHover] = useState<number | null>(null);
  const box = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(800);

  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setWidth(Math.max(280, e.contentRect.width)));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const shown = series.filter((s) => picked.includes(s.key));
  const other = stations.find((s) => s.id === compare);

  const lines: Line[] = useMemo(() => {
    const out: Line[] = [];
    const when = surveyDates(stationId, filmedOn);
    for (const s of shown) {
      // With no count yet, the sample still needs a level to sit at.
      const base = s.current ?? 4 + seeded(`${stationId}|${s.key}|base`)() * 6;
      const past = history(`${stationId}|${s.key}`, base, when);
      out.push({ key: s.key, label: s.label, color: s.color, dashed: false, points: s.current === null ? past : [...past, { date: filmedOn, value: s.current, real: true }] });
      if (other) {
        const scale = 0.5 + seeded(`${other.id}|${s.key}|scale`)();
        const theirs = history(`${other.id}|${s.key}`, base * scale, when);
        const last = seeded(`${other.id}|${s.key}|last`)();
        theirs.push({ date: filmedOn, value: Math.round(base * scale * (0.85 + last * 0.3) * 100) / 100, real: false });
        out.push({ key: `${s.key}@${other.id}`, label: `${s.label} · ${other.label}`, color: s.color, dashed: true, points: theirs });
      }
    }
    return out;
  }, [shown.map((s) => `${s.key}:${s.current}`).join(), stationId, other?.id, filmedOn]);

  const toggle = (key: string) =>
    setPicked((now) => (now.includes(key) ? (now.length > 1 ? now.filter((k) => k !== key) : now) : [...now, key]));

  // Chart geometry.
  const H = 260;
  const pad = { l: 40, r: 48, t: 26, b: 30 };
  const dates = [...new Set(lines.flatMap((l) => l.points.map((p) => p.date)))].sort();
  const first = dates[0] ?? filmedOn;
  const lastDate = dates[dates.length - 1] ?? filmedOn;
  const span = Math.max(1, (+new Date(lastDate) - +new Date(first)) / 864e5);
  const x = (date: string) => pad.l + ((+new Date(date) - +new Date(first)) / 864e5 / span) * (width - pad.l - pad.r);
  const top = Math.max(1, ...lines.flatMap((l) => l.points.map((p) => p.value)));
  const nice = niceMax(top);
  const y = (v: number) => pad.t + (1 - v / nice) * (H - pad.t - pad.b);
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => f * nice);
  const thisX = x(filmedOn);

  const main = lines.find((l) => !l.dashed);
  const trend = main ? trendOf(main.points) : null;
  const hoverDate = hover === null ? null : dates.reduce((best, d) => (Math.abs(x(d) - hover) < Math.abs(x(best) - hover) ? d : best), dates[0]);
  const near = (l: Line, date: string) =>
    l.points.reduce<Point | null>((best, p) => (Math.abs(+new Date(p.date) - +new Date(date)) < 12 * 864e5 && (!best || Math.abs(+new Date(p.date) - +new Date(date)) < Math.abs(+new Date(best.date) - +new Date(date))) ? p : best), null);

  return (
    <section className="panel report-card trend-card">
      <div className="report-card-head">
        <div>
          <h2>Population trend</h2>
          <p className="meta trend-sub">Mean count per survey at {stationLabel || "this station"}. Oldest on the left, this report on the right.</p>
        </div>
        <div className="row" style={{ gap: 8 }}>
          {trend !== null && main && (
            <span className={`trend-badge ${trend > 0.05 ? "up" : trend < -0.05 ? "down" : "flat"}`} title="This report against the average of the three surveys before it">
              {trend > 0.05 ? "▲" : trend < -0.05 ? "▼" : "▬"} {main.label} {trend > 0.05 ? "up" : trend < -0.05 ? "down" : "steady"} {Math.abs(Math.round(trend * 100))}%
            </span>
          )}
          <span className="pill muted">Earlier surveys are sample data</span>
        </div>
      </div>

      <div className="trend-controls">
        <div className="mean-pick" role="group" aria-label="Lines to show">
          {series.map((s) => (
            <button key={s.key} className="mean-chip" aria-pressed={picked.includes(s.key)} onClick={() => toggle(s.key)} style={{ "--sp": s.color } as React.CSSProperties}>
              <i aria-hidden />{s.label}
            </button>
          ))}
        </div>
        {stations.length > 0 && (
          <label className="trend-compare">
            <span className="meta">Compare with</span>
            <select value={compare} onChange={(e) => setCompare(e.target.value)}>
              <option value="">No other station</option>
              {stations.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
            </select>
          </label>
        )}
      </div>

      <div className="trend-plot" ref={box} onPointerMove={(e) => setHover(e.clientX - e.currentTarget.getBoundingClientRect().left)} onPointerLeave={() => setHover(null)}>
        <svg width={width} height={H} role="img" aria-label={lines.map((l) => `${l.label}: ${l.points.map((p) => `${shortDate(p.date)} ${p.value}`).join(", ")}`).join(". ")}>
          {ticks.map((t) => (
            <g key={t}>
              <line x1={pad.l} x2={width - pad.r} y1={y(t)} y2={y(t)} className="trend-grid" />
              <text x={pad.l - 8} y={y(t) + 4} className="trend-axis" textAnchor="end">{fmt(t)}</text>
            </g>
          ))}
          {dates.filter((_, i) => dates.length <= 10 || i % 2 === dates.length % 2).map((d) => (
            <text key={d} x={x(d)} y={H - 8} className="trend-axis" textAnchor="middle">{shortDate(d)}</text>
          ))}
          <rect x={thisX - 16} y={pad.t - 6} width={32} height={H - pad.t - pad.b + 6} className="trend-now" rx={6} />
          <text x={thisX} y={pad.t - 9} className="trend-axis trend-now-label" textAnchor="middle">This report</text>
          {lines.map((l) => (
            <g key={l.key}>
              <path
                d={l.points.map((p, i) => `${i ? "L" : "M"}${x(p.date).toFixed(1)},${y(p.value).toFixed(1)}`).join(" ")}
                fill="none" stroke={l.color} strokeWidth={l.dashed ? 2 : 2.5} strokeDasharray={l.dashed ? "6 5" : undefined} strokeLinejoin="round" strokeLinecap="round"
                opacity={l.dashed ? 0.75 : 1}
              />
              {l.points.map((p) => (
                <circle key={p.date} cx={x(p.date)} cy={y(p.value)} r={p.real ? 6 : 3} fill={p.real ? l.color : "var(--panel)"} stroke={l.color} strokeWidth={p.real ? 3 : 2} className={p.real ? "trend-real" : ""} />
              ))}
            </g>
          ))}
          {hoverDate && <line x1={x(hoverDate)} x2={x(hoverDate)} y1={pad.t} y2={H - pad.b} className="trend-guide" />}
        </svg>
        {hoverDate && (
          <div className="trend-tip" style={{ left: Math.min(x(hoverDate) + 12, width - 210) }}>
            <b>{longDate(hoverDate)}{hoverDate === filmedOn ? " · this report" : ""}</b>
            {lines.map((l) => {
              const p = near(l, hoverDate);
              return p && (
                <span key={l.key}>
                  <i style={{ background: l.color, opacity: l.dashed ? 0.6 : 1 }} />{l.label}
                  <b className="num">{p.value.toFixed(2)}</b>
                </span>
              );
            })}
          </div>
        )}
      </div>
      <div className="trend-key meta">
        <span><i className="trend-key-dot" /> Sample survey</span>
        <span><i className="trend-key-dot real" /> This report, from the count</span>
        {other && <span><i className="trend-key-dash" /> {other.label}</span>}
      </div>
    </section>
  );
}

/** A round number just above `v` for the top of the axis. */
function niceMax(v: number) {
  const pow = 10 ** Math.floor(Math.log10(v));
  const n = v / pow;
  return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 2.5 ? 2.5 : n <= 5 ? 5 : 10) * pow;
}
const fmt = (v: number) => (Number.isInteger(v) ? String(v) : v.toFixed(1));
