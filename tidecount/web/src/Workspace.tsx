import { CSSProperties, PointerEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api, clock, FrameBox, Segment, Track, VideoDetail } from "./api";
import { guess, nameOf, pos, stateFor, UNIDENTIFIED } from "./trackHelpers";
import { KeyGroup, Shortcuts } from "./Shortcuts";
import { VideoHeader } from "./VideoHeader";
import { PicturePanel, pictureFilter, SharpenFilter, usePicture } from "./Picture";

const RATES = [0.25, 0.5, 1, 2, 4];
const FRAME = 1 / 30;
/** The double arrows, and Shift with an arrow key, jump this many frames. */
const JUMP = 10;
const KEYS: KeyGroup[] = [
  { title: "Video", keys: [["Space", "Play or pause"], ["← →", "Step one frame"], ["Shift ← →", `Jump ${JUMP} frames`], ["B", "Show or hide AI boxes"], ["G", "Show or hide the grid"]] },
  { title: "Find fish", keys: [["A", "Add fish AI missed: drag a box around each"], ["F", "Redetect this frame: show fish AI was less sure of"], ["Esc", "Stop adding, or hide redetected boxes"], ["[ ]", "Previous or next track in the whole video"]] },
  { title: "The selected box", keys: [["1 2 3", "Confirm a suggested species"], ["C or U", "Unidentified fish"], ["X", "Not a fish, or remove a fish you added"], ["Z", "Undo the last decision or added fish"]] },
  { title: "The segment", keys: [["N", "Mark reviewed and go to the next"]] },
];
/** A click with no drag still adds a fish, with a box this size around the click. */
const CLICK_BOX = { w: 0.1, h: 0.08 };
type Past = { id: number; added?: boolean };
type Rect = { x: number; y: number; w: number; h: number };
/** Boxes from Freeze frame: the analysed frame they belong to, and the ones nobody has decided yet. */
type Frozen = { t: number; threshold: number; boxes: FrameBox[] };

const inSeg = (t: Track, s: Segment) => t.first_t < s.end && t.last_t > s.start;

