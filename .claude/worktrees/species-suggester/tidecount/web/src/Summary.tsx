import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, clock, Summary } from "./api";

export function SummaryPage() {
  const { id = "" } = useParams();
  const [s, setS] = useState<Summary | null>(null);

  useEffect(() => { api.summary(id).then(setS); }, [id]);
  if (!s) return <p className="meta">Loading…</p>;

  const pct = (v: number) => `${Math.round((v / (s.video.duration || 1)) * 100)}%`;
  const school = s.schools.reduce((n, c) => n + c.total, 0);
  const facts: [string, string][] = [
    ["Reviewed", clock(s.reviewed)],
    ["Could not see", clock(s.could_not_see)],
    ["Still in the queue", clock(s.pending)],
    ["Skipped by AI, unreviewed", clock(s.skipped)],
    ["Open AI suggestions, not counted", String(s.open_suggestions)],
    ["Audit of skipped footage", `${s.audit_segments} of ${s.audit_total} done, ${s.audit_fish} fish found`],
    ["Active review time", clock(s.review_seconds)],
  ];

  return (
    <div className="stack" style={{ gap: 20 }}>
      <div className="row" style={{ alignItems: "flex-end", justifyContent: "space-between" }}>
        <div>
          <Link className="btn" to={`/videos/${id}`} style={{ marginBottom: 12 }}>← Back to video</Link>
          <h1>{s.video.name} summary</h1>
          <p className="lede">Only results a person confirmed are counted here.</p>
        </div>
        <a className="btn primary" href={`/api/videos/${id}/export.csv`}>Export CSV</a>
      </div>

      <div className="panel kpis">
        <div className="kpi"><span className="meta">Fish entries</span><b>{s.entries}</b></div>
        <div className="kpi"><span className="meta">Species confirmed</span><b>{s.species_count}</b></div>
        <div className="kpi"><span className="meta">School count</span><b>{s.schools.length ? school : "—"}</b></div>
        <div className="kpi"><span className="meta">Footage reviewed</span><b>{pct(s.reviewed)}</b></div>
        <div className="kpi"><span className="meta">Could not see</span><b>{pct(s.could_not_see)}</b></div>
      </div>

      <div className="split" style={{ gridTemplateColumns: "minmax(0,1fr) 400px" }}>
        <div className="stack">
          <section className="panel">
            <div className="panel-head"><h2>Species</h2></div>
            <table>
              <thead><tr><th>Species</th><th className="right">Entries</th></tr></thead>
              <tbody>
                {s.species.map((r) => <tr key={r.name}><td>{r.name}</td><td className="num right">{r.entries}</td></tr>)}
                {!s.species.length && <tr><td colSpan={2} className="meta">Nothing confirmed yet.</td></tr>}
              </tbody>
            </table>
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
            {s.partial ? "MaxN isn't reported because this was a partial review. " : ""}
            Could not see is never counted as zero.
          </p>
          <p className="meta" style={{ lineHeight: 1.6 }}>Metric: entries, which can count one fish twice. {s.video.notes}</p>
        </section>
      </div>
    </div>
  );
}
