import { useEffect, useRef, useState } from "react";
import {
  describeRange, fromPositions, lastPosition, sameRange, tickYears, toPositions, yearAt,
  type YearPreset, type YearRange, type YearScale,
} from "./yearRange";

type Props = {
  scale: YearScale;
  value: YearRange;
  /** Called when the person lets go of a handle, picks a preset or stops using the keys, never while dragging. */
  onCommit: (range: YearRange) => void;
  presets?: YearPreset[];
  /** What the range is of, for the label read to screen readers: "Years shown". */
  label?: string;
};

const KEY_SETTLE_MS = 500; // after the last arrow key, so holding one down is one change

/**
 * One bar with two handles to pick a start and end year, one year at a time, with preset chips.
 * The left end is "earlier": a start handle there takes every older record, however old.
 * It knows nothing about OBIS: any source whose records have dates can use it. The text shows the
 * range being dragged, but the page is told only when the handle is let go.
 */
export default function YearRangeSlider({ scale, value, onCommit, presets = [], label = "Years shown" }: Props) {
  const last = lastPosition(scale);
  const [draft, setDraft] = useState<[number, number]>(() => toPositions(value, scale));
  const timer = useRef(0);
  const committed = useRef(value);
  committed.current = value;

  // Follow the value when it changes from outside (a preset, or a new fish).
  useEffect(() => { setDraft(toPositions(value, scale)); }, [value.from, value.to, scale.first, scale.last]);
  useEffect(() => () => window.clearTimeout(timer.current), []);

  const shown = fromPositions(draft[0], draft[1], scale);
  const commit = (d: [number, number]) => {
    const next = fromPositions(d[0], d[1], scale);
    if (!sameRange(next, committed.current)) onCommit(next);
  };
  const settle = (d: [number, number]) => {
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => commit(d), KEY_SETTLE_MS);
  };

  const [i, j] = draft;
  const pct = (n: number) => (last ? (n / last) * 100 : 0);
  const yearOf = (n: number, end: boolean) => (n <= 0 && !end ? "the earliest record" : n >= last && end ? "the latest record" : String(yearAt(n, scale)));
  const pick = (r: YearRange) => { window.clearTimeout(timer.current); setDraft(toPositions(r, scale)); onCommit(r); };

  // Whichever handle can still move toward the middle stays on top when both sit at one end.
  const startOnTop = i >= last / 2;

  return (
    <div className="year-range" role="group" aria-label={label}>
      <div className="year-range-head">
        <span className="meta">Years</span>
        <b className="num year-range-text" aria-live="polite">{describeRange(shown)}</b>
        {presets.length > 0 && (
          <div className="row year-range-presets" role="group" aria-label="Quick choices">
            {presets.map((p) => (
              <button key={p.label} type="button" className="chip" aria-pressed={sameRange(p.range, shown)} onClick={() => pick(p.range)}>{p.label}</button>
            ))}
          </div>
        )}
      </div>
      <div className="year-range-bar">
        <div className="year-range-track" aria-hidden="true">
          <div className="year-range-fill" style={{ left: `${pct(i)}%`, width: `${pct(j) - pct(i)}%` }} />
        </div>
        <input
          type="range" className="year-range-input" style={{ zIndex: startOnTop ? 3 : 2 }}
          min={0} max={last} step={1} value={i}
          aria-label="First year" aria-valuetext={yearOf(i, false)}
          onChange={(e) => setDraft(([, b]) => [Math.min(Number(e.target.value), b), b])}
          onPointerUp={() => commit(draft)}
          onKeyUp={() => settle(draft)}
          onBlur={() => { window.clearTimeout(timer.current); commit(draft); }}
        />
        <input
          type="range" className="year-range-input" style={{ zIndex: startOnTop ? 2 : 3 }}
          min={0} max={last} step={1} value={j}
          aria-label="Last year" aria-valuetext={yearOf(j, true)}
          onChange={(e) => setDraft(([a]) => [a, Math.max(Number(e.target.value), a)])}
          onPointerUp={() => commit(draft)}
          onKeyUp={() => settle(draft)}
          onBlur={() => { window.clearTimeout(timer.current); commit(draft); }}
        />
      </div>
      <div className="year-range-ticks" aria-hidden="true">
        <span style={{ left: "0%" }}>Earlier</span>
        {tickYears(scale).map((y) => (
          <span key={y} style={{ left: `${pct(y - scale.first + 1)}%` }}>{y}</span>
        ))}
      </div>
    </div>
  );
}
