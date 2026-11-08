import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api, clock, Dot, FrameRecord, snapshotApi, SnapshotFrame, SnapshotList, SnapshotRow, SnapshotStatus, SpeciesRow } from "./api";
import { DotStage } from "./Dots";
import { Magnifier } from "./Magnifier";
import { PicturePanel, pictureFilter, SharpenFilter, usePicture } from "./Picture";
import { useUser } from "./session";
import { KeyGroup, Shortcuts } from "./Shortcuts";
import { UNIDENTIFIED } from "./trackHelpers";
import { colorOf, isNonFish, loadSpecies, NON_FISH, saveSpecies, SpeciesDot, SpeciesStore, tally, UNIDENTIFIED_LABEL, withSpecies } from "./speciesTally";
import { VideoHeader } from "./VideoHeader";

const KEYS: KeyGroup[] = [
  { title: "This frame", keys: [["N", "Save and go to the next"], ["U", "Could not see"], ["Z", "Undo the last dot"]] },
  { title: "Species", keys: [["1", "Count unidentified fish"], ["2 – 9", "Count the species with that number"]] },
  { title: "Move", keys: [["← →", "Previous or next point, without saving"]] },
  { title: "View", keys: [["D", "Show or hide all dots"], ["M", "Zoom: a magnifying glass over the frame"], ["G", "Show or hide grid totals"], ["Space", "Play the seconds around the frame"], ["R", "Change the clip's speed"]] },
];
const CLIP_RATES = [0.25, 0.5, 1];
const COUNT_REACH_S = 1; // a fish that shows up this close to the frame may count, in the procedure
const EMPTY_RECORD: FrameRecord = { invertebrates: 0, species: [], visibility: "", comment: "" };

const LABELS = {
  "": { text: "Not done", tone: "muted" },
  checked: { text: "Checked", tone: "up" },
  could_not_see: { text: "Could not see", tone: "warn" },
};

/** The next frame of the same kind nobody has done, in list order, wrapping round to the start.
 * Peak frames are extra, so finishing the sub-sample points leads to the report, not to them. */
const nextOpen = (frames: SnapshotRow[], after: number) => {
  const kind = frames.find((f) => f.id === after)?.kind;
  const open = (f: SnapshotRow) => !f.status && f.id !== after && f.kind === kind;
  return frames.slice(frames.findIndex((f) => f.id === after) + 1).find(open) ?? frames.find(open) ?? null;
};


