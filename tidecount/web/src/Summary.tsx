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
    ["Points could not see", String(snap.could_not_see)],
    ["Busiest moments checked", `${snap.peak_checked} of ${snap.peak_total}`],
  ];

  return (
    <div className="stack" style={{ gap: 16 }}>
      <VideoHeader id={id} step="report" />
      <div className="pagehead">
        <div>
          <h1>Report</h1>
          <p className="lede">Analysis window {clock(s.protocol.start)} to {clock(s.protocol.end)}. Only counts a person confirmed are included.</p>
        </div>
        <a className="btn primary" href={`/api/videos/${id}/protocol.csv`}>Export analysis sheet</a>
      </div>

      <div className="panel kpis">
        <div className="kpi">
          <span className="meta">MeanCount</span>
          <b>{snap.mean_count?.toFixed(2) ?? "—"}</b>
          {snap.mean_count !== null
            ? <small className="meta num">Fish per point, {snap.frames_checked} of {snap.frames_total} points</small>
            : <small><Link to={`/videos/${id}/snapshots`}>Not counted yet. Start counting</Link></small>}
        </div>
        <div className="kpi">
          <span className="meta">Invertebrates per point</span>
          <b>{snap.invertebrate_mean?.toFixed(2) ?? "—"}</b>
        </div>
        <div className="kpi">
          <span className="meta">Species observed</span>
          <b>{s.species_observed.length}</b>
          <small className="meta">{s.species_observed.join(", ") || "None named yet"}</small>
        </div>
        <div className="kpi">
          <span className="meta">Visibility</span>
          <b style={{ fontSize: 20 }}>{s.protocol.visibility || "—"}</b>
          <small className="meta">Juveniles: {s.protocol.juveniles === null ? "not noted" : s.protocol.juveniles ? "present" : "absent"}</small>
        </div>
      </div>

      <section className="panel" style={{ overflowX: "auto" }}>
        <div className="panel-head"><h2>Sub-sample points</h2></div>
        <table>
          <thead><tr><th>Point</th><th>Time</th><th>Visibility</th><th className="right">Fish</th><th className="right">Invertebrates</th><th>Species</th><th>Notes</th></tr></thead>
          <tbody>
            {s.points.map((p, i) => (
              <tr key={p.id}>
                <td className="num">{i + 1}</td>
                <td className="num">{clock(p.t)}</td>
                <td>{p.visibility || s.protocol.visibility || "—"}</td>
                <td className="num right">{p.status === "checked" ? p.total : p.status ? "Could not see" : "—"}</td>
                <td className="num right">{p.status === "checked" ? p.invertebrates ?? 0 : "—"}</td>
                <td>{p.species.map((x) => `${x.name} ${x.n}`).join(", ")}</td>
                <td className="meta">{p.comment}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      {!!s.peaks.length && (
        <section className="panel" style={{ overflowX: "auto" }}>
          <div className="panel-head"><h2>Busiest moments AI found</h2></div>
          <p className="meta" style={{ padding: "0 16px 12px", lineHeight: 1.6 }}>
            MeanCount only sees the sub-sample points, so a school that passes between two of them isn't in it. These are AI's busiest moments away from those points. AI's numbers are unchecked until a person opens the frame, and they never feed MeanCount.
          </p>
          <table>
            <thead><tr><th>Time</th><th>Where</th><th className="right">AI's count</th><th className="right">Person's count</th><th /></tr></thead>
            <tbody>
              {s.peaks.map((p) => (
                <tr key={p.id}>
                  <td className="num">{clock(p.t)}</td>
                  <td>{p.in_window ? "Between points" : "Outside the window"}</td>
                  <td className="num right">{p.ai_count}</td>
                  <td className="num right">{p.status === "checked" ? p.total : p.status ? "Could not see" : "—"}</td>
                  <td className="right"><Link className="btn" to={`/videos/${id}/snapshots?mode=ai&frame=${p.id}`}>Check frame</Link></td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      <details className="stack">
        <summary className="meta">AI-assisted review of the whole video</summary>
        <div className="stack" style={{ gap: 16, marginTop: 12 }}>
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
          <span className="meta">Most fish in one frame</span>
          <b>{snap.largest_count ?? "—"}</b>
          <small className="meta">{snap.largest_count === null ? "Needs a count" : snap.largest_label}</small>
        </div>
        <div className="kpi">
          <span className="meta">Fish entries</span>
          <b>{s.entries}</b>
          <small className="meta">Confirmed tracks. One fish can count twice.</small>
        </div>
        <div className="kpi"><span className="meta">Species named</span><b>{s.species_count}</b></div>
        {!!s.schools.length && <div className="kpi"><span className="meta">Fish in counted schools</span><b>{school}</b></div>}
      </div>

      <div className="split report-split">
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
            <section className="panel" style={{ overflowX: "auto" }}>
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
      <a className="btn" style={{ alignSelf: "flex-start" }} href={`/api/videos/${id}/export.csv`}>Export review data</a>
        </div>
      </details>
    </div>
  );
}
