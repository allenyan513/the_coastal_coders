import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, clock, Summary, Video } from "./api";
import { reviewProgress } from "./Library";

type Row = { video: Video; summary: Summary };

/** Every analysed video side by side, grouped by site. One row per video: the run with the most review done. */
export function Reports() {
  const [rows, setRows] = useState<Row[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.videos()
      .then((all) => Promise.all(all.filter((v) => v.status === "Ready to review").map(async (video) => ({ video, summary: await api.summary(video.id) }))))
      .then(setRows)
      .catch((e) => setError(e.message));
  }, []);

  const sites = useMemo(() => {
    const best = new Map<string, Row>();
    (rows ?? []).forEach((r) => {
      const root = r.video.source_id || r.video.id;
      const kept = best.get(root);
      if (!kept || reviewProgress(r.summary).done > reviewProgress(kept.summary).done) best.set(root, r);
    });
    const out = new Map<string, Row[]>();
    best.forEach((r) => out.set(r.video.site || "No site set", [...(out.get(r.video.site || "No site set") ?? []), r]));
    return [...out].sort((a, b) => a[0].localeCompare(b[0]));
  }, [rows]);

  if (error) return <p className="meta">{error}</p>;
  if (!rows) return <p className="meta">Loading…</p>;

  return (
    <div className="stack" style={{ gap: 20 }}>
      <div>
        <h1>Reports</h1>
        <p className="lede">Results a person confirmed, video by video. AI suggestions that nobody checked aren't counted.</p>
      </div>
      {sites.map(([site, list]) => (
        <section className="panel" key={site}>
          <div className="panel-head"><h2>{site}</h2></div>
          <table className="cards">
            <thead>
              <tr>
                <th>Video</th><th className="right">Length</th><th className="right">Watched</th><th className="right">Skipped by AI</th>
                <th className="right">Fish entries</th><th className="right">Species named</th><th className="right">Average per snapshot</th><th className="right">Most in one frame</th><th />
              </tr>
            </thead>
            <tbody>
              {list.map(({ video: v, summary: s }) => {
                const p = reviewProgress(s);
                return (
                  <tr key={v.id}>
                    <td><Link className="vname" to={`/videos/${v.id}/summary`}>{v.name}</Link></td>
                    <td className="num right" data-label="Length">{clock(v.duration)}</td>
                    <td className="num right" data-label="Watched">{clock(p.done)} of {clock(p.total)}</td>
                    <td className="num right" data-label="Skipped by AI">{clock(s.skipped)}</td>
                    <td className="num right" data-label="Fish entries">{s.entries}</td>
                    <td className="num right" data-label="Species named">{s.species_count}</td>
                    <td className="num right" data-label="Average per snapshot">{s.snapshots.mean_count?.toFixed(2) ?? "—"}</td>
                    <td className="num right" data-label="Most in one frame">{s.snapshots.largest_count ?? "—"}</td>
                    <td className="right"><a className="btn" href={`/api/videos/${v.id}/export.csv`}>CSV</a></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </section>
      ))}
      {!sites.length && <p className="meta">No analysed videos yet.</p>}
      <p className="meta">Fish entries can count one fish twice if it leaves and comes back. A dash means that count hasn't been done.</p>
    </div>
  );
}
