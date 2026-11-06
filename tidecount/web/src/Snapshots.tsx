import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api, clock, Dot, snapshotApi, SnapshotFrame, SnapshotList, SnapshotRow, SnapshotStatus } from "./api";
import { DotStage } from "./Dots";
import { KeyGroup, Shortcuts } from "./Shortcuts";
import { VideoHeader } from "./VideoHeader";

const KEYS: KeyGroup[] = [
  { title: "This frame", keys: [["N", "Save and go to the next"], ["U", "Could not see"], ["B", "Back one frame"], ["Z", "Undo the last dot"]] },
  { title: "View", keys: [["D", "Show or hide AI dots"], ["G", "Show or hide grid totals"], ["Space", "Play two seconds around the frame"]] },
];
const CLIP_S = 1; // Space plays this long either side of the frame
const LABELS = {
  "": { text: "Not done", tone: "muted" },
  checked: { text: "Checked", tone: "up" },
  could_not_see: { text: "Could not see", tone: "warn" },
};

/** The next frame nobody has done, in the order the list is in, wrapping round to the start. */
const nextOpen = (frames: SnapshotRow[], after: number) => {
  const open = (f: SnapshotRow) => !f.status && f.id !== after;
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
  const [error, setError] = useState("");
  const [toast, setToast] = useState("");
  const drafts = useRef(new Map<number, Dot[]>());
  const undoStack = useRef<Dot[][]>([]);
  const saving = useRef(false);

  const flash = (msg: string) => {
    setToast(msg);
    setTimeout(() => setToast(""), 2400);
  };

  useEffect(() => {
    snapshotApi.list(id).then((all) => {
      const l = blind ? { ...all, frames: [...all.frames].sort((a, b) => a.rank - b.rank) } : all;
      setList(l);
      setCurrentId((l.frames.find((f) => !f.status) ?? l.frames[0])?.id ?? null);
    }).catch((e) => setError(e.message));
    drafts.current.clear(); // unsaved dots from the other way of counting don't carry over
    if (mode) api.event(id, "snapshot_open");
  }, [id, mode]);

  useEffect(() => {
    if (currentId === null || !mode) return;
    let stale = false;
    setFrame(null);
    setImage("loading");
    setPlaying(false);
    undoStack.current = [];
    snapshotApi.frame(currentId, blind).then((f) => {
      if (stale) return;
      setFrame(f);
      setDots(drafts.current.get(f.id) ?? f.dots);
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

  const stopClip = () => {
    clip.current?.pause();
    setPlaying(false);
  };
  const playClip = () => {
    const el = clip.current;
    if (!el || !frame) return;
    if (playing) return stopClip();
    el.currentTime = Math.max(0, frame.t - CLIP_S);
    setPlaying(true);
    el.play().catch(() => setPlaying(false));
  };

  const save = async (status: SnapshotStatus) => {
    if (!list || !frame || frame.id !== currentId || saving.current) return;
    if (status === "checked" ? image !== "ready" : image === "loading") return;
    saving.current = true;
    const kept = status === "checked" ? shown : [];
    try {
      const { stats } = await snapshotApi.save(frame.id, status, kept, hidden > 0, blind);
      drafts.current.delete(frame.id);
      const frames = list.frames.map((f) => (f.id === frame.id ? { ...f, status, total: status === "checked" ? kept.length : null } : f));
      setList({ ...list, frames, stats });
      const next = nextOpen(frames, frame.id);
      if (next) setCurrentId(next.id);
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
      const key = e.key.toLowerCase();
      if (key === " ") { e.preventDefault(); playClip(); }
      else if (key === "n") save("checked");
      else if (key === "u") save("could_not_see");
      else if (key === "b") back();
      else if (key === "z") undo();
      else if (key === "d" && !blind) setShowAi((v) => !v);
      else if (key === "g") setShowGrid((v) => !v);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  if (error) return <p className="meta">{error}</p>;
  if (!list) return <p className="meta">Loading…</p>;

  const { video, stats } = list;
  const header = (
    <VideoHeader
      id={id}
      step="snapshots"
      snapshots={{ done: stats.frames_done, total: stats.frames_total }}
      from={fromAccuracy ? { to: "/accuracy", label: "AI accuracy" } : undefined}
    />
  );
  if (!list.frames.length) {
    return <div className="stack">{header}<p className="meta">No frames to check: this clip is under {clock(15)} long and AI saw no fish in it.</p></div>;
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
              {stats.frames_total} frames, one every 30 seconds. {stats.frames_done} done so far{own ? `, ${own} of them on your own` : ""}.
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
  const fact = (name: string, value: string) => (
    <div className="row" style={{ justifyContent: "space-between" }}><span>{name}</span><span className="num">{value}</span></div>
  );

  return (
    <div className="stack">
      {header}
      <div className="row">
        <b className="num">{stats.frames_done} of {stats.frames_total}</b>
        <span className="meta">snapshots done</span>
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
            src={`/api/videos/${id}/proxy`}
            muted
            playsInline
            preload="metadata"
            style={{ display: playing ? "block" : "none" }}
            onTimeUpdate={(e) => { if (frame && e.currentTarget.currentTime >= frame.t + CLIP_S) stopClip(); }}
            onEnded={stopClip}
            onError={() => { setPlaying(false); flash("The playable copy isn't available."); }}
          />
          {frame && <span className="stamp">{clock(frame.t)} / {clock(video.duration)}</span>}
          {image === "failed" && <span className="stage-note">This frame can't be read. Press U.</span>}
        </DotStage>
        <aside className="stack">
          <div className="panel" style={{ padding: 16 }}>
            <div className="row" style={{ justifyContent: "space-between" }}>
              {frame?.kind === "peak" ? <span className="pill accent">Peak frame</span> : <span className="pill muted">Snapshot</span>}
              {label && <span className={`pill ${label.tone}`}>{label.text}</span>}
            </div>
            <div className="meta" style={{ marginTop: 12 }}>Total in this frame</div>
            <div className="num" style={{ fontSize: 32, fontWeight: 600, letterSpacing: "-.8px", marginTop: 6 }}>{shown.length}</div>
            <p className="meta" style={{ marginTop: 8, lineHeight: 1.5 }}>
              {frame?.kind === "peak" ? "Picked for a high AI count. It feeds MaxN, never MeanCount. " : ""}
              {hidden > 0 ? `${hidden} AI ${hidden === 1 ? "dot is" : "dots are"} hidden and won't be saved. ` : ""}
              {shown.length === 0 ? "With no dots, saving records zero fish. " : ""}
              {blind && frame?.ai_shown && frame.status !== "checked" ? "This frame showed AI's dots earlier, so it won't measure AI." : ""}
            </p>
          </div>
          <div className="panel panel-pad" style={{ fontSize: 13 }}>
            {fact("MeanCount", stats.mean_count?.toFixed(2) ?? "—")}
            {fact("Frames in MeanCount", `${stats.frames_checked} of ${stats.frames_total}`)}
            {fact(stats.largest_label, String(stats.largest_count ?? "—"))}
            {fact("Could not see", String(stats.could_not_see + stats.peak_could_not_see))}
          </div>
          <div className="panel panel-pad">
            <button className="btn primary" disabled={image !== "ready" || !frame} onClick={() => save("checked")}><kbd>N</kbd>Save, next</button>
            <button className="btn tall" disabled={image === "loading" || !frame} onClick={() => save("could_not_see")}>Could not see</button>
            <div className="row">
              <button className="btn" style={{ flex: 1 }} onClick={back}>Back</button>
              <button className="btn" style={{ flex: 1 }} onClick={undo}>Undo dot</button>
              <button className="btn" style={{ flex: 1 }} onClick={playClip}>{playing ? "Stop" : "Play 2 s"}</button>
            </div>
            <div className="row">
              {!blind && <button className="chip" aria-pressed={showAi} onClick={() => setShowAi(!showAi)}>AI dots</button>}
              <button className="chip" aria-pressed={showGrid} onClick={() => setShowGrid(!showGrid)}>Grid totals</button>
            </div>
            <p className="meta">Click empty water to add a dot. Click a dot to remove it.{blind ? "" : ` AI dots: ${frame?.model}, saved detections.`}</p>
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
      <li>Put one dot on the middle of each fish. Include fish that are partly hidden, blurry or far away if you're confident it's a fish.</li>
      <li>Count only fish. Leave out crabs and other animals, and anything inside a bait bag or basket.</li>
      <li>No fish in the frame? Save it with no dots. That answer is just as useful.</li>
      <li>Too dark or murky to tell? Choose Could not see. That frame is left out of every number.</li>
    </ul>
  );
}