export function Workspace() {
  const { id = "" } = useParams();
  const [search] = useSearchParams();
  const navigate = useNavigate();
  const player = useRef<HTMLVideoElement>(null);
  const [video, setVideo] = useState<VideoDetail | null>(null);
  const [tracks, setTracks] = useState<Track[]>([]);
  const [segId, setSegId] = useState<number | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [time, setTime] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [rate, setRate] = useState(1);
  const [boxes, setBoxes] = useState(true);
  const [grid, setGrid] = useState(false);
  const [picture, setPicture] = usePicture();
  const [original, setOriginal] = useState(false);  // held down: the footage as filmed, to compare
  const [full, setFull] = useState(false);
  const [addMode, setAddMode] = useState(false);
  const [draft, setDraft] = useState<Rect | null>(null);
  const [following, setFollowing] = useState(false);
  const [siteSpecies, setSiteSpecies] = useState<string[]>([]);
  const [toast, setToast] = useState("");
  const [frozen, setFrozen] = useState<Frozen | null>(null);
  const [maybe, setMaybe] = useState<number | null>(null);  // which frozen box is selected
  const history = useRef<Past[]>([]);
  const dragFrom = useRef<{ x: number; y: number } | null>(null);
  const opening = useRef<Track | null>(null);

  const flash = (msg: string) => {
    setToast(msg);
    setTimeout(() => setToast(""), 2400);
  };

  useEffect(() => {
    Promise.all([api.video(id), api.tracks(id)]).then(([v, t]) => {
      setVideo(v);
      setTracks(t);
      const queue = v.segments.filter((s) => s.status !== "skipped");
      const wanted = Number(search.get("seg"));
      const asked = t.find((x) => x.id === Number(search.get("track")));
      opening.current = asked ?? null;
      setSegId((asked && queue.find((s) => inSeg(asked, s))?.id) ?? queue.find((s) => s.id === wanted)?.id ?? queue.find((s) => s.status === "needs_review")?.id ?? queue[0]?.id ?? null);
    });
    api.species().then((rows) => setSiteSpecies([...new Set(rows.map((r) => r.common))].sort()));
    api.event(id, "open");
  }, [id]);

  const queue = useMemo(() => video?.segments.filter((s) => s.status !== "skipped") ?? [], [video]);
  const seg = queue.find((s) => s.id === segId) ?? null;
  const segTracks = useMemo(() => (seg ? tracks.filter((t) => inSeg(t, seg) && t.state !== "Rejected") : []), [seg, tracks]);
  const undecided = segTracks.filter((t) => !t.state);
  const current = tracks.find((t) => t.id === selected) ?? null;
  const possible = maybe !== null ? frozen?.boxes[maybe] ?? null : null;

  useEffect(() => {
    const el = player.current;
    if (!el) return;
    let handle = 0;
    const tick = () => {
      setTime(el.currentTime);
      handle = el.requestVideoFrameCallback(tick);
    };
    handle = el.requestVideoFrameCallback(tick);
    return () => el.cancelVideoFrameCallback(handle);
  }, [video]);

  useEffect(() => {
    if (player.current) player.current.playbackRate = rate;
  }, [rate]);

  useEffect(() => {
    if (!seg || !player.current) return;
    player.current.currentTime = seg.start;
    setTime(seg.start);
    player.current.pause();
    setSelected(tracks.filter((t) => inSeg(t, seg) && !t.state)[0]?.id ?? null);
    if (opening.current) {
      const asked = opening.current;
      opening.current = null;
      setSelected(asked.id);
      seek(asked.first_t);
      if (!inSeg(asked, seg)) setFull(true);
    }
    setAdding(false);
    unfreeze();
    api.event(id, "segment_open", { segment: seg.id });
  }, [segId]);

  useEffect(() => {
    if (!seg || full || !playing || !player.current) return;
    if (time >= seg.end) player.current.pause();
  }, [time, seg, full, playing]);

  useEffect(() => {
    if (frozen && Math.abs(time - frozen.t) > 0.1) unfreeze();
  }, [time]);

  const seek = (t: number) => {
    if (player.current) player.current.currentTime = t;
    setTime(t);
  };
  const toggle = () => {
    const el = player.current;
    if (!el) return;
    if (el.paused) el.play();
    else el.pause();
  };
  const step = (n: number) => {
    player.current?.pause();
    seek(Math.max(0, (player.current?.currentTime ?? 0) + n * FRAME));
  };

  const patch = (trackId: number, state: Track["state"], species: string | null) =>
    setTracks((all) => all.map((t) => (t.id === trackId ? { ...t, state, decided_species: species } : t)));

  const decide = useCallback(async (t: Track, species: string) => {
    const state = stateFor(t, species);
    patch(t.id, state, species);
    history.current.push({ id: t.id });  // the track stays selected, so the video doesn't jump
    await api.decide(t.id, state, species);
  }, []);

  /** Take back a fish a person added. It leaves no record, unlike Not a fish on an AI track. */
  const remove = useCallback(async (trackId: number) => {
    setTracks((all) => all.filter((t) => t.id !== trackId));
    setSelected((now) => (now === trackId ? null : now));
    history.current = history.current.filter((p) => p.id !== trackId);
    await api.removeFish(trackId);
    flash("Added fish removed");
  }, []);

  const reject = useCallback(async (t: Track) => {
    if (t.manual) return remove(t.id);
    patch(t.id, "Rejected", null);
    history.current.push({ id: t.id });
    await api.decide(t.id, "Rejected", null);
  }, [remove]);

  const undo = useCallback(async () => {
    const last = history.current.pop();
    if (!last) return flash("Nothing to undo");
    if (last.added) return remove(last.id);
    const track = tracks.find((t) => t.id === last.id);
    setSelected(last.id);
    if (track?.manual) {
      // A fish a person added is counted from the start, so undoing its name puts that back.
      patch(last.id, "Corrected", UNIDENTIFIED);
      await api.decide(last.id, "Corrected", UNIDENTIFIED);
    } else {
      patch(last.id, null, null);
      await api.undo(last.id);
    }
    flash("Decision undone");
  }, [tracks, remove]);

  const finish = async (status: "reviewed" | "could_not_see") => {
    if (!seg) return;
    await api.segmentStatus(seg.id, status);
    const updated = video!.segments.map((s) => (s.id === seg.id ? { ...s, status } : s));
    setVideo({ ...video!, segments: updated });
    if (status === "reviewed" && seg.is_audit) flash("That was an audit of skipped footage.");
    const open = updated.filter((s) => s.status === "needs_review");
    const next = open.find((s) => s.start > seg.start) ?? open[0];
    if (next) setSegId(next.id);
    else navigate(`/videos/${id}/summary`);
  };

  /** Step through every fish in the video by track number, wrapping at the ends. A fish in another
   *  segment opens that segment, so the queue and the fish card stay in step. */
  const fishOrder = useMemo(() => [...tracks].sort((a, b) => a.id - b.id), [tracks]);
  const fishIndex = fishOrder.findIndex((t) => t.id === selected);
  const goFish = (dir: 1 | -1) => {
    if (!fishOrder.length) return;
    let at: number;
    if (fishIndex >= 0) at = (fishIndex + dir + fishOrder.length) % fishOrder.length;
    else {
      // Nothing selected: start from the fish nearest the playhead in the direction asked.
      const ahead = fishOrder.findIndex((t) => t.first_t >= time);
      at = dir === 1 ? Math.max(ahead, 0) : (ahead <= 0 ? fishOrder.length - 1 : ahead - 1);
    }
    const t = fishOrder[at];
    player.current?.pause();
    setMaybe(null);
    const home = queue.find((s) => t.first_t >= s.start && t.first_t < s.end) ?? queue.find((s) => inSeg(t, s));
    if (home && home.id !== segId) {
      opening.current = t;  // the segment effect selects it and seeks to it once the segment opens
      setSegId(home.id);
      return;
    }
    setSelected(t.id);
    seek(t.first_t);
    if (seg && !inSeg(t, seg)) setFull(true);  // in footage AI skipped, so don't stop at this segment's end
  };

  const unfreeze = () => {
    setFrozen(null);
    setMaybe(null);
  };

  /** Pause, and show every box AI drew on this frame at a lower confidence than the one that starts tracks. */
  const freeze = async () => {
    const el = player.current;
    if (!el) return;
    el.pause();
    setAdding(false);
    try {
      const got = await api.frameBoxes(id, el.currentTime);
      seek(got.t);  // the boxes belong to the analysed frame nearest here, so show that frame
      setFrozen(got);
      setMaybe(null);
      flash(got.boxes.length
        ? `${got.boxes.length} possible fish AI was less sure of. Click one to decide.`
        : "No other possible fish on this frame");
      api.event(id, "freeze_frame", { t: got.t, offered: got.boxes.length, threshold: got.threshold });
    } catch (err) {
      flash(`Couldn't freeze: ${(err as Error).message}`);
    }
  };

  const pickMaybe = (i: number) => {
    setMaybe(i);
    setSelected(null);
  };

  /** Settle a frozen box: confirmed, it becomes a fish like one a person drew; rejected, it's logged and goes. */
  const settleMaybe = async (fish: boolean) => {
    if (!frozen || !possible) return;
    const { t } = frozen;
    const box = { x: possible.x, y: possible.y, w: possible.w, h: possible.h };
    setFrozen({ ...frozen, boxes: frozen.boxes.filter((b) => b !== possible) });
    setMaybe(null);
    if (fish) await addBox(box, t);
    else api.event(id, "freeze_box_rejected", { t, ...box, conf: possible.conf });
  };

  const setAdding = (on: boolean) => {
    if (on) player.current?.pause();
    dragFrom.current = null;
    setDraft(null);
    setAddMode(on);
  };

  /** Where the pointer is on the video, from 0 to 1 each way. */
  const spot = (e: PointerEvent<HTMLDivElement>) => {
    const box = e.currentTarget.getBoundingClientRect();
    const clamp = (v: number) => Math.min(1, Math.max(0, v));
    return { x: clamp((e.clientX - box.left) / box.width), y: clamp((e.clientY - box.top) / box.height) };
  };

  const onDown = (e: PointerEvent<HTMLDivElement>) => {
    if (!addMode || following || e.button !== 0) return;
    player.current?.pause();  // the box belongs to one frame, so the frame must hold still while it's drawn
    e.currentTarget.setPointerCapture(e.pointerId);
    dragFrom.current = spot(e);
    setDraft({ ...dragFrom.current, w: 0, h: 0 });
  };

  const onMove = (e: PointerEvent<HTMLDivElement>) => {
    const from = dragFrom.current;
    if (!from) return;
    const to = spot(e);
    setDraft({ x: Math.min(from.x, to.x), y: Math.min(from.y, to.y), w: Math.abs(to.x - from.x), h: Math.abs(to.y - from.y) });
  };

  const onUp = async (e: PointerEvent<HTMLDivElement>) => {
    const from = dragFrom.current;
    if (!from) return;
    dragFrom.current = null;
    const to = spot(e);
    const dragged = Math.abs(to.x - from.x) > 0.01 && Math.abs(to.y - from.y) > 0.01;
    const box = dragged
      ? { x: Math.min(from.x, to.x), y: Math.min(from.y, to.y), w: Math.abs(to.x - from.x), h: Math.abs(to.y - from.y) }
      : { x: to.x - CLICK_BOX.w / 2, y: to.y - CLICK_BOX.h / 2, ...CLICK_BOX };
    setDraft(box);
    await addBox(box, player.current?.currentTime ?? time);
    setDraft(null);
  };

  /** A fish AI missed or wasn't sure of: followed through the video, counted, and selected. */
  const addBox = async (box: Rect, at: number) => {
    setFollowing(true);
    try {
      const added = await api.addFish(id, at, box);
      setTracks(await api.tracks(id));
      setSelected(added.id);
      history.current.push({ id: added.id, added: true });
      flash(added.points > 1 ? `Added, and followed for ${added.seconds.toFixed(1)} s` : "Added. AI couldn't follow it, so the box marks this moment only.");
      // Species suggestions arrive a little later, since the species model takes a while to load.
      [4000, 20000, 45000].forEach((wait) => setTimeout(async () => {
        const fresh = (await api.tracks(id)).find((t) => t.id === added.id);
        if (fresh?.candidates.length) setTracks((all) => all.map((t) => (t.id === added.id && !t.candidates.length ? { ...t, candidates: fresh.candidates } : t)));
      }, wait));
    } catch (err) {
      flash(`Not added: ${(err as Error).message}`);
    }
    setFollowing(false);
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (["INPUT", "SELECT", "TEXTAREA"].includes((e.target as HTMLElement).tagName)) return;
      const key = e.key.toLowerCase();
      if (key === " ") { e.preventDefault(); toggle(); }
      else if (key === "arrowleft") step(e.shiftKey ? -JUMP : -1);
      else if (key === "arrowright") step(e.shiftKey ? JUMP : 1);
      else if (key === "z") undo();
      else if (key === "b") setBoxes((v) => !v);
      else if (key === "g") setGrid((v) => !v);
      else if (key === "a") setAdding(!addMode);
      else if (key === "f") { if (frozen) unfreeze(); else freeze(); }
      else if (key === "]") goFish(1);
      else if (key === "[") goFish(-1);
      else if (key === "escape") { setAdding(false); unfreeze(); }
      else if (key === "n") finish("reviewed");
      else if (possible) {
        if (key === "c") settleMaybe(true);
        else if (key === "x") settleMaybe(false);
      }
      else if (current) {
        if (key === "c" || key === "u") decide(current, UNIDENTIFIED);
        else if (key === "x") reject(current);
        else if (["1", "2", "3"].includes(key) && current.candidates[+key - 1]) decide(current, nameOf(current.candidates[+key - 1]));
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const visible = useMemo(() => tracks.flatMap((t) => {
    if (t.state === "Rejected" && t.id !== selected) return [];
    const p = pos(t, time);
    return p ? [{ track: t, box: p }] : [];
  }), [tracks, time, selected]);

  const bars = useMemo(() => {
    if (!video) return [];
    const count = Math.min(140, video.seconds.length);
    const size = video.seconds.length / Math.max(count, 1);
    const peak = Math.max(1, ...video.seconds.map((s) => s.detections));
    return Array.from({ length: count }, (_, i) => {
      const part = video.seconds.slice(Math.floor(i * size), Math.floor((i + 1) * size));
      const fish = Math.max(0, ...part.map((p) => p.detections));
      const at = (i + 0.5) * size;
      return { at, height: Math.max(6, 8 + (fish / peak) * 92), seg: video.segments.find((s) => at >= s.start && at < s.end) };
    });
  }, [video]);

  if (!video) return <p className="meta">Loading…</p>;
  const speciesButtons = current?.candidates.map((c, i) => (
    <button key={c.species} className="species" aria-pressed={current.decided_species === nameOf(c)} onClick={() => decide(current, nameOf(c))}>
      <span>{i + 1}. {nameOf(c)}</span><span className="num meta">{Math.round(c.score * 100)}%</span>
    </button>
  ));
  const done = queue.filter((s) => s.status !== "needs_review").length;
  const ratio = (video.width || 16) / (video.height || 9);
  const filter = original ? "none" : pictureFilter(picture, "sharpen");

  return (
    <div className="stack review-page">
      <VideoHeader id={id} step="review" view="segments" review={{ done, total: queue.length }} />

      <SharpenFilter id="sharpen" amount={picture.sharpness} />
      <div className="workspace">
        <section className="review-mid" aria-label="Video" style={{ "--ratio": ratio } as CSSProperties}>
          <PicturePanel value={picture} onChange={setPicture} onCompare={setOriginal}>
            <label className="switch">
              <input type="checkbox" checked={boxes} onChange={() => setBoxes(!boxes)} />
              <span>AI boxes</span><kbd className="switch-key">B</kbd>
            </label>
            <label className="switch">
              <input type="checkbox" checked={grid} onChange={() => setGrid(!grid)} />
              <span>Grid</span><kbd className="switch-key">G</kbd>
            </label>
          </PicturePanel>
          <div
            className={`stage ${addMode ? "adding" : ""}`}
            style={{ aspectRatio: `${ratio}` }}
            onPointerDown={onDown}
            onPointerMove={onMove}
            onPointerUp={onUp}
          >
            <video
              ref={player}
              src={`/api/videos/${id}/proxy`}
              muted
              playsInline
              preload="auto"
              style={{ filter }}
              onPlay={() => setPlaying(true)}
              onPause={() => setPlaying(false)}
            />
            <div className="overlay">
              {grid && <div className="gridlines">{Array.from({ length: 15 }, (_, i) => <div key={i} />)}</div>}
              {boxes && visible.map(({ track: t, box: [, x, y, w, h] }) => {
                const name = t.decided_species ?? (guess(t) ? `${guess(t)}?` : "Fish");
                const state = t.manual ? "Added by you" : t.state ?? "Suggested";
                return (
                  <button
                    key={t.id}
                    className={`fishbox ${t.state === "Confirmed" ? "done" : t.state === "Corrected" ? "fixed" : ""} ${t.id === selected ? "sel" : ""}`}
                    style={{ left: `${x * 100}%`, top: `${y * 100}%`, width: `${w * 100}%`, height: `${h * 100}%` }}
                    aria-label={`Track ${t.id}, ${state}, ${name}`}
                    onClick={(e) => { e.stopPropagation(); setSelected(t.id); setMaybe(null); player.current?.pause(); }}
                  >
                    <span>#{t.id} · {state} · {name}</span>
                  </button>
                );
              })}
              {frozen?.boxes.map((b, i) => (
                <button
                  key={`maybe-${b.x}-${b.y}`}
                  className={`fishbox maybe ${i === maybe ? "sel" : ""}`}
                  style={{ left: `${b.x * 100}%`, top: `${b.y * 100}%`, width: `${b.w * 100}%`, height: `${b.h * 100}%` }}
                  aria-label={`Possible fish, ${Math.round(b.conf * 100)}% sure`}
                  onClick={(e) => { e.stopPropagation(); pickMaybe(i); }}
                >
                  <span>Possible · {Math.round(b.conf * 100)}%</span>
                </button>
              ))}
              {draft && <div className={`fishbox draft ${following ? "busy" : ""}`} style={{ left: `${draft.x * 100}%`, top: `${draft.y * 100}%`, width: `${draft.w * 100}%`, height: `${draft.h * 100}%` }} />}
            </div>
            <span className="stamp">{clock(time)} / {clock(video.duration)}</span>
            {addMode && <span className="stage-note" role="status">{following ? "Following the fish through the video…" : <>Adding fish: drag a box around each fish AI missed.<span className="hide-phone"> Esc when done.</span></>}</span>}
          </div>

          <div className="panel row player-controls" style={{ padding: 8 }}>
            <button className="btn" style={{ width: 36, padding: 0 }} onClick={() => step(-JUMP)} title={`Back ${JUMP} frames (Shift + left arrow)`} aria-label={`Back ${JUMP} frames`}>«</button>
            <button className="btn" style={{ width: 36, padding: 0 }} onClick={() => step(-1)} title="Back one frame (left arrow)" aria-label="Back one frame">‹</button>
            <button className="btn" style={{ minWidth: 68 }} onClick={toggle} title="Space">{playing ? "Pause" : "Play"}</button>
            <button className="btn" style={{ width: 36, padding: 0 }} onClick={() => step(1)} title="Forward one frame (right arrow)" aria-label="Forward one frame">›</button>
            <button className="btn" style={{ width: 36, padding: 0 }} onClick={() => step(JUMP)} title={`Forward ${JUMP} frames (Shift + right arrow)`} aria-label={`Forward ${JUMP} frames`}>»</button>
            <select className="run-model num" style={{ width: 84 }} aria-label="Playback speed" title="Playback speed" value={rate} onChange={(e) => setRate(Number(e.target.value))}>
              {RATES.map((r) => <option key={r} value={r}>{r}×</option>)}
            </select>
          </div>

          <div className="video-tools" aria-label="Find fish">
            <button className="btn tool add" aria-pressed={addMode} onClick={() => setAdding(!addMode)}>
              <b>{addMode ? "Done adding" : "Add missed fish"}</b>
              <small>{addMode ? "Esc to stop" : "Drag a box around a fish AI missed"}</small>
              <kbd>{addMode ? "Esc" : "A"}</kbd>
            </button>
            <button className="btn tool redetect" aria-pressed={!!frozen} onClick={() => (frozen ? unfreeze() : freeze())}>
              <b>{frozen ? "Hide redetected" : "Redetect this frame"}</b>
              <small>{frozen ? `${frozen.boxes.length} possible fish left to decide` : "Show fish AI was less sure of"}</small>
              <kbd>F</kbd>
            </button>
            <div className="fish-nav" role="group" aria-label="Step through fish">
              <button className="btn" disabled={!fishOrder.length} onClick={() => goFish(-1)} title="Previous track ([)" aria-label="Previous track">‹</button>
              <span className="fish-count">
                <b className="num"><span className="fish-word">Track </span>{current ? `#${current.id}` : "–"}</b>
                <small className="num">{fishIndex < 0 ? `${fishOrder.length} tracks` : `${fishIndex + 1} of ${fishOrder.length}`}</small>
              </span>
              <button className="btn" disabled={!fishOrder.length} onClick={() => goFish(1)} title="Next track (])" aria-label="Next track">›</button>
            </div>
          </div>

          <div className="panel panel-pad player-timeline">
            <div className="row" style={{ justifyContent: "space-between" }}>
              <span className="meta">AI detections across the video. Click to jump.</span>
              <div className="row">
                <button className="chip" aria-pressed={full} onClick={() => setFull(!full)}>{full ? "Playing through" : "Stop at segment end"}</button>
                <Shortcuts groups={KEYS} />
              </div>
            </div>
            <div className="timeline">
              {seg && <span className="seg-here" style={{ left: `${(seg.start / (video.duration || 1)) * 100}%`, width: `${((seg.end - seg.start) / (video.duration || 1)) * 100}%` }} />}
              {bars.map((b, i) => {
                const s = b.seg;
                const bg = s && s.id === segId ? "var(--accent)" : s?.status === "reviewed" ? "var(--up)" : s?.status === "could_not_see" ? "var(--amber)" : s && s.status === "needs_review" ? "var(--text-2)" : "var(--skip)";
                return <button key={i} aria-label={`Jump to ${clock(b.at)}`} style={{ height: `${b.height}%`, background: bg }} onClick={() => { if (s && s.status !== "skipped") setSegId(s.id); seek(b.at); }} />;
              })}
              <span className="playhead" style={{ left: `${(time / (video.duration || 1)) * 100}%` }} />
            </div>
            <div className="legend" style={{ fontSize: 12 }}>
              <span><i style={{ background: "var(--accent)" }} />This segment</span>
              <span><i style={{ background: "var(--text-2)" }} />In the queue</span>
              <span><i style={{ background: "var(--up)" }} />Reviewed</span>
              <span><i style={{ background: "var(--amber)" }} />Could not see</span>
              <span><i style={{ background: "var(--skip)" }} />Skipped by AI, still reachable</span>
            </div>
          </div>
        </section>

        <aside className="side-col" aria-label="Details">
          {possible && frozen ? (
            <div className="panel panel-pad">
              <div className="row" style={{ justifyContent: "space-between" }}>
                <h2>Possible fish</h2>
                <span className="pill warn">Low confidence</span>
              </div>
              <p className="meta num">Detector {possible.conf.toFixed(2)} · {clock(frozen.t)}</p>
              <p className="meta">AI wasn't sure enough to track this. Confirm it and it's followed through the video and counted, like a fish you added.</p>
              <div className="row">
                <button className="btn primary" style={{ flex: 1 }} disabled={following} onClick={() => settleMaybe(true)}><kbd>C</kbd>Confirm fish</button>
                <button className="btn tall reject" onClick={() => settleMaybe(false)}><kbd>X</kbd>Not a fish</button>
              </div>
            </div>
          ) : current ? (
            <div className="panel panel-pad">
              <div className="row" style={{ justifyContent: "space-between" }}>
                <h2 className="num">Track #{current.id}</h2>
                {current.manual
                  ? <span className="pill accent">Added by you</span>
                  : <span className={`pill ${current.state ? (current.state === "Rejected" ? "down" : "up") : "warn"}`}>{current.state ?? "Suggested"}</span>}
              </div>
              {current.has_crop && <img className="crop" src={`/api/tracks/${current.id}/crop`} alt="Best view of this fish" />}
              <p className="meta num">{current.manual ? `Counted as ${current.decided_species ?? UNIDENTIFIED}` : `Detector ${current.conf.toFixed(2)}`} · {clock(current.first_t)}–{clock(current.last_t)}</p>
              {!!current.manual && current.points.length < 2 && <p className="meta">AI couldn't follow this fish, so its box marks one moment.</p>}
              {!!current.static && !current.state && <p className="meta" style={{ color: "var(--warn)" }}>This barely moves. It may be background, not a fish.</p>}
              {current.candidates.length > 0
                ? <p className="meta">{guess(current) ? "Pick the species to confirm it" : "AI's best guesses, not sure. Pick one if it's right"}</p>
                : <p className="meta">{current.manual ? "AI's species guesses can take a moment. You can type it below." : "Too small for AI to guess the species. Type it below."}</p>}
              {speciesButtons}
              <div className="row" style={{ flexWrap: "nowrap" }}>
                <button className="btn primary" style={{ flex: 1, minWidth: 0 }} aria-pressed={current.decided_species === UNIDENTIFIED} onClick={() => decide(current, UNIDENTIFIED)}>
                  <kbd>C</kbd>Unidentified fish
                </button>
                <button className="btn tall reject" onClick={() => reject(current)}>
                  <kbd>X</kbd>{current.manual ? "Remove this fish" : "Not a fish"}
                </button>
              </div>
              <input
                key={`name-${current.id}`}
                className="name-species"
                list="site-species"
                aria-label="Name the species from the site list"
                placeholder="Name it: type a species from the site list"
                onChange={(e) => {
                  const name = siteSpecies.find((n) => n.toLowerCase() === e.target.value.trim().toLowerCase());
                  if (!name) return;
                  e.target.value = "";
                  e.target.blur();
                  decide(current, name);
                }}
              />
              <datalist id="site-species">{siteSpecies.map((n) => <option key={n} value={n} />)}</datalist>
              <p className="meta">Applies to the whole track.</p>
            </div>
          ) : (
            <div className="panel panel-pad">
              <h2>{seg?.is_dense ? "Dense school" : seg?.low_vis ? "Hard to see" : segTracks.length ? "All tracks decided" : "No AI suggestions here"}</h2>
              <p style={{ color: "var(--text-2)", fontSize: 13 }}>
                {seg?.is_dense ? "Freeze the frame to see fish AI was less sure of." : seg?.low_vis ? "If you can't read this footage, mark it Could not see." : segTracks.length ? "Move on, or add a fish AI missed." : "Watch this segment. If you spot a fish, add it."}
              </p>
            </div>
          )}

          <div className="panel panel-pad side-actions" aria-label="This segment">
            {undecided.length > 0 && <p className="meta" style={{ color: "var(--warn)" }}>{undecided.length} undecided will stay out of results.</p>}
            <button className="btn" onClick={() => finish("could_not_see")}>Could not see</button>
            <button className="btn primary" onClick={() => finish("reviewed")}><kbd>N</kbd>Mark reviewed, next</button>
          </div>
        </aside>
      </div>
      {toast && <div className="toast" role="status">{toast}</div>}
    </div>
  );
}
