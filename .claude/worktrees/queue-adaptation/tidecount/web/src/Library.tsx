import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api, clock, ModelOption, Video } from "./api";

const TONES: Record<string, string> = { "Ready to review": "accent", Analyzing: "muted", Queued: "muted", Failed: "down" };

export function Library() {
  const [videos, setVideos] = useState<Video[]>([]);
  const [models, setModels] = useState<ModelOption[]>([]);
  const [detector, setDetector] = useState("");
  const [site, setSite] = useState("");
  const [path, setPath] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const input = useRef<HTMLInputElement>(null);

  const load = () => api.videos().then(setVideos).catch((e) => setError(e.message));
  useEffect(() => {
    load();
    api.models().then((m) => {
      setModels(m);
      setDetector(m.find((o) => o.default)?.key ?? "");
    });
    const timer = setInterval(load, 2000);
    return () => clearInterval(timer);
  }, []);

  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    setError("");
    try {
      await action();
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const labelOf = (key: string) => models.find((m) => m.key === key)?.label ?? key;
  const usedBy = (v: Video) => {
    const root = v.source_id || v.id;
    return videos.filter((o) => (o.source_id || o.id) === root).map((o) => o.detector);
  };
  const count = (s: string) => videos.filter((v) => v.status === s).length;

  return (
    <div className="stack" style={{ gap: 20 }}>
      <div>
        <h1>Fish Counter</h1>
        <p className="lede">Import video, let AI analyze it, then review only what needs attention.</p>
      </div>

      <div className="panel kpis">
        <div className="kpi"><span className="meta">Ready to review</span><b>{count("Ready to review")}</b></div>
        <div className="kpi"><span className="meta">Analyzing or queued</span><b>{count("Analyzing") + count("Queued")}</b></div>
        <div className="kpi"><span className="meta">Failed</span><b>{count("Failed")}</b></div>
      </div>

      <div className="panel panel-pad">
        <h2>Import video</h2>
        <div className="row" style={{ alignItems: "flex-end" }}>
          <label className="field">Site
            <input value={site} onChange={(e) => setSite(e.target.value)} placeholder="Mahone Bay living shoreline" />
          </label>
          <label className="field">Model
            <select value={detector} onChange={(e) => setDetector(e.target.value)}>
              {models.map((m) => <option key={m.key} value={m.key} disabled={!m.available}>{m.label}{m.available ? "" : " (off)"}</option>)}
            </select>
          </label>
          <input
            ref={input}
            type="file"
            accept="video/*,.mp4,.mov,.mkv,.avi"
            hidden
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) run(() => api.upload(file, site, detector));
              e.target.value = "";
            }}
          />
          <button className="btn primary" disabled={busy} onClick={() => input.current?.click()}>
            {busy ? "Importing…" : "Choose file"}
          </button>
          <span className="meta">or for large files</span>
          <label className="field">File path on this PC
            <input value={path} onChange={(e) => setPath(e.target.value)} placeholder="D:\Surveys\GX010123.MP4" />
          </label>
          <button className="btn tall" disabled={busy || !path.trim()} onClick={() => run(async () => { await api.importPath(path, site, detector); setPath(""); })}>
            Add path
          </button>
        </div>
        {error && <p className="meta" style={{ color: "var(--down)" }}>{error}</p>}
      </div>

      <div className="panel" style={{ overflowX: "auto" }}>
        <table>
          <thead>
            <tr><th>Video</th><th>Model</th><th>Site</th><th className="right">Length</th><th>State</th><th className="right">To review</th><th className="right">Action</th></tr>
          </thead>
          <tbody>
            {videos.map((v) => (
              <tr key={v.id}>
                <td className="num">{v.name}</td>
                <td>{labelOf(v.detector)}</td>
                <td>{v.site || "—"}</td>
                <td className="num right">{v.duration ? clock(v.duration) : "—"}</td>
                <td>
                  <div className="row">
                    <span className={`pill ${TONES[v.status] ?? "muted"}`}>{v.status}</span>
                    {v.status === "Analyzing" && (
                      <>
                        <span className="meta">{v.stage}</span>
                        <span className="bar"><i style={{ width: `${v.progress * 100}%` }} /></span>
                      </>
                    )}
                    {v.error && <span className="meta">{v.error}</span>}
                  </div>
                </td>
                <td className="num right">{v.status === "Ready to review" ? clock(v.to_review ?? 0) : "—"}</td>
                <td className="right">
                  <div className="row" style={{ justifyContent: "flex-end" }}>
                    {v.status === "Ready to review" && (
                      <select
                        className="run-model"
                        aria-label={`Run another model on ${v.name}`}
                        value=""
                        onChange={(e) => run(() => api.reanalyze(v.id, e.target.value))}
                      >
                        <option value="">Run model…</option>
                        {models.filter((m) => m.available && !usedBy(v).includes(m.key)).map((m) => <option key={m.key} value={m.key}>{m.label}</option>)}
                      </select>
                    )}
                    {usedBy(v).length > 1 && <Link className="btn" to={`/videos/${v.id}/compare`}>Compare</Link>}
                    {v.status === "Ready to review" && <Link className="btn" to={`/videos/${v.id}/tracks`}>Tracks</Link>}
                    {v.status === "Ready to review" && <Link className="btn" to={`/videos/${v.id}`}>Review</Link>}
                  </div>
                  {v.status === "Failed" && <button className="btn" onClick={() => run(() => api.retry(v.id))}>Retry</button>}
                </td>
              </tr>
            ))}
            {videos.length === 0 && <tr><td colSpan={7} className="meta">No videos yet. Import one to start.</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  );
}
