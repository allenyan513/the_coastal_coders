import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, clock, Summary, Video } from "./api";
import { countProgress } from "./Library";

type Row = { video: Video; summary: Summary };

/** Every analysed video side by side, grouped by site. One row per video: the run with the most points counted. */
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
      if (!kept || countProgress(r.summary).done > countProgress(kept.summary).done) best.set(root, r);
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
        <p className="lede">The procedure's results, video by video. Only counts a person confirmed are included.</p>
      </div>
      {sites.map(([site, list]) => (
        <section className="panel" key={site}>
          <div className="panel-head"><h2>{site}</h2></div>
          <table className="cards">
            <thead>
              <tr>
                <th>Video</th><th className="right">Length</th><th className="right">Window</th><th className="right">Points counted</th>
                <th className="right">MeanCount</th><th className="right">Invertebrates per point</th><th className="right">Species</th><th>Visibility</th><th />
              </tr>
            </thead>
            <tbody>
              {list.map(({ video: v, summary: s }) => (
                <tr key={v.id}>
                  <td><Link className="vname" to={`/videos/${v.id}/summary`}>{v.name}</Link></td>
                  <td className="num right" data-label="Length">{clock(v.duration)}</td>
                  <td className="num right" data-label="Window">{clock(s.protocol.start)} to {clock(s.protocol.end)}</td>
                  <td className="num right" data-label="Points counted">{s.snapshots.frames_checked} of {s.snapshots.frames_total}</td>
                  <td className="num right" data-label="MeanCount">{s.snapshots.mean_count?.toFixed(2) ?? "—"}</td>
                  <td className="num right" data-label="Invertebrates per point">{s.snapshots.invertebrate_mean?.toFixed(2) ?? "—"}</td>
                  <td className="num right" data-label="Species">{s.species_observed.length}</td>
                  <td data-label="Visibility">{s.protocol.visibility || "—"}</td>
                  <td className="right"><a className="btn" href={`/api/videos/${v.id}/protocol.csv`}>Sheet</a></td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ))}
      {!sites.length && <p className="meta">No analysed videos yet.</p>}
      <p className="meta">A dash means that count hasn't been done.</p>
    </div>
  );
}
