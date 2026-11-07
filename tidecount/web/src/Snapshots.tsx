import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api, clock, Dot, FrameRecord, snapshotApi, SnapshotFrame, SnapshotList, SnapshotRow, SnapshotStatus, SpeciesRow } from "./api";
import { DotStage } from "./Dots";
import { KeyGroup, Shortcuts } from "./Shortcuts";
import { VideoHeader } from "./VideoHeader";

const KEYS: KeyGroup[] = [
  { title: "This frame", keys: [["N", "Save and go to the next"], ["U", "Could not see"], ["B", "Back one frame"], ["Z", "Undo the last dot"]] },
  { title: "View", keys: [["D", "Show or hide AI dots"], ["G", "Show or hide grid totals"], ["Space", "Play the seconds around the frame"], ["R", "Change the clip's speed"]] },
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

const MODES = {
  own: {
    title: "Count on my own",
    text: "AI's dots stay hidden. This is slower, and your counts also show how accurate AI is.",
  },
  ai: {
    title: "Start from AI's dots",
    text: "AI's dots are on the frame for you to correct. This is faster, but these frames can't measure AI.",
  },
};
type Mode = keyof typeof MODES;

export function Snapshots() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  // The person picks a way to count each time they open this step. Counting on their own is blind:
  // AI's dots never load, so the counts can score the AI, and frames come in a fixed random order,
  // so stopping early still covers the whole video.
  const [params, setParams] = useSearchParams();
  const asked = params.get("mode");
  const mode: Mode | null = asked === "own" || asked === "ai" ? asked : null;
  const blind = mode === "own";
  const fromAccuracy = params.get("from") === "accuracy";
  const askedFrame = Number(params.get("frame")) || null; // the report links straight to a peak frame
  const choose = (next: Mode | null) => {
    const kept = new URLSearchParams(params);
    if (next) kept.set("mode", next);
    else kept.delete("mode");
    setParams(kept);
  };
  const clip = useRef<HTMLVideoElement>(null);
  const [list, setList] = useState<SnapshotList | null>(null);
  const [currentId, setCurrentId] = useState<number | null>(null);
  const [frame, setFrame] = useState<SnapshotFrame | null>(null);
  const [dots, setDots] = useState<Dot[]>([]);
  const [image, setImage] = useState<"loading" | "ready" | "failed">("loading");
  const [showAi, setShowAi] = useState(true);
  const [showGrid, setShowGrid] = useState(true);
  const [playing, setPlaying] = useState(false);
  const [clipRate, setClipRate] = useState(CLIP_RATES[0]);
  const [clipAt, setClipAt] = useState<number | null>(null); // seconds from the frame while its clip plays
  const [record, setRecord] = useState<FrameRecord>(EMPTY_RECORD);
  const [speciesList, setSpeciesList] = useState<SpeciesRow[]>([]);
  const [error, setError] = useState("");
  const [toast, setToast] = useState("");
  const drafts = useRef(new Map<number, Dot[]>());
  const recordDrafts = useRef(new Map<number, FrameRecord>());
  const undoStack = useRef<Dot[][]>([]);
  const saving = useRef(false);

  const flash = (msg: string) => {
    setToast(msg);
    setTimeout(() => setToast(""), 2400);
  };

  const load = () => snapshotApi.list(id).then((all) => {
    // Sub-sample points come first either way: peak frames are extra, and can fall outside the window.
    const order = blind ? (a: SnapshotRow, b: SnapshotRow) => a.rank - b.rank : (a: SnapshotRow, b: SnapshotRow) => Number(a.kind === "peak") - Number(b.kind === "peak") || a.t - b.t;
    const l = { ...all, frames: [...all.frames].sort(order) };
    setList(l);
    setCurrentId(askedFrame ?? (l.frames.find((f) => !f.status) ?? l.frames[0])?.id ?? null);
  }).catch((e) => setError(e.message));

  useEffect(() => {
    load();
    drafts.current.clear(); // unsaved dots from the other way of counting don't carry over
    if (mode) api.event(id, "snapshot_open");
  }, [id, mode]);

  useEffect(() => {
    api.species().then(setSpeciesList).catch(() => setSpeciesList([])); // the names are only suggestions
  }, []);

  useEffect(() => {
    if (currentId === null || !mode) return;
    let stale = false;
    setFrame(null);
    setImage("loading");
    setPlaying(false);
    setClipAt(null);
    undoStack.current = [];
    snapshotApi.frame(currentId, blind).then((f) => {
      if (stale) return;
      setFrame(f);
      setDots(drafts.current.get(f.id) ?? f.dots);
      setRecord(recordDrafts.current.get(f.id) ?? { invertebrates: f.invertebrates ?? 0, species: f.species, visibility: f.visibility, comment: f.comment });
    }).catch((e) => flash(e.message));
    return () => { stale = true; };
  }, [currentId, mode]);

  useEffect(() => {
    const next = list && frame && nextOpen(list.frames, frame.id);
    if (next) new Image().src = snapshotApi.image(next.id);
  }, [frame?.id]);

  // Hiding AI dots takes them out of the count, so every dot in a saved total was on screen.
  const shown = useMemo(() => (showAi && !blind ? dots : dots.filter((d) => d.source === "user")), [dots, showAi, blind]);
  const hidden = dots.length - shown.length;

  const change = (next: Dot[]) => {
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

  const changeRecord = (next: FrameRecord) => {
    setRecord(next);
    if (currentId !== null) recordDrafts.current.set(currentId, next);
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
    try {
      const { stats } = await snapshotApi.save(frame.id, status, kept, hidden > 0, blind, record);
      drafts.current.delete(frame.id);
      recordDrafts.current.delete(frame.id);
      const frames = list.frames.map((f) => (f.id === frame.id ? { ...f, status, total: status === "checked" ? kept.length : null } : f));
      setList({ ...list, frames, stats });
      const next = nextOpen(frames, frame.id);
      if (next && !askedFrame) setCurrentId(next.id);
      else navigate(fromAccuracy ? "/accuracy" : `/videos/${id}/summary`);
    } catch (e) {
      flash((e as Error).message);
    } finally {
      saving.current = false;
    }
  };

  const back = () => {
    const i = list?.frames.findIndex((f) => f.id === currentId) ?? 0;
    if (list && i > 0) setCurrentId(list.frames[i - 1].id);
    else flash("This is the first frame");
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!mode || e.repeat || e.metaKey || e.ctrlKey || e.altKey) return;
      if ((e.target as HTMLElement).closest("input, textarea, select")) return; // typing a note isn't a shortcut
      const key = e.key.toLowerCase();
      if (key === " ") { e.preventDefault(); playClip(); }
      else if (key === "n") save("checked");
      else if (key === "u") save("could_not_see");
      else if (key === "b") back();
      else if (key === "z") undo();
      else if (key === "d" && !blind) setShowAi((v) => !v);
      else if (key === "g") setShowGrid((v) => !v);
      else if (key === "r") changeClipRate(CLIP_RATES[(CLIP_RATES.indexOf(clipRate) + 1) % CLIP_RATES.length]);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  if (error) return <p className="meta">{error}</p>;
  if (!list) return <p className="meta">Loading…</p>;

  const { video, stats, protocol } = list;
  const header = (
    <VideoHeader
      id={id}
      step="snapshots"
      snapshots={{ done: stats.frames_done, total: stats.frames_total }}
      from={fromAccuracy ? { to: "/accuracy", label: "AI accuracy" } : undefined}
    />
  );
  if (!list.frames.length) {
    return <div className="stack">{header}<p className="meta">No frames to check: this clip is too short for a sub-sample point and AI saw no fish in it.</p></div>;
  }
  if (!mode) {
    const own = list.frames.filter((f) => f.kind === "snapshot" && f.status === "checked" && f.blind).length;
    return (
      <div className="stack">
        {header}
        <div className="stack" style={{ maxWidth: 760, gap: 16 }}>
          <div>
            <h1>How do you want to count?</h1>
            <p className="lede">
              {stats.frames_total} frames, one every {protocol.every_s} seconds. {stats.frames_done} done so far{own ? `, ${own} of them on your own` : ""}.
              You can switch at any time.
            </p>
          </div>
          <div className="choices">
            {(Object.keys(MODES) as Mode[]).map((m) => (
              <button key={m} className="choice" onClick={() => choose(m)}>
                <b>{MODES[m].title}</b>
                <span>{MODES[m].text}</span>
              </button>
            ))}
          </div>
          <p className="meta">Once a frame has shown AI's dots it can't measure AI, even if you count it again on your own.</p>
          <HowToMark />
        </div>
      </div>
    );
  }

  const peakDone = stats.peak_checked + stats.peak_could_not_see;
  const label = frame ? LABELS[frame.status] : null;
  const named = record.species.reduce((sum, s) => sum + s.n, 0);
  const fact = (name: string, value: string) => (
    <div className="row" style={{ justifyContent: "space-between" }}><span>{name}</span><span className="num">{value}</span></div>
  );

  return (
    <div className="stack">
      {header}
      <div className="row">
        <b className="num">{stats.frames_done} of {stats.frames_total}</b>
        <span className="meta">sub-sample points done</span>
        <div className="bar" style={{ flex: 1 }}><i style={{ width: `${(stats.frames_done / (stats.frames_total || 1)) * 100}%` }} /></div>
        {!blind && <span className="num meta">{peakDone} of {stats.peak_total} peak frames</span>}
      </div>
      <p className="meta">
        {blind ? "Counting on your own. AI's dots are hidden, so your counts can measure AI. " : "Starting from AI's dots. These frames can't measure AI. "}
        <button className="link" onClick={() => choose(null)}>Change how you count</button>
      </p>
      <div className="split">
        <DotStage
          key={currentId}
          src={snapshotApi.image(currentId ?? 0)}
          dots={shown}
          showDots={!playing}
          showGrid={showGrid && !playing}
          aspect={`${video.width || 16} / ${video.height || 9}`}
          onAdd={(x, y) => (playing ? stopClip() : change([...dots, { x, y, source: "user" }]))}
          onRemove={(dot) => change(dots.filter((d) => d !== dot))}
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
          {frame && (
            <span className="stamp">
              {clock(frame.t)} / {clock(video.duration)}
              {playing && clipAt !== null && ` · ${clipAt >= 0 ? "+" : "−"}${Math.abs(clipAt).toFixed(1)} s · ${Math.abs(clipAt) <= COUNT_REACH_S ? "counting second" : "context only"}`}
            </span>
          )}
          {image === "failed" && <span className="stage-note">This frame can't be read. Press U.</span>}
        </DotStage>
        <aside className="stack">
          <div className="panel" style={{ padding: 16 }}>
            <div className="row" style={{ justifyContent: "space-between" }}>
              {frame?.kind === "peak" ? <span className="pill accent">AI's busiest moment</span> : <span className="pill muted">Sub-sample point</span>}
              {label && <span className={`pill ${label.tone}`}>{label.text}</span>}
            </div>
            <div className="meta" style={{ marginTop: 12 }}>Total in this frame</div>
            <div className="num" style={{ fontSize: 32, fontWeight: 600, letterSpacing: "-.8px", marginTop: 6 }}>{shown.length}</div>
            <p className="meta" style={{ marginTop: 8, lineHeight: 1.5 }}>
              {frame?.kind === "peak" ? "AI saw many fish here, away from the sub-sample points. It feeds MaxN, never MeanCount. " : ""}
              {hidden > 0 ? `${hidden} AI ${hidden === 1 ? "dot is" : "dots are"} hidden and won't be saved. ` : ""}
              {shown.length === 0 ? "With no dots, saving records zero fish. " : ""}
              {blind && frame?.ai_shown && frame.status !== "checked" ? "This frame showed AI's dots earlier, so it won't measure AI." : ""}
            </p>
          </div>
          <RecordPanel record={record} fish={shown.length} named={named} options={protocol.visibility_options} species={speciesList} onChange={changeRecord} />
          <div className="panel panel-pad">
            <button className="btn primary" disabled={image !== "ready" || !frame} onClick={() => save("checked")}><kbd>N</kbd>Save, next</button>
            <button className="btn tall" disabled={image === "loading" || !frame} onClick={() => save("could_not_see")}>Could not see</button>
            <div className="row">
              <button className="btn" style={{ flex: 1 }} onClick={back}>Back</button>
              <button className="btn" style={{ flex: 1 }} onClick={undo}>Undo dot</button>
              <button className="btn" style={{ flex: 1 }} onClick={playClip}>{playing ? "Stop" : `Play ±${protocol.context_s} s`}</button>
            </div>
            <div className="row">
              {CLIP_RATES.map((r) => <button key={r} className="chip" aria-pressed={clipRate === r} onClick={() => changeClipRate(r)}>{r}×</button>)}
              {!blind && <button className="chip" aria-pressed={showAi} onClick={() => setShowAi(!showAi)}>AI dots</button>}
              <button className="chip" aria-pressed={showGrid} onClick={() => setShowGrid(!showGrid)}>Grid totals</button>
            </div>
            <p className="meta">Click empty water to add a dot. Click a dot to remove it.{blind ? "" : ` AI dots: ${frame?.model}, saved detections.`}</p>
          </div>
          <div className="panel panel-pad snap-facts" style={{ fontSize: 13 }}>
            {fact("MeanCount", stats.mean_count?.toFixed(2) ?? "—")}
            {fact("Points in MeanCount", `${stats.frames_checked} of ${stats.frames_total}`)}
            {fact(stats.largest_label, String(stats.largest_count ?? "—"))}
            {fact("Could not see", String(stats.could_not_see + stats.peak_could_not_see))}
          </div>
          <div><Shortcuts groups={blind ? KEYS.map((g) => ({ ...g, keys: g.keys.filter(([key]) => key !== "D") })) : KEYS} /></div>
          <details className="meta">
            <summary>What counts as a fish</summary>
            <HowToMark />
          </details>
        </aside>
      </div>
      {toast && <div className="toast" role="status">{toast}</div>}
    </div>
  );
}

/** The marking rules, the same for everyone, so counts from different people can be compared. */
function HowToMark() {
  return (
    <ul className="meta rules">
      <li>Put one dot on the middle of each fish you can see in this second. Watch the clip for context, but don't count what only shows up a full second away.</li>
      <li>It's a fish if at least two of these show: fish shape, anatomy such as fins or eyes, colour or a flash of scales, swimming movement.</li>
      <li>In a school, count only the fish you're sure of. If it could be algae, sediment or bubbles, leave it out.</li>
      <li>Dots are for fish only. Enter crabs, shrimp, worms and snails under Invertebrates, and leave out anything inside a bait bag or basket.</li>
      <li>No fish in the frame? Save it with no dots. That answer is just as useful.</li>
      <li>Too dark or murky to tell? Choose Could not see. That frame is left out of every number.</li>
    </ul>
  );
}

/** What the procedure records at a sub-sample point, beyond the fish dots. */
function RecordPanel({ record, fish, named, options, species, onChange }: {
  record: FrameRecord; fish: number; named: number; options: string[]; species: SpeciesRow[]; onChange: (next: FrameRecord) => void;
}) {
  const row = (i: number, change: Partial<FrameRecord["species"][number]>) =>
    onChange({ ...record, species: record.species.map((s, j) => (j === i ? { ...s, ...change } : s)) });
  return (
    <div className="panel panel-pad">
      <label className="field">
        Invertebrates
        <input className="num" type="number" min={0} style={{ minWidth: 0 }} value={record.invertebrates} onChange={(e) => onChange({ ...record, invertebrates: Math.max(0, Number(e.target.value) || 0) })} />
      </label>
      <div className="stack" style={{ gap: 6 }}>
        <span className="meta">Fish species in this frame</span>
        {record.species.map((s, i) => (
          <div className="row" key={i}>
            <input className="record-input" list="frame-species" aria-label="Species" placeholder="Species" value={s.name} onChange={(e) => row(i, { name: e.target.value })} />
            <input className="record-input num" style={{ flex: "0 0 56px" }} type="number" min={1} aria-label="How many" value={s.n} onChange={(e) => row(i, { n: Math.max(1, Number(e.target.value) || 1) })} />
            <button className="btn" aria-label="Remove species" onClick={() => onChange({ ...record, species: record.species.filter((_, j) => j !== i) })}>×</button>
          </div>
        ))}
        <button className="btn" onClick={() => onChange({ ...record, species: [...record.species, { name: "", n: 1 }] })}>Add species</button>
        <datalist id="frame-species">{species.map((s) => <option key={s.species} value={s.common} />)}</datalist>
        <span className="meta">
          {named > fish ? `That's more than the ${fish} fish marked on this frame.` : `Unknown or unable to ID: ${fish - named}`}
        </span>
      </div>
      <label className="field">
        Visibility at this frame
        <select value={record.visibility} onChange={(e) => onChange({ ...record, visibility: e.target.value })}>
          <option value="">Not noted</option>
          {options.map((o) => <option key={o}>{o}</option>)}
        </select>
      </label>
      <label className="field">
        Notes
        <textarea className="record-input" rows={2} value={record.comment} onChange={(e) => onChange({ ...record, comment: e.target.value })} />
      </label>
    </div>
  );
}
