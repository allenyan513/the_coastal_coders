import { useState } from "react";
import { Link } from "react-router-dom";
import { clock } from "./api";

export type Slice = { key: string; label: string; n: number; color: string };
export type PointValue = { id: number; t: number; n: number };

/** Every fish counted at the points, as a ring split by species, with the total in the middle. */
export function SpeciesDonut({ slices, total, countLink }: { slices: Slice[]; total: number; countLink: string }) {
  const r = 64;
  const c = 2 * Math.PI * r;
  const sum = slices.reduce((a, s) => a + s.n, 0);
  const gap = slices.length > 1 ? 2 : 0;
  let at = 0;
  return (
    <section className="panel report-card">
      <div className="report-card-head"><h2>Fish by species</h2></div>
      <div className="donut-wrap">
        <div className="donut" role="img" aria-label={`${total} fish: ${slices.map((s) => `${s.label} ${s.n}`).join(", ")}`}>
          <svg viewBox="0 0 160 160" aria-hidden>
            <circle cx="80" cy="80" r={r} fill="none" stroke="var(--border-2)" strokeWidth="20" />
            {sum > 0 && slices.map((s) => {
              const len = (s.n / sum) * c;
              const el = (
                <circle
                  key={s.key}
                  cx="80" cy="80" r={r} fill="none" stroke={s.color} strokeWidth="20"
                  strokeDasharray={`${Math.max(0.5, len - gap)} ${c}`}
                  strokeDashoffset={-at}
                  transform="rotate(-90 80 80)"
                >
                  <title>{`${s.label}: ${s.n} (${Math.round((s.n / sum) * 100)}%)`}</title>
                </circle>
              );
              at += len;
              return el;
            })}
          </svg>
          <div className="donut-center">
            <b className="num">{total}</b>
            <small>fish counted</small>
          </div>
        </div>
        {sum > 0 ? (
          <ul className="donut-legend">
            {slices.map((s) => (
              <li key={s.key}>
                <i style={{ background: s.color }} />
                <span>{s.label}</span>
                <b className="num">{s.n}</b>
                <small className="num">{Math.round((s.n / sum) * 100)}%</small>
              </li>
            ))}
          </ul>
        ) : (
          <p className="meta">No points counted yet. <Link to={countLink}>Start counting</Link></p>
        )}
      </div>
    </section>
  );
}

/**
 * The mean per point for all fish or one species, with a bar for each point and the mean drawn across them.
 * A switch turns it into the total counted at the points. The protocol has no population estimate:
 * MeanCount is relative abundance, so the total is only what the counters added up, not how many fish live there.
 */
export function MeanCard({
  options, value, onChange, mean, values, checked, totalPoints, countLink,
}: {
  options: { key: string; label: string; color: string }[];
  value: string;
  onChange: (key: string) => void;
  mean: number | null;
  values: PointValue[];
  checked: number;
  totalPoints: number;
  countLink: string;
}) {
  const [total, setTotal] = useState(false);
  const sum = values.reduce((a, v) => a + v.n, 0);
  const most = Math.max(0, ...values.map((v) => v.n));
  const top = Math.max(1, ...values.map((v) => v.n), mean ?? 0);
  const color = options.find((o) => o.key === value)?.color ?? "var(--accent)";
  const name = options.find((o) => o.key === value)?.label ?? "All fish";
  return (
    <section className="panel report-card mean-card" style={{ "--sp": color } as React.CSSProperties}>
      <div className="report-card-head">
        <h2>{total ? "Total counted" : "Mean count"}</h2>
        <label className="mean-switch" title="Switch between the mean per point and the total counted">
          <span className={total ? "" : "on"}>Mean</span>
          <input type="checkbox" role="switch" checked={total} onChange={() => setTotal(!total)} aria-label="Show the total counted" />
          <span className={total ? "on" : ""}>Total</span>
        </label>
      </div>
      <div className="mean-pick" role="radiogroup" aria-label="Mean count of">
        {options.map((o) => (
          <button key={o.key} role="radio" aria-checked={value === o.key} className="mean-chip" onClick={() => onChange(o.key)} style={{ "--sp": o.color } as React.CSSProperties}>
            <i aria-hidden />{o.label}
          </button>
        ))}
      </div>
      <div className="mean-big">
        <b className="num">{mean === null ? "—" : total ? sum : mean.toFixed(2)}</b>
        <span>
          {mean === null
            ? <Link to={countLink}>Not counted yet. Start counting</Link>
            : total
              ? <>{value === "all" ? "fish" : name} counted across {checked} of {totalPoints} points</>
              : <>{value === "all" ? "fish" : name} per point · {checked} of {totalPoints} points</>}
        </span>
        {total && mean !== null && (
          <small className="mean-note">
            At least {most} {most === 1 ? "was" : "were"} there at once. Not a population estimate: a fish that stays can be counted at more than one point.
          </small>
        )}
      </div>
      {values.length > 0 && (
        <div className="mean-bars" role="img" aria-label={values.map((v) => `${clock(v.t)}: ${v.n}`).join(", ")}>
          {mean !== null && !total && <span className="mean-line" style={{ bottom: `calc(20px + (100% - 38px) * ${mean / top})` }}><small className="num">mean {mean.toFixed(1)}</small></span>}
          {values.map((v, i) => (
            <div key={v.id} className="mean-col" title={`Point ${i + 1} at ${clock(v.t)}: ${v.n}`}>
              <i style={{ height: `${(v.n / top) * 100}%` }}><span className="mean-n num">{v.n}</span></i>
              <small className="num">{clock(v.t)}</small>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

/** Anything counted that isn't a fish, such as crabs and jellyfish. */
export function NonFishCard({ rows, checked, countLink }: { rows: { key: string; label: string; n: number; seen: number }[]; checked: number; countLink: string }) {
  const total = rows.reduce((a, r) => a + r.n, 0);
  return (
    <section className="panel report-card nonfish-card">
      <div className="report-card-head">
        <h2>Non-fish</h2>
        {total > 0 && <span className="pill muted num">{total} counted</span>}
      </div>
      {rows.length ? (
        <ul className="nonfish-list">
          {rows.map((r) => (
            <li key={r.key}>
              <span>{r.label}</span>
              <b className="num">{r.n}</b>
              <small className="meta num">{(r.n / (checked || 1)).toFixed(2)} per point · seen at {r.seen} of {checked}</small>
            </li>
          ))}
        </ul>
      ) : (
        <p className="meta nonfish-empty">
          Nothing other than fish was counted. To count crabs, jellyfish and the like, add them with + Add species on the <Link to={countLink}>Count tab</Link>.
        </p>
      )}
    </section>
  );
}
