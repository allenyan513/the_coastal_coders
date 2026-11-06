import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, clock, Summary } from "./api";
import { VideoHeader } from "./VideoHeader";

export function SummaryPage() {
  const { id = "" } = useParams();
  const [s, setS] = useState<Summary | null>(null);

  useEffect(() => { api.summary(id).then(setS); }, [id]);
  if (!s) return <p className="meta">Loading…</p>;

  const total = s.video.duration || 1;
  const pct = (v: number) => `${Math.round((v / total) * 100)}%`;
  const queue = s.reviewed + s.could_not_see + s.pending;
  const school = s.schools.reduce((n, c) => n + c.total, 0);
  const snap = s.snapshots;
  const most = Math.max(1, ...s.species.map((r) => r.entries));
  const parts = [
    { name: "Reviewed", value: s.reviewed, color: "var(--up)" },
    { name: "Could not see", value: s.could_not_see, color: "var(--amber)" },
    { name: "Still in the queue", value: s.pending, color: "var(--text-2)" },
    { name: "Skipped by AI", value: s.skipped, color: "var(--skip)" },
  ];
  const facts: [string, string][] = [
    ["Fish AI missed, added by a person", `${s.entries_added} of ${s.entries} entries`],
    ["Open AI suggestions, not counted", String(s.open_suggestions)],
    ["Audit of skipped footage", `${s.audit_segments} of ${s.audit_total} done, ${s.audit_fish} fish found`],
    ["Time spent reviewing", clock(s.review_seconds)],
    ["Snapshot frames checked", `${snap.frames_checked} of ${snap.frames_total}`],
    ["Snapshot frames could not see", String(snap.could_not_see)],
    ["Peak frames checked", `${snap.peak_checked} of ${snap.peak_total}`],
    ["Peak frames could not see", String(snap.peak_could_not_see)],
  ];

  return (
    <div className="stack" style={{ gap: 16 }}>
      <VideoHeader id={id} step="report" />
      <div className="pagehead">
        <div>
          <h1>Report</h1>
          <p className="lede">Only results a person confirmed are counted here.</p>
        </div>
        <a className="btn primary" href={`/api/videos/${id}/export.csv`}>Export CSV</a>
      </div>

      <section className="panel" aria-label="Footage">
        <div className="kpis big">
          <div className="kpi"><span className="meta">Footage</span><b>{clock(s.video.duration)}</b></div>
          <div className="kpi">
            <span className="meta">Queued for a person to watch</span>
            <b>{clock(queue)}</b>
            <small className="meta num">{pct(queue)} of the footage</small>
          </div>
          <div className="kpi">
            <span className="meta">Skipped by AI</span>
            <b>{pct(s.skipped)}</b>
            <small className="meta num">{clock(s.skipped)} with no detections</small>
          </div>
        </div>
        <div className="panel-pad" style={{ gap: 10, padding: "4px 20px 16px" }}>
          <div className="band" role="img" aria-label={parts.map((p) => `${p.name} ${clock(p.value)}`).join(", ")}>
            {parts.filter((p) => p.value > 0).map((p) => <i key={p.name} title={`${p.name}: ${clock(p.value)}, ${pct(p.value)}`} style={{ flex: `${p.value} 0 0`, background: p.color }} />)}
          </div>
          <div className="legend">
            {parts.map((p) => <span key={p.name}><i style={{ background: p.color }} />{p.name} <b className="num" style={{ color: "var(--text)", fontWeight: 500 }}>{clock(p.value)}</b></span>)}
          </div>
        </div>
      </section>

      <div className="panel kpis">
        <div className="kpi">
          <span className="meta">Average fish per snapshot</span>
          <b>{snap.mean_count?.toFixed(2) ?? "—"}</b>
          {snap.mean_count !== null
            ? <small className="meta num">MeanCount, {snap.frames_checked} of {snap.frames_total} frames</small>
            : <small><Link to={`/videos/${id}/snapshots`}>Not counted yet. Start the snapshot count</Link></small>}
        </div>
        <div className="kpi">
          <span className="meta">Most fish in one frame</span>
          <b>{snap.largest_count ?? "—"}</b>
          <small className="meta">{snap.largest_count === null ? "Needs the snapshot count" : snap.largest_label}</small>
        </div>
        <div className="kpi">
          <span className="meta">Fish entries</span>
          <b>{s.entries}</b>
          <small className="meta">Confirmed tracks. One fish can count twice.</small>
        </div>
        <div className="kpi"><span className="meta">Species named</span><b>{s.species_count}</b></div>
        {!!s.schools.length && <div className="kpi"><span className="meta">Fish in counted schools</span><b>{school}</b></div>}
      </div>

      <div className="split" style={{ gridTemplateColumns: "minmax(0,1fr) 380px" }}>
        <div className="stack">
          <section className="panel">
            <div className="panel-head">
              <h2>Fish entries by species</h2>
            </div>
            {s.species.map((r) => (
              <div className="sbar-row" key={r.name} title={`${r.name}: ${r.entries} ${r.entries === 1 ? "entry" : "entries"}`}>
                <span>{r.name}</span>
                <span><i className="sbar" style={{ width: `${(r.entries / most) * 100}%` }} /></span>
                <span className="num right">{r.entries}</span>
              </div>
            ))}
            {!s.species.length && <p className="meta" style={{ padding: 12 }}>Nothing confirmed yet.</p>}
          </section>
          {!!s.schools.length && (
            <section className="panel">
              <div className="panel-head"><h2>School counts</h2></div>
              <table>
                <thead><tr><th>Time</th><th className="right">Total</th><th className="right">AI proposed</th><th className="right">Removed</th><th className="right">Added</th></tr></thead>
                <tbody>
                  {s.schools.map((c, i) => (
                    <tr key={i}><td className="num">{clock(c.t)}</td><td className="num right">{c.total}</td><td className="num right">{c.proposed}</td><td className="num right">{c.removed}</td><td className="num right">{c.added}</td></tr>
                  ))}
                </tbody>
              </table>
            </section>
          )}
        </div>
        <section className="panel panel-pad">
          <h2>What this covers</h2>
          {facts.map(([k, v]) => (
            <div key={k} className="row" style={{ justifyContent: "space-between", fontSize: 13 }}><span>{k}</span><span className="num">{v}</span></div>
          ))}
          <p style={{ color: "var(--text-2)", fontSize: 13, lineHeight: 1.6, borderTop: "1px solid var(--border-2)", paddingTop: 12, marginTop: 4 }}>
            {s.audit_fish > 0 ? "The audit found fish in skipped footage, so totals may be low. " : ""}
            {s.partial && !snap.complete ? "MaxN isn't reported because this was a partial review. " : ""}
            {snap.complete && snap.peak_total > snap.peak_checked + snap.peak_could_not_see ? "Some peak frames are still open, so MaxN may rise. " : ""}
            Could not see is never counted as zero.
          </p>
          <p className="meta" style={{ lineHeight: 1.6 }}>{s.video.notes}</p>
        </section>
      </div>
    </div>
  );
}
