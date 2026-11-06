import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { AccuracyRow, api } from "./api";

const share = (part: number, whole: number) => (whole ? `${Math.round((part / whole) * 100)}%` : "—");

/** How well AI finds fish, measured against frames a person counted without seeing AI's dots. */
export function Accuracy() {
  const [rows, setRows] = useState<AccuracyRow[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => { api.accuracy().then((r) => setRows(r.videos)).catch((e) => setError(e.message)); }, []);

  if (error) return <p className="meta">{error}</p>;
  if (!rows) return <p className="meta">Loading…</p>;

  // Runs of one video share labels, so totals take one row per video: the first run listed.
  const seen = new Set<string>();
  const one = rows.filter((r) => !seen.has(r.name + r.site) && seen.add(r.name + r.site));
  const sum = (pick: (r: AccuracyRow) => number) => one.reduce((n, r) => n + pick(r), 0);
  const frames = sum((r) => r.frames_blind);
  const fish = sum((r) => r.fish);
  const found = sum((r) => r.found);
  const assisted = sum((r) => r.frames_assisted);

  return (
    <div className="stack" style={{ gap: 20 }}>
      <div>
        <h1>AI accuracy</h1>
        <p className="lede">Count the fish on a few frames without seeing AI's dots. TideCount then shows how many of your fish AI had found. Frames you count on your own in a video's snapshot count land here too.</p>
      </div>

      <div className="panel kpis">
        <div className="kpi"><span className="meta">Frames you counted blind</span><b>{frames}</b></div>
        <div className="kpi"><span className="meta">Fish you counted</span><b>{fish}</b></div>
        <div className="kpi">
          <span className="meta">AI found</span>
          <b>{fish ? `${found} of ${fish}` : "—"}</b>
          {fish > 0 && <small className="meta num">{share(found, fish)} of your fish</small>}
        </div>
        <div className="kpi"><span className="meta">AI missed</span><b>{fish ? fish - found : "—"}</b></div>
        <div className="kpi">
          <span className="meta">AI boxes with no fish</span>
          <b>{frames ? sum((r) => r.extra_boxes) : "—"}</b>
        </div>
      </div>
      {frames > 0 && frames < 20 && <p className="meta" style={{ color: "var(--warn)" }}>With fewer than 20 frames these numbers are rough. Each frame you add steadies them.</p>}

      <section className="panel">
        <div className="panel-head">
          <h2>Videos</h2>
          <p className="meta">One frame every 30 seconds. A fish counts as found when your dot sits inside an AI box on that frame.</p>
        </div>
        <table className="cards">
          <thead>
            <tr>
              <th>Video</th><th>Detection model</th><th className="right">Frames counted blind</th><th className="right">Fish you counted</th>
              <th className="right">AI found</th><th className="right">AI missed</th><th className="right">Boxes with no fish</th><th />
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const left = r.frames_total - r.frames_blind - r.frames_assisted - r.frames_could_not_see;
              return (
                <tr key={r.id}>
                  <td>
                    <span className="vname">{r.name}</span>
                    <div className="meta">{r.site || "No site set"}</div>
                  </td>
                  <td className="meta" data-label="Detection model">{r.model}</td>
                  <td className="num right" data-label="Frames counted blind">{r.frames_blind} of {r.frames_total}</td>
                  <td className="num right" data-label="Fish you counted">{r.frames_blind ? r.fish : "—"}</td>
                  <td className="num right" data-label="AI found">{r.fish ? `${r.found} · ${share(r.found, r.fish)}` : "—"}</td>
                  <td className="num right" data-label="AI missed">{r.fish ? r.missed : "—"}</td>
                  <td className="num right" data-label="Boxes with no fish">{r.frames_blind ? r.extra_boxes : "—"}</td>
                  <td className="right">
                    <div className="row" style={{ justifyContent: "flex-end", flexWrap: "nowrap" }}>
                      {r.frames_blind > 0 && <a className="btn" href={`/api/videos/${r.id}/labels.json`} title="Your blind counts, in the form the benchmark reads">Labels</a>}
                      <Link className={`btn ${left > 0 ? "go" : ""}`} to={`/videos/${r.id}/snapshots?mode=own&from=accuracy`}>{left > 0 ? "Count frames" : "Open frames"}</Link>
                    </div>
                  </td>
                </tr>
              );
            })}
            {!rows.length && <tr><td colSpan={8} className="meta">No analysed videos yet.</td></tr>}
          </tbody>
        </table>
      </section>

      <div className="stack" style={{ gap: 6 }}>
        {assisted > 0 && <p className="meta">{assisted} {assisted === 1 ? "frame was" : "frames were"} counted with AI's dots showing and {assisted === 1 ? "is" : "are"} left out. Seeing AI's dots first makes AI look better than it is.</p>}
        <p className="meta">Two models run on one video share your counts, so each row scores its own model on the same frames.</p>
        <p className="meta"><Link to="/models">Compare detection models</Link>, for people tuning TideCount.</p>
      </div>
    </div>
  );
}
