import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, clock, ModelOption, Video } from "./api";

type Group = { root: string; runs: Video[] };

/** Where detection models are tried against each other. Day-to-day review never needs this page. */
export function ModelLab() {
  const [videos, setVideos] = useState<Video[]>([]);
  const [models, setModels] = useState<ModelOption[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const load = () => api.videos().then(setVideos).catch((e) => setError(e.message));
  useEffect(() => {
    load();
    api.models().then(setModels).catch(() => {});
    const timer = setInterval(load, 2500);
    return () => clearInterval(timer);
  }, []);

  const groups = useMemo(() => {
    const out: Group[] = [];
    videos.forEach((v) => {
      const root = v.source_id || v.id;
      const group = out.find((g) => g.root === root);
      if (group) group.runs.push(v);
      else out.push({ root, runs: [v] });
    });
    return out;
  }, [videos]);

  const labelOf = (key: string) => models.find((m) => m.key === key)?.label ?? key;

  async function rerun(id: string, detector: string) {
    setBusy(true);
    setError("");
    try {
      await api.reanalyze(id, detector);
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="stack" style={{ gap: 20 }}>
      <div>
        <h1>Model lab</h1>
        <p className="lede">Run a second detection model on a video and compare the two side by side. Reviewing footage doesn't need this page.</p>
      </div>
      {error && <p className="meta" style={{ color: "var(--down)" }}>{error}</p>}

      <section className="panel" style={{ overflowX: "auto" }}>
        <div className="panel-head"><h2>Models on this PC</h2></div>
        <table>
          <thead><tr><th>Model</th><th>State</th><th>Note</th></tr></thead>
          <tbody>
            {models.map((m) => (
              <tr key={m.key}>
                <td style={{ fontWeight: 500 }}>{m.label}{m.default && <span className="pill accent" style={{ marginLeft: 8 }}>Default</span>}</td>
                <td><span className={`pill ${m.available ? "up" : "muted"}`}>{m.available ? "Ready" : "Off"}</span></td>
                <td className="meta">{m.note || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="panel" style={{ overflowX: "auto" }}>
        <div className="panel-head">
          <h2>Videos</h2>
          <p className="meta">Each run keeps its own tracks and review, so a new model never changes work already done.</p>
        </div>
        <table>
          <thead><tr><th>Video</th><th className="right">Length</th><th>Models run</th><th>Run another</th><th className="right">Compare</th></tr></thead>
          <tbody>
            {groups.map((g) => {
              const first = g.runs[g.runs.length - 1];
              const used = g.runs.map((r) => r.detector);
              const spare = models.filter((m) => m.available && !used.includes(m.key));
              const ready = g.runs.filter((r) => r.status === "Ready to review");
              return (
                <tr key={g.root}>
                  <td>
                    <span className="vname">{first.name}</span>
                    <div className="meta">{first.site || "No site set"}</div>
                  </td>
                  <td className="num right">{first.duration ? clock(first.duration) : "—"}</td>
                  <td>
                    <div className="row" style={{ gap: 4 }}>
                      {g.runs.map((r) => (
                        <span key={r.id} className={`pill ${r.status === "Ready to review" ? "muted" : r.status === "Failed" ? "down" : "warn"}`} title={r.error || r.status}>
                          {labelOf(r.detector)}{r.status === "Analyzing" ? ` · ${Math.round(r.progress * 100)}%` : r.status === "Queued" ? " · queued" : r.status === "Failed" ? " · failed" : ""}
                        </span>
                      ))}
                    </div>
                  </td>
                  <td>
                    {ready.length > 0 && spare.length > 0 ? (
                      <select className="run-model" style={{ maxWidth: 220 }} aria-label={`Run another model on ${first.name}`} value="" disabled={busy} onChange={(e) => rerun(ready[0].id, e.target.value)}>
                        <option value="">Choose a model…</option>
                        {spare.map((m) => <option key={m.key} value={m.key}>{m.label}</option>)}
                      </select>
                    ) : <span className="meta">{ready.length ? "Every model has run" : "Waiting for analysis"}</span>}
                  </td>
                  <td className="right">
                    {ready.length > 1
                      ? <Link className="btn go" to={`/videos/${ready[0].id}/compare`}>Compare {ready.length}</Link>
                      : <span className="meta">Needs two runs</span>}
                  </td>
                </tr>
              );
            })}
            {!groups.length && <tr><td colSpan={5} className="meta">No videos yet. Import one from Videos first.</td></tr>}
          </tbody>
        </table>
      </section>
    </div>
  );
}