export function Snapshots() {
  const { id = "" } = useParams();
  const user = useUser();
  const navigate = useNavigate();
  // Counting starts from AI's dots. Only the AI accuracy page asks for a blind count (?mode=own):
  // AI's dots never load, so the counts can score the AI, and frames come in a fixed random order,
  // so stopping early still covers the whole video.
  const [params] = useSearchParams();
  const mode = params.get("mode") === "own" ? "own" : "ai";
  const blind = mode === "own";
  const fromAccuracy = params.get("from") === "accuracy";
  const askedFrame = Number(params.get("frame")) || null; // the report links straight to a peak frame
  const clip = useRef<HTMLVideoElement>(null);
  const [list, setList] = useState<SnapshotList | null>(null);
  const [currentId, setCurrentId] = useState<number | null>(null);
  const [frame, setFrame] = useState<SnapshotFrame | null>(null);
  const [dots, setDots] = useState<SpeciesDot[]>([]);
  // Species per dot, a front-end trial kept in this browser. "" counts unidentified fish.
  const [store, setStore] = useState<SpeciesStore>(() => loadSpecies(id));
  const [active, setActive] = useState("");
  const [adding, setAdding] = useState<string | null>(null);
  const [speciesList, setSpeciesList] = useState<SpeciesRow[]>([]);
  const [image, setImage] = useState<"loading" | "ready" | "failed">("loading");
  const [showDots, setShowDots] = useState(true); // only out of the way for a look: hidden dots still count
  const [picture, setPicture] = usePicture(); // the same look as on Identify
  const [original, setOriginal] = useState(false);
  const [zoom, setZoom] = useState(false); // a magnifying glass that follows the pointer over the frame
  const [showGrid, setShowGrid] = useState(true);
  const [playing, setPlaying] = useState(false);
  const [clipRate, setClipRate] = useState(CLIP_RATES[0]);
  const [clipAt, setClipAt] = useState<number | null>(null); // seconds from the frame while its clip plays
  const [record, setRecord] = useState<FrameRecord>(EMPTY_RECORD);
  const [error, setError] = useState("");
  const [toast, setToast] = useState("");
  const drafts = useRef(new Map<number, SpeciesDot[]>());
  const undoStack = useRef<SpeciesDot[][]>([]);
  const saving = useRef(false);

  const flash = (msg: string) => {
    setToast(msg);
    setTimeout(() => setToast(""), 2400);
  };

  const load = () => snapshotApi.list(id).then((all) => {
    // Count follows the protocol: the sub-sample points, one every 60 s. AI's peak frames only show
    // when the report links straight to one.
    const order = blind ? (a: SnapshotRow, b: SnapshotRow) => a.rank - b.rank : (a: SnapshotRow, b: SnapshotRow) => a.t - b.t;
    const kept = all.frames.filter((f) => f.kind === "snapshot" || f.id === askedFrame);
    const l = { ...all, frames: kept.sort(order) };
    setList(l);
    // Pick up at the first point nobody has counted, or the first point when they all are.
    const points = l.frames.filter((f) => f.kind === "snapshot");
    setCurrentId(askedFrame ?? (points.find((f) => !f.status) ?? points[0] ?? l.frames[0])?.id ?? null);
  }).catch((e) => setError(e.message));

  useEffect(() => {
    load();
    drafts.current.clear(); // unsaved dots from the other way of counting don't carry over
    api.event(id, "snapshot_open");
  }, [id, mode]);

  // The species to count start as the ones named on the Identify tab.
  useEffect(() => {
    const s = loadSpecies(id);
    setStore(s);
    setActive("");
    api.species().then(setSpeciesList).catch(() => setSpeciesList([]));
    if (s.palette.length) return;
    api.tracks(id).then((tracks) => {
      const named = [...new Set(tracks
        .filter((t) => (t.state === "Confirmed" || t.state === "Corrected") && t.decided_species && t.decided_species !== UNIDENTIFIED)
        .map((t) => t.decided_species as string))];
      if (named.length) updateStore({ ...s, palette: named.slice(0, 8) });
    }).catch(() => {});
  }, [id]);

  const updateStore = (next: SpeciesStore) => {
    setStore(next);
    saveSpecies(id, next);
  };
  /** A species' everyday name when the species list knows it. */
  const nameOf = (species: string) => (species ? speciesList.find((r) => r.species === species)?.common || species : UNIDENTIFIED_LABEL);
  const addSpecies = (raw: string) => {
    const typed = raw.trim();
    setAdding(null);
    if (!typed) return;
    const known = speciesList.find((r) => r.common.toLowerCase() === typed.toLowerCase() || r.species.toLowerCase() === typed.toLowerCase());
    const species = known?.species ?? NON_FISH.find((n) => n.toLowerCase() === typed.toLowerCase()) ?? typed;
    if (!store.palette.includes(species)) updateStore({ ...store, palette: [...store.palette, species] });
    setActive(species);
  };

  useEffect(() => {
    if (currentId === null) return;
    let stale = false;
    setFrame(null);
    setImage("loading");
    setPlaying(false);
    setClipAt(null);
    undoStack.current = [];
    snapshotApi.frame(currentId, blind).then((f) => {
      if (stale) return;
      setFrame(f);
      setDots(drafts.current.get(f.id) ?? withSpecies(f.dots, loadSpecies(id).frames[f.id]));
      setRecord({ invertebrates: f.invertebrates ?? 0, species: f.species, visibility: f.visibility, comment: f.comment });
    }).catch((e) => flash(e.message));
    return () => { stale = true; };
  }, [currentId, mode]);

  useEffect(() => {
    const next = list && frame && nextOpen(list.frames, frame.id);
    if (next) new Image().src = snapshotApi.image(next.id);
  }, [frame?.id]);

  // A blind count never shows AI's dots, so they never count.
  const shown = useMemo(() => (blind ? dots.filter((d) => d.source === "user") : dots), [dots, blind]);
  const hidden = dots.length - shown.length;

  const change = (next: SpeciesDot[]) => {
    undoStack.current.push(dots);
    setDots(next);
    if (currentId !== null) drafts.current.set(currentId, next);
  };
  const undo = () => {
    const last = undoStack.current.pop();
    if (!last) return flash("Nothing to undo");
    setDots(last);
    if (currentId !== null) drafts.current.set(currentId, last);
  };

  const stopClip = () => {
    clip.current?.pause();
    setPlaying(false);
    setClipAt(null);
  };
  const playClip = () => {
    const el = clip.current;
    if (!el || !frame) return;
    if (playing) return stopClip();
    el.currentTime = 0;
    el.playbackRate = clipRate; // loading a clip resets this, so it's set on every play
    setPlaying(true);
    el.play().catch(() => setPlaying(false));
  };
  const changeClipRate = (rate: number) => {
    setClipRate(rate);
    if (clip.current) clip.current.playbackRate = rate;
  };

  const save = async (status: SnapshotStatus) => {
    if (!list || !frame || frame.id !== currentId || saving.current) return;
    if (status === "checked" ? image !== "ready" : image === "loading") return;
    saving.current = true;
    const kept = status === "checked" ? shown : [];
    const fish = kept.filter((d) => !isNonFish(d.species));
    const others = kept.length - fish.length;
    try {
      const plain: Dot[] = fish.map(({ x, y, source }) => ({ x, y, source }));
      const sent = others > 0 ? { ...record, invertebrates: others } : record;
      const { stats } = await snapshotApi.save(frame.id, status, plain, hidden > 0, blind, sent, user.name);
      drafts.current.delete(frame.id);
      const tags = kept.filter((d) => d.species).map((d) => ({ x: d.x, y: d.y, species: d.species as string }));
      updateStore({ ...store, frames: { ...store.frames, [frame.id]: tags } });
      const frames = list.frames.map((f) => (f.id === frame.id ? { ...f, status, total: status === "checked" ? fish.length : null } : f));
      setList({ ...list, frames, stats });
      setFrame({ ...frame, status }); // the card shows the saved state when there's nowhere left to go
      const next = nextOpen(frames, frame.id);
      if (next && !askedFrame) setCurrentId(next.id);
      else if (askedFrame || fromAccuracy) navigate(fromAccuracy ? "/accuracy" : `/videos/${id}/summary`);
      else flash(status === "checked" ? `Saved ${fish.length} fish` : "Saved as could not see"); // the done banner takes it from here
    } catch (e) {
      flash((e as Error).message);
    } finally {
      saving.current = false;
    }
  };

  /** Move to the frame before or after this one in the strip, without saving. */
  const step = (dir: 1 | -1) => {
    if (!list) return;
    const i = list.frames.findIndex((f) => f.id === currentId) + dir;
    if (i >= 0 && i < list.frames.length) setCurrentId(list.frames[i].id);
    else flash(dir < 0 ? "This is the first frame" : "This is the last frame");
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.repeat || e.metaKey || e.ctrlKey || e.altKey) return;
      if ((e.target as HTMLElement).closest("input, textarea, select")) return; // typing a note isn't a shortcut
      const key = e.key.toLowerCase();
      if (key === " ") { e.preventDefault(); playClip(); }
      else if (key === "n") save("checked");
      else if (key === "u") save("could_not_see");
      else if (key === "arrowleft" || key === "b") step(-1);
      else if (key === "arrowright") step(1);
      else if (key === "z") undo();
      else if (key === "d") setShowDots((v) => !v);
      else if (key === "m") setZoom((v) => !v);
      else if (key === "g") setShowGrid((v) => !v);
      else if (/^[1-9]$/.test(key)) {
        const pick = ["", ...store.palette][Number(key) - 1];
        if (pick !== undefined) setActive(pick);
      }
      else if (key === "r") changeClipRate(CLIP_RATES[(CLIP_RATES.indexOf(clipRate) + 1) % CLIP_RATES.length]);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  if (error) return <p className="meta">{error}</p>;
  if (!list) return <p className="meta">Loading…</p>;

  const { video, stats, protocol } = list;
  const allCounted = stats.frames_total > 0 && stats.frames_done >= stats.frames_total;
  const header = (
    <VideoHeader
      id={id}
      step="snapshots"
      snapshots={{ done: stats.frames_done, total: stats.frames_total }}
      from={fromAccuracy ? { to: "/accuracy", label: "AI accuracy" } : undefined}
      actions={
        <div className="count-top">
          <div className={`count-progress ${allCounted ? "done" : ""}`}>
            <span className="num">{allCounted ? "✓ " : ""}{stats.frames_done} of {stats.frames_total} points counted</span>
            <div className="bar"><i className={allCounted ? "up" : ""} style={{ width: `${(stats.frames_done / (stats.frames_total || 1)) * 100}%` }} /></div>
          </div>
          {allCounted && !blind && <Link className="btn go" to={`/videos/${id}/summary`}>See the report</Link>}
          <Shortcuts groups={KEYS} />
        </div>
      }
    />
  );
  if (!list.frames.length) {
    return <div className="stack">{header}<p className="meta">No frames to check: this clip is too short for a sub-sample point and AI saw no fish in it.</p></div>;
  }
  const points = list.frames.filter((f) => f.kind === "snapshot");
  const isPeak = frame?.kind === "peak";
  const pointNo = points.findIndex((f) => f.id === currentId) + 1;
  const label = frame ? LABELS[frame.status] : null;
  const counts = tally(shown, store.palette);
  const fishOnFrame = shown.filter((d) => !isNonFish(d.species)).length;
  const countOf = (species: string) => counts.find((c) => c.species === species)?.n ?? 0;
  const dotColor = (d: SpeciesDot) => (d.species ? colorOf(store.palette, d.species) : undefined);
  /** Click a dot: give it the species being counted, or remove it when it has that species already. */
  const clickDot = (dot: SpeciesDot) => {
    if ((dot.species ?? "") !== active) change(dots.map((d) => (d === dot ? { ...d, species: active || undefined } : d)));
    else change(dots.filter((d) => d !== dot));
  };
  const at = list.frames.findIndex((f) => f.id === currentId);

  return (
    <div className="stack count-page">
      {header}
      <SharpenFilter id="count-sharpen" amount={picture.sharpness} />
      <div className="split count-split" style={{ "--ratio": (video.width || 16) / (video.height || 9) } as React.CSSProperties}>
        <div className="count-view" style={{ "--pic": original ? "none" : pictureFilter(picture, "count-sharpen") } as React.CSSProperties}>
          <PicturePanel
            value={picture}
            onChange={setPicture}
            onCompare={setOriginal}
            top={
              <button className={`btn zoom-btn ${zoom ? "on" : ""}`} aria-pressed={zoom} onClick={() => setZoom(!zoom)} title="Magnify where you point (M)">
                <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden><circle cx="10.5" cy="10.5" r="6.5" fill="none" stroke="currentColor" strokeWidth="2.2" /><path d="M15.5 15.5 21 21" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" /></svg>
                {zoom ? "Zoom on" : "Zoom"}<kbd>M</kbd>
              </button>
            }
          >
            <label className="switch">
              <input type="checkbox" checked={showDots} onChange={() => setShowDots(!showDots)} />
              <span>Dots</span><kbd className="switch-key">D</kbd>
            </label>
            <label className="switch">
              <input type="checkbox" checked={showGrid} onChange={() => setShowGrid(!showGrid)} />
              <span>Grid totals</span><kbd className="switch-key">G</kbd>
            </label>
          </PicturePanel>
          <button className="count-nav" disabled={at <= 0} onClick={() => step(-1)} aria-label="Previous point" title="Previous point (←)">‹</button>
          <div className={`count-col ${zoom ? "zooming" : ""}`}>
            <DotStage
              key={currentId}
              src={snapshotApi.image(currentId ?? 0)}
              dots={shown}
              showDots={showDots && !playing}
              showGrid={showGrid && !playing}
              aspect={`${video.width || 16} / ${video.height || 9}`}
              onAdd={(x, y) => (playing ? stopClip() : change([...dots, { x, y, source: "user", species: active || undefined }]))}
              onRemove={(dot) => clickDot(dot as SpeciesDot)}
              colorOf={(d) => dotColor(d as SpeciesDot)}
              labelOf={(d) => nameOf((d as SpeciesDot).species ?? "")}
              onLoad={() => setImage("ready")}
              onError={() => setImage("failed")}
            >
              <video
                ref={clip}
                className="clip"
                src={frame ? snapshotApi.clip(frame.id) : undefined}
                muted
                playsInline
                preload="auto"
                style={{ display: playing ? "block" : "none" }}
                onTimeUpdate={(e) => { if (frame) setClipAt(Math.max(0, frame.t - protocol.context_s) + e.currentTarget.currentTime - frame.t); }}
                onEnded={stopClip}
                onError={() => { setPlaying(false); flash("This clip can't be played."); }}
              />
              {image === "failed" && <span className="stage-note">This frame can't be read. Press U.</span>}
              {zoom && !playing && image === "ready" && (
                <Magnifier
                  src={snapshotApi.image(currentId ?? 0)}
                  dots={showDots ? shown.map((d) => ({ x: d.x, y: d.y, className: `dot ${d.source}`, color: dotColor(d) })) : []}
                />
              )}
            </DotStage>

            {/* Under the frame, like a player's time bar. Room for more tools later. */}
            <div className="panel count-bar">
              <button className={`btn ${playing ? "" : "go"} count-play`} onClick={playClip}>
                {playing ? "■ Stop" : `▶ Play ±${protocol.context_s} s`}
              </button>
              <div className="row count-speed" role="group" aria-label="Clip speed">
                {CLIP_RATES.map((r) => <button key={r} className="chip" aria-pressed={clipRate === r} onClick={() => changeClipRate(r)}>{r}×</button>)}
              </div>
              <span className="count-time num">
                {frame ? `${clock(frame.t)} / ${clock(video.duration)}` : "…"}
                {playing && clipAt !== null && (
                  <small className={Math.abs(clipAt) <= COUNT_REACH_S ? "in" : ""}>
                    {` ${clipAt >= 0 ? "+" : "−"}${Math.abs(clipAt).toFixed(1)} s · ${Math.abs(clipAt) <= COUNT_REACH_S ? "counting second" : "context only"}`}
                  </small>
                )}
              </span>
              <div className="count-species" role="radiogroup" aria-label="Species to count">
                <span className="count-species-label">Counting</span>
                {["", ...store.palette].map((sp, i) => (
                  <button
                    key={sp || "unidentified"}
                    role="radio"
                    aria-checked={active === sp}
                    className="species-pick"
                    style={{ "--sp": colorOf(store.palette, sp) } as React.CSSProperties}
                    onClick={() => setActive(sp)}
                    title={`Count ${nameOf(sp)}${i < 9 ? ` (${i + 1})` : ""}`}
                  >
                    <i aria-hidden />
                    <span className="species-pick-name">{nameOf(sp)}</span>
                    <b className="num">{countOf(sp)}</b>
                    {i < 9 && <kbd>{i + 1}</kbd>}
                  </button>
                ))}
                {adding === null ? (
                  <button className="species-pick add" onClick={() => setAdding("")}>+ Add species</button>
                ) : (
                  <form className="species-add" onSubmit={(e) => { e.preventDefault(); addSpecies(adding); }}>
                    <input
                      autoFocus
                      list="count-species-names"
                      placeholder="Species name"
                      value={adding}
                      onChange={(e) => setAdding(e.target.value)}
                      onKeyDown={(e) => { if (e.key === "Escape") setAdding(null); }}
                      onBlur={() => addSpecies(adding)}
                    />
                    <datalist id="count-species-names">
                      {speciesList.map((r) => <option key={r.species} value={r.common || r.species} />)}
                      {NON_FISH.map((n) => <option key={n} value={n}>Non-fish</option>)}
                    </datalist>
                  </form>
                )}
              </div>
            </div>
          </div>
          <button className="count-nav" disabled={at < 0 || at >= list.frames.length - 1} onClick={() => step(1)} aria-label="Next point" title="Next point (→)">›</button>
        </div>

        <aside className="count-side">
          <div className="panel count-card">
            <div className="row" style={{ justifyContent: "space-between" }}>
              <b className="count-where">
                {isPeak ? "Busiest moment" : `Point ${pointNo} of ${points.length}`}
                <span className="meta num"> · {frame ? clock(frame.t) : "…"}</span>
              </b>
              {label && <span className={`pill ${label.tone}`}>{label.text}</span>}
            </div>
            <div className="count-total">
              <span className="num">{fishOnFrame}</span>
              <small>fish on this frame{shown.length > fishOnFrame ? ` + ${shown.length - fishOnFrame} non-fish` : ""}</small>
            </div>
            <p className="meta count-hint">
              {isPeak ? "AI saw many fish here, away from the points. It feeds MaxN, never MeanCount. " : ""}
              Pick a species under the frame, then click a fish. Click a dot to give it that species, and again to remove it.
              {!showDots ? " Dots are hidden but still count. Press D to show them." : ""}
              {blind && frame?.ai_shown && frame.status !== "checked" ? " This frame showed AI's dots earlier, so it won't measure AI." : ""}
            </p>
            <button className="btn primary count-save" disabled={image !== "ready" || !frame} onClick={() => save("checked")}>
              {nextOpen(list.frames, currentId ?? 0) ? "Save and next" : "Save"}<kbd>N</kbd>
            </button>
          </div>
          <div className="species-tally" aria-label="Fish on this frame by species">
            {counts.map((c) => (
              <button
                key={c.species || "unidentified"}
                className="species-box"
                aria-pressed={active === c.species}
                style={{ "--sp": colorOf(store.palette, c.species) } as React.CSSProperties}
                onClick={() => setActive(c.species)}
                title={`Count ${nameOf(c.species)}`}
              >
                <b className="num">{c.n}</b>
                <span>{nameOf(c.species)}</span>
              </button>
            ))}
          </div>

        </aside>
      </div>
      {toast && <div className="toast" role="status">{toast}</div>}
    </div>
  );
}
