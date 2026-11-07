import { DragEvent, useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, clock, isLocal, ModelOption, Summary, Video } from "./api";
import { Menu } from "./Menu";
import { useUser } from "./session";
import { FilmedOn, SiteList, StationDialog, StationPicker, StationStats } from "./Surveys";
import { season, setFilmedOn, setPlace, setPlaces, suggestStation, useSurveys } from "./surveyStore";

const READY = "Ready to review";
type Group = { root: string; runs: Video[] };

/** Sub-sample points to count, and how many are done. */
export function countProgress(s: Summary) {
  return { done: s.snapshots.frames_done, total: s.snapshots.frames_total };
}

/** Surveys: one tree of sites, transects and stations, with each station's footage under it. */
export function Library() {
  const manager = useUser().role === "manager";
  const data = useSurveys();
  const [videos, setVideos] = useState<Video[]>([]);
  const [summaries, setSummaries] = useState<Record<string, Summary>>({});
  const [models, setModels] = useState<ModelOption[]>([]);
  const [chosen, setChosen] = useState<Record<string, string>>({});
  const [detector, setDetector] = useState("");
  const [pending, setPending] = useState<File | null>(null);
  const [stationId, setStationId] = useState("");
  const [filmed, setFilmed] = useState("");
  const [path, setPath] = useState("");
  const [placing, setPlacing] = useState<{ root: string; name: string } | null>(null);
  const [editing, setEditing] = useState(false);
  const [inboxOpen, setInboxOpen] = useState(false);
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
  /** The run a row shows: the one picked, else the one with the most points counted, else the first imported. */
  const shownRun = (g: Group) =>
    g.runs.find((v) => v.id === chosen[g.root])
    ?? [...g.runs].sort((a, b) => (summaries[b.id] ? countProgress(summaries[b.id]).done : 0) - (summaries[a.id] ? countProgress(summaries[a.id]).done : 0))[0];

  const showImport = importing ?? (videos.length === 0 && !error);

  /** Holds the file until it has a station. Coastal Action's file names pre-fill it, for the person to confirm. */
  const choose = (file: File) => {
    setPending(file);
    setStationId(suggestStation(data, file.name) || stationId);
  };
  const drop = (e: DragEvent) => {
    e.preventDefault();
    setOver(false);
    const file = e.dataTransfer.files[0];
    if (file) choose(file);
  };
  const siteName = () => {
    const transect = data.transects.find((t) => t.id === data.stations.find((s) => s.id === stationId)?.transectId);
    return data.sites.find((s) => s.id === transect?.siteId)?.name ?? "";
  };
  const importTo = (send: (site: string) => Promise<{ id: string }>) => run(async () => {
    const { id } = await send(siteName());
    setPlace(id, stationId);
    if (filmed) setFilmedOn(id, filmed);
    setPending(null);
    setPath("");
  });

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
    const filed = !!data.places[g.root];
    return (
      <div className="vrow" key={g.root}>
        {ready
          ? <video className="thumb" src={`/api/videos/${v.id}/proxy#t=${Math.min(3, v.duration / 2).toFixed(1)}`} preload="metadata" muted playsInline tabIndex={-1} />
          : <span className="thumb" />}
        <div className="stack" style={{ gap: 4, minWidth: 0 }}>
          {ready ? <Link className="vname" to={`/videos/${v.id}/snapshots`}>{v.name}</Link> : <span className="vname">{v.name}</span>}
          <span className="meta">
            {!filed && <><button className="link" onClick={() => setPlacing({ root: g.root, name: v.name })}>Choose station</button>{" · "}</>}
            {filed && !data.filmedOn[g.root] && <><button className="link" onClick={() => setPlacing({ root: g.root, name: v.name })}>Add filmed date</button>{" · "}</>}
            {data.filmedOn[g.root] ? `${season(data.filmedOn[g.root])} · ` : ""}
            {labelOf(v.detector)}
          </span>
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
                <span className={`pill ${finished ? "up" : started ? "warn" : "accent"}`}>{finished ? "Counted" : started ? "Counting" : "Ready to count"}</span>
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
              <Link className={`btn ${finished ? "" : "go"}`} to={finished ? `/videos/${v.id}/summary` : `/videos/${v.id}/snapshots`}>
                {finished ? "Open report" : started ? "Continue" : "Count"}
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
  const importInto = (id: string) => {
    setStationId(id);
    setImporting(true);
    window.scrollTo({ top: 0 });
  };

  return (
    <div className="stack" style={{ gap: 20 }}>
      <div className="pagehead">
        <div>
          <h1>Surveys</h1>
          <p className="lede">{editing ? "Add or change sites, transects and stations. Footage stays where it is." : "What's been filmed and counted at every station."}</p>
        </div>
        <div className="row">
          {manager && <button className="btn tall" onClick={() => setEditing(!editing)}>{editing ? "Done" : "Edit structure"}</button>}
          {!editing && <button className="btn primary" onClick={() => setImporting(!showImport)}>{showImport ? "Close import" : "Import video"}</button>}
        </div>
      </div>

      {showImport && !editing && (
        <div className="panel panel-pad" style={{ gap: 12 }}>
          <div className="row" style={{ alignItems: "stretch", gap: 16 }}>
            <div
              className={`drop ${over ? "over" : ""}`}
              style={{ flex: "2 1 320px" }}
              onDragOver={(e) => { e.preventDefault(); setOver(true); }}
              onDragLeave={() => setOver(false)}
              onDrop={drop}
            >
              <b>{busy ? "Importing…" : pending ? pending.name : <><span className="hide-phone">Drop a video here</span><span className="only-phone">Choose a video</span></>}</b>
              <span className="meta">{pending ? (stationId ? "Check the station, then import." : "Choose its station to import it.") : `MP4, MOV, MKV or AVI. ${isLocal ? "It's copied into this PC's Tideflow folder and nowhere else." : "It's uploaded to the demo server."}`}</span>
              {pending ? (
                <div className="row">
                  <button className="btn" disabled={busy} onClick={() => setPending(null)}>Cancel</button>
                  <button className="btn go" disabled={busy || !stationId} onClick={() => importTo((site) => api.upload(pending, site, detector))}>Import</button>
                </div>
              ) : <button className="btn" disabled={busy} onClick={() => input.current?.click()}>Choose file</button>}
              <input
                ref={input}
                type="file"
                accept="video/*,.mp4,.mov,.mkv,.avi"
                hidden
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) choose(file);
                  e.target.value = "";
                }}
              />
            </div>
            <div className="stack" style={{ flex: "1 1 260px" }}>
              <StationPicker data={data} value={stationId} onChange={setStationId} />
              <FilmedOn value={filmed} onChange={setFilmed} />
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
                      <input value={path} onChange={(e) => { setPath(e.target.value); setStationId(suggestStation(data, e.target.value) || stationId); }} placeholder="D:\Surveys\GX010123.MP4" />
                    </label>
                    <button className="btn" disabled={busy || !path.trim() || !stationId} onClick={() => importTo((site) => api.importPath(path, site, detector))}>
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

      {manager && !editing && unfiled.length > 0 && (
        <section className="panel inbox">
          <div className="inbox-head">
            <p><b>{unfiled.length} {unfiled.length === 1 ? "video needs" : "videos need"} a station</b>{matchCount > 0 && <span className="meta"> · {matchCount} can be filed from {matchCount === 1 ? "its name" : "their names"}</span>}</p>
            <div className="row">
              <button className="btn" onClick={() => setInboxOpen(!inboxOpen)}>{inboxOpen ? "Hide" : "Review"}</button>
              {matchCount > 0 && <button className="btn go" onClick={() => setPlaces(matches)}>File {matchCount} by name</button>}
            </div>
          </div>
          {inboxOpen && unfiled.map(row)}
        </section>
      )}

      <SiteList editing={editing} videosAt={videosAt} statsAt={statsAt} onImport={importInto} />
      {placing && <StationDialog root={placing.root} name={placing.name} onClose={() => setPlacing(null)} />}
    </div>
  );
}
