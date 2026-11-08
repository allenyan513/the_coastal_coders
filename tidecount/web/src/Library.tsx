import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, clock, ModelOption, Summary, Video } from "./api";
import { ImportDialog } from "./ImportDialog";
import { Menu } from "./Menu";
import { useUser } from "./session";
import { SiteList, StationDialog, StationStats } from "./Surveys";
import { Group, SurveySites } from "./SurveySites";
import { season, setPlaces, suggestStation, useSurveys } from "./surveyStore";

const READY = "Ready to review";

/** Sub-sample points to count, and how many are done. */
export function countProgress(s: Summary) {
  return { done: s.snapshots.frames_done, total: s.snapshots.frames_total };
}

/** Footage still to identify, in seconds, and the share already done. Identify comes before Count,
 * since Count offers the species named on Identify. */
export function identifyProgress(s: Summary) {
  const done = s.reviewed + s.could_not_see;
  return { left: s.pending, share: done + s.pending > 0 ? done / (done + s.pending) : 1 };
}

/** Surveys: one tree of sites, transects and stations, with each station's footage under it. */
export function Library() {
  const manager = useUser().role === "manager";
  const data = useSurveys();
  const [videos, setVideos] = useState<Video[]>([]);
  const [summaries, setSummaries] = useState<Record<string, Summary>>({});
  const [models, setModels] = useState<ModelOption[]>([]);
  const [chosen, setChosen] = useState<Record<string, string>>({});
  const [placing, setPlacing] = useState<{ root: string; name: string } | null>(null);
  const [editing, setEditing] = useState(false);
  const [inboxOpen, setInboxOpen] = useState(false);
  const [params] = useSearchParams();
  // The QR page's upload link lands here with ?import, so the dialog opens straight away.
  const [importing, setImporting] = useState<{ station?: string } | null>(params.has("import") ? {} : null);
  const [toast, setToast] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const load = () => api.videos().then((v) => { setVideos(v); setLoaded(true); }).catch((e) => setError(e.message));
  useEffect(() => {
    load();
    api.models().then(setModels);
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
  /** The run a row shows: the one picked, else the one with the most points counted, else the first imported. */
  const shownRun = useCallback((g: Group) =>
    g.runs.find((v) => v.id === chosen[g.root])
    ?? [...g.runs].sort((a, b) => (summaries[b.id] ? countProgress(summaries[b.id]).done : 0) - (summaries[a.id] ? countProgress(summaries[a.id]).done : 0))[0],
  [chosen, summaries]);
  const pointsOf = useCallback((g: Group) => {
    const s = summaries[shownRun(g).id];
    return s ? countProgress(s) : { done: 0, total: 0 };
  }, [summaries, shownRun]);

  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(""), 5000);
    return () => clearTimeout(timer);
  }, [toast]);

  const unfiled = groups.filter((g) => !data.places[g.root]);
  const matches = Object.fromEntries(unfiled.flatMap((g) => {
    const suggested = suggestStation(data, g.runs[0].name);
    return suggested ? [[g.root, suggested] as const] : [];
  }));
  const matchCount = Object.keys(matches).length;

  const row = (g: Group) => {
    const v = shownRun(g);
    const s = summaries[v.id];
    const p = s ? countProgress(s) : null;
    const ready = v.status === READY;
    const started = !!p && p.done > 0;
    const finished = !!p && p.total > 0 && p.done >= p.total;
    // Identify first, unless counting has already started.
    const toIdentify = !!s && !started && !finished && identifyProgress(s).left > 0;
    const work = toIdentify ? `/videos/${v.id}` : `/videos/${v.id}/snapshots`;
    const filed = !!data.places[g.root];
    return (
      <div className="vrow" key={g.root}>
        {ready
          ? <video className="thumb" src={`/api/videos/${v.id}/proxy#t=${Math.min(3, v.duration / 2).toFixed(1)}`} preload="metadata" muted playsInline tabIndex={-1} />
          : <span className="thumb" />}
        <div className="stack" style={{ gap: 4, minWidth: 0 }}>
          {ready ? <Link className="vname" to={work}>{v.name}</Link> : <span className="vname">{v.name}</span>}
          <span className="meta">
            {!filed && <><button className="link" onClick={() => setPlacing({ root: g.root, name: v.name })}>Choose station</button>{" · "}</>}
            {filed && !data.filmedOn[g.root] && <><button className="link" onClick={() => setPlacing({ root: g.root, name: v.name })}>Add filmed date</button>{" · "}</>}
            {data.filmedOn[g.root] ? `${season(data.filmedOn[g.root])} · ` : ""}
            {labelOf(v.detector)}
          </span>
          {g.runs.length > 1 && (
            <label className="meta runs-pick">{g.runs.length} model runs, showing
              <select value={v.id} onChange={(e) => setChosen({ ...chosen, [g.root]: e.target.value })}>
                {g.runs.map((r) => <option key={r.id} value={r.id}>{labelOf(r.detector)}</option>)}
              </select>
            </label>
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
                <span className={`pill ${finished ? "up" : started ? "warn" : "accent"}`}>{finished ? "Counted" : started ? "Counting" : toIdentify ? "To identify" : "Ready to count"}</span>
                {p && <span className="num meta">{p.done} of {p.total} points</span>}
              </div>
              {p && <span className="bar wide"><i className={finished ? "up" : ""} style={{ width: `${(p.done / (p.total || 1)) * 100}%` }} /></span>}
            </>
          )}
        </div>
        <div className="row vactions" style={{ justifyContent: "flex-end", flexWrap: "nowrap" }}>
          {v.status === "Failed" && <button className="btn" disabled={busy} onClick={() => run(() => api.retry(v.id))}>Retry</button>}
          {ready && (
            <>
              <Link className={`btn ${finished ? "" : "go"}`} to={finished ? `/videos/${v.id}/summary` : work}>
                {finished ? "Open report" : started ? "Continue" : toIdentify ? "Identify" : "Count"}
              </Link>
              <Menu label={`More for ${v.name}`}>
                <Link role="menuitem" to={`/videos/${v.id}`}>Review footage</Link>
                <Link role="menuitem" to={`/videos/${v.id}/summary`}>Report</Link>
                <a role="menuitem" href={`/api/videos/${v.id}/protocol.csv`}>Export analysis sheet</a>
                <button role="menuitem" onClick={() => setPlacing({ root: g.root, name: v.name })}>{filed ? "Station and date" : "Choose station"}</button>
              </Menu>
            </>
          )}
        </div>
      </div>
    );
  };

  const groupsAt = (id: string) => groups.filter((g) => data.places[g.root] === id);
  const videosAt = (id: string) => <div className="tree-videos">{groupsAt(id).map(row)}</div>;
  const statsAt = (id: string): StationStats => {
    const here = groupsAt(id).map((g) => summaries[shownRun(g).id]).map((s) => (s ? countProgress(s) : { done: 0, total: 0 }));
    return { videos: here.length, done: here.reduce((n, p) => n + p.done, 0), total: here.reduce((n, p) => n + p.total, 0) };
  };
  /** Starts an import with the station already chosen, from the row that needs footage. */
  const importInto = (id: string) => setImporting({ station: id });

  return (
    <div className="stack" style={{ gap: 20 }}>
      <div className="pagehead">
        <div>
          <h1>Surveys</h1>
          <p className="lede">{editing ? "Add or change sites, transects and stations. Footage stays where it is." : "Pick a site to see its stations, its footage and what needs fixing."}</p>
        </div>
        <div className="row pagehead-actions">
          {manager && <button className="btn tall" onClick={() => setEditing(!editing)}>{editing ? "Done" : "Edit structure"}</button>}
          {!editing && <button className="btn primary" onClick={() => setImporting({})}>Import video</button>}
        </div>
      </div>

      {loaded && videos.length === 0 && !editing && (
        <div className="panel empty-cta">
          <b>No footage yet</b>
          <p className="meta">Import a video and Tideflow scans it for fish, then files it under its station.</p>
          <button className="btn go" onClick={() => setImporting({})}>Import your first video</button>
        </div>
      )}
      {error && <p className="meta" style={{ color: "var(--down)" }}>{error}</p>}

      {manager && !editing && unfiled.length > 0 && (
        <section className="panel inbox">
          <div className="inbox-head">
            <p><b>{unfiled.length} {unfiled.length === 1 ? "video needs" : "videos need"} a station</b>{matchCount > 0 && <span className="meta"> · {matchCount} can be filed from {matchCount === 1 ? "its name" : "their names"}</span>}</p>
            <div className="row">
              <button className="btn" onClick={() => setInboxOpen(!inboxOpen)}>{inboxOpen ? "Hide" : "Review"}</button>
              {matchCount > 0 && <button className="btn go" onClick={() => setPlaces(matches).then(setError)}>File {matchCount} by name</button>}
            </div>
          </div>
          {inboxOpen && unfiled.map(row)}
        </section>
      )}

      {editing
        ? <SiteList editing videosAt={videosAt} statsAt={statsAt} onImport={importInto} />
        : (
          <SurveySites
            groups={groups}
            shown={shownRun}
            points={pointsOf}
            row={row}
            onImport={(station) => setImporting({ station })}
            onPlace={(g) => setPlacing({ root: g.root, name: g.runs[0].name })}
            onRetry={(id) => run(() => api.retry(id))}
          />
        )}
      {placing && <StationDialog root={placing.root} name={placing.name} onClose={() => setPlacing(null)} />}
      {importing && (
        <ImportDialog
          models={models}
          station={importing.station}
          onClose={() => setImporting(null)}
          onImported={(name) => {
            setImporting(null);
            setToast(`Imported ${name}. AI is scanning it now.`);
            load();
          }}
        />
      )}
      {toast && <div className="toast" role="status">{toast} <Link to="/workflow">See progress</Link></div>}
    </div>
  );
}
