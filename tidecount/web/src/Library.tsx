import { DragEvent, useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, clock, isLocal, ModelOption, Summary, Video } from "./api";

const READY = "Ready to review";
type Group = { root: string; runs: Video[] };

/** Footage a person has to look at, and how much of it is done. */
export function reviewProgress(s: Summary) {
  const done = s.reviewed + s.could_not_see;
  return { done, total: done + s.pending };
}

function Menu({ label, children }: { label: string; children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (e: Event) => {
      if (e instanceof KeyboardEvent ? e.key === "Escape" : !box.current?.contains(e.target as Node)) setOpen(false);
    };
    window.addEventListener("mousedown", close);
    window.addEventListener("keydown", close);
    return () => {
      window.removeEventListener("mousedown", close);
      window.removeEventListener("keydown", close);
    };
  }, [open]);
  return (
    <div className="menu" ref={box}>
      <button className="btn" aria-label={label} aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen(!open)}>⋯</button>
      {open && <div className="menu-list" role="menu" onClick={() => setOpen(false)}>{children}</div>}
    </div>
  );
}

export function Library() {
  const [videos, setVideos] = useState<Video[]>([]);
  const [summaries, setSummaries] = useState<Record<string, Summary>>({});
  const [models, setModels] = useState<ModelOption[]>([]);
  const [chosen, setChosen] = useState<Record<string, string>>({});
  const [detector, setDetector] = useState("");
  const [site, setSite] = useState("");
  const [path, setPath] = useState("");
  const [params] = useSearchParams();
  const [importing, setImporting] = useState<boolean | null>(params.has("import") ? true : null);
  const [over, setOver] = useState(false);
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

  const readyIds = videos.filter((v) => v.status === READY).map((v) => v.id).join(",");
  useEffect(() => {
    if (!readyIds) return;
    Promise.all(readyIds.split(",").map(async (id) => [id, await api.summary(id)] as const))
      .then((all) => setSummaries(Object.fromEntries(all)))
      .catch(() => {});
  }, [readyIds]);

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
  /** The run a row shows: the one picked, else the one with the most review done, else the first imported. */
  const shownRun = (g: Group) =>
    g.runs.find((v) => v.id === chosen[g.root])
    ?? [...g.runs].sort((a, b) => (summaries[b.id] ? reviewProgress(summaries[b.id]).done : 0) - (summaries[a.id] ? reviewProgress(summaries[a.id]).done : 0))[0];

  const shown = groups.map(shownRun);
  const sum = (pick: (s: Summary) => number) => shown.reduce((n, v) => n + (summaries[v.id] ? pick(summaries[v.id]) : 0), 0);
  const working = videos.filter((v) => v.status === "Analyzing" || v.status === "Queued").length;
  const failed = videos.filter((v) => v.status === "Failed").length;
  const showImport = importing ?? (videos.length === 0 && !error);

  const drop = (e: DragEvent) => {
    e.preventDefault();
    setOver(false);
    const file = e.dataTransfer.files[0];
    if (file) run(() => api.upload(file, site, detector));
  };

  return (
    <div className="stack" style={{ gap: 20 }}>
      <div className="pagehead">
        <div>
          <h1>Videos</h1>
          <p className="lede">Import a video, let AI find the footage worth watching, then review, count and export.</p>
        </div>
        <button className="btn primary" onClick={() => setImporting(!showImport)}>{showImport ? "Close import" : "Import video"}</button>
      </div>

      {showImport && (
        <div className="panel panel-pad" style={{ gap: 12 }}>
          <div className="row" style={{ alignItems: "stretch", gap: 16 }}>
            <div
              className={`drop ${over ? "over" : ""}`}
              style={{ flex: "2 1 320px" }}
              onDragOver={(e) => { e.preventDefault(); setOver(true); }}
              onDragLeave={() => setOver(false)}
              onDrop={drop}
            >
              <b>{busy ? "Importing…" : <><span className="hide-phone">Drop a video here</span><span className="only-phone">Choose a video</span></>}</b>
              <span className="meta">MP4, MOV, MKV or AVI. {isLocal ? "It's copied into this PC's TideCount folder and nowhere else." : "It's uploaded to the demo server."}</span>
              <button className="btn" disabled={busy} onClick={() => input.current?.click()}>Choose file</button>
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
            </div>
            <div className="stack" style={{ flex: "1 1 260px" }}>
              <label className="field">Site, used to group reports
                <input value={site} onChange={(e) => setSite(e.target.value)} placeholder="Mahone Bay living shoreline" />
              </label>
              <details className="advanced">
                <summary>Advanced: model and large files</summary>
                <div className="stack">
                  <label className="field">Detection model
                    <select value={detector} onChange={(e) => setDetector(e.target.value)}>
                      {models.map((m) => <option key={m.key} value={m.key} disabled={!m.available}>{m.label}{m.available ? "" : " (off)"}</option>)}
                    </select>
                  </label>
                  <div className="stack hide-phone">
                    <label className="field">File path on this PC, for files too large to upload
                      <input value={path} onChange={(e) => setPath(e.target.value)} placeholder="D:\Surveys\GX010123.MP4" />
                    </label>
                    <button className="btn" disabled={busy || !path.trim()} onClick={() => run(async () => { await api.importPath(path, site, detector); setPath(""); })}>
                      Import from path
                    </button>
                  </div>
                </div>
              </details>
            </div>
          </div>
        </div>
      )}
      {error && <p className="meta" style={{ color: "var(--down)" }}>{error}</p>}

      <div className="panel kpis">
        <div className="kpi"><span className="meta">Videos</span><b>{groups.length}</b></div>
        <div className="kpi"><span className="meta">Footage imported</span><b>{clock(shown.reduce((n, v) => n + v.duration, 0))}</b></div>
        <div className="kpi"><span className="meta">Left to review</span><b>{clock(sum((s) => s.pending))}</b></div>
        <div className="kpi"><span className="meta">Skipped by AI</span><b>{clock(sum((s) => s.skipped))}</b></div>
        {working > 0 && <div className="kpi"><span className="meta">Analyzing or queued</span><b>{working}</b></div>}
        {failed > 0 && <div className="kpi"><span className="meta">Failed</span><b>{failed}</b></div>}
      </div>

      <div className="panel">
        <div className="vcols">
          <span /><span>Video</span><span className="right hide-narrow">Length</span><span className="hide-narrow">Progress</span><span />
        </div>
        {groups.map((g) => {
          const v = shownRun(g);
          const s = summaries[v.id];
          const p = s ? reviewProgress(s) : null;
          const ready = v.status === READY;
          const started = !!p && p.done > 0;
          const finished = !!p && p.total > 0 && p.done >= p.total;
          return (
            <div className="vrow" key={g.root}>
              {ready
                ? <video className="thumb" src={`/api/videos/${v.id}/proxy#t=${Math.min(3, v.duration / 2).toFixed(1)}`} preload="metadata" muted playsInline tabIndex={-1} />
                : <span className="thumb" />}
              <div className="stack" style={{ gap: 4, minWidth: 0 }}>
                {ready ? <Link className="vname" to={`/videos/${v.id}`}>{v.name}</Link> : <span className="vname">{v.name}</span>}
                <span className="meta">{v.site || "No site set"}{g.runs.length === 1 ? ` · ${labelOf(v.detector)}` : ""}</span>
                {g.runs.length > 1 && (
                  <div className="row" style={{ gap: 4 }}>
                    {g.runs.map((r) => (
                      <button key={r.id} className="chip" style={{ height: 26 }} aria-pressed={r.id === v.id} onClick={() => setChosen({ ...chosen, [g.root]: r.id })}>
                        {labelOf(r.detector)}
                      </button>
                    ))}
                  </div>
                )}
              </div>
              <span className="num right hide-narrow">{v.duration ? clock(v.duration) : "—"}</span>
              <div className="stack vprogress" style={{ gap: 6 }}>
                {!ready && (
                  <div className="row">
                    <span className={`pill ${v.status === "Failed" ? "down" : "muted"}`}>{v.status}</span>
                    {v.status === "Analyzing" && <span className="meta">{v.stage} · {Math.round(v.progress * 100)}%</span>}
                    {v.error && <span className="meta">{v.error}</span>}
                  </div>
                )}
                {v.status === "Analyzing" && <span className="bar wide"><i style={{ width: `${v.progress * 100}%` }} /></span>}
                {ready && (
                  <>
                    <div className="row">
                      <span className={`pill ${finished ? "up" : started ? "warn" : "accent"}`}>{finished ? "Reviewed" : started ? "In review" : READY}</span>
                      {p && <span className="num meta">{clock(p.done)} of {clock(p.total)} watched</span>}
                    </div>
                    {p && <span className="bar wide"><i className={finished ? "up" : ""} style={{ width: `${(p.done / (p.total || 1)) * 100}%` }} /></span>}
                  </>
                )}
              </div>
              <div className="row vactions" style={{ justifyContent: "flex-end", flexWrap: "nowrap" }}>
                {v.status === "Failed" && <button className="btn" disabled={busy} onClick={() => run(() => api.retry(v.id))}>Retry</button>}
                {ready && (
                  <>
                    <Link className={`btn ${finished ? "" : "go"}`} to={finished ? `/videos/${v.id}/summary` : `/videos/${v.id}`}>
                      {finished ? "Open report" : started ? "Continue" : "Review"}
                    </Link>
                    <Menu label={`More for ${v.name}`}>
                      <Link role="menuitem" to={`/videos/${v.id}/tracks`}>All tracks</Link>
                      <Link role="menuitem" to={`/videos/${v.id}/snapshots`}>Snapshot count</Link>
                      <Link role="menuitem" to={`/videos/${v.id}/summary`}>Report</Link>
                      <a role="menuitem" href={`/api/videos/${v.id}/export.csv`}>Export CSV</a>
                    </Menu>
                  </>
                )}
              </div>
            </div>
          );
        })}
        {groups.length === 0 && <p className="meta" style={{ padding: 16 }}>No videos yet. Import one to start.</p>}
      </div>
    </div>
  );
}
