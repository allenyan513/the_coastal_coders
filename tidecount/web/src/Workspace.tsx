import { PointerEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api, clock, Segment, Track, VideoDetail } from "./api";
import { guess, nameOf, pos, stateFor, topName, UNIDENTIFIED } from "./trackHelpers";
import { KeyGroup, Shortcuts } from "./Shortcuts";
import { VideoHeader } from "./VideoHeader";

const RATES = [0.25, 0.5, 1, 2, 4];
const FRAME = 1 / 30;
const KEYS: KeyGroup[] = [
  { title: "Video", keys: [["Space", "Play or pause"], ["← →", "Step one frame"], ["B", "Show or hide AI boxes"], ["G", "Show or hide the grid"]] },
  { title: "The selected track", keys: [["C", "Confirm"], ["X", "Not a fish, or remove a fish you added"], ["1 2 3", "Name it with a suggestion"], ["U", "Fish, unidentified"], ["Z", "Undo the last decision or added fish"]] },
  { title: "The segment", keys: [["A", "Add fish AI missed: drag a box around each"], ["Esc", "Stop adding"], ["N", "Mark reviewed and go to the next"]] },
];
/** A click with no drag still adds a fish, with a box this size around the click. */
const CLICK_BOX = { w: 0.1, h: 0.08 };
type Past = { id: number; added?: boolean };
type Rect = { x: number; y: number; w: number; h: number };

const inSeg = (t: Track, s: Segment) => t.first_t < s.end && t.last_t > s.start;

function segLabel(s: Segment) {
  if (s.status === "could_not_see") return { text: "Could not see", tone: "warn" };
  if (s.status === "reviewed") return s.is_audit ? { text: "Audit, reviewed", tone: "accent" } : { text: "Reviewed", tone: "up" };
  return { text: "Needs review", tone: "muted" };
}

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
  const [gray, setGray] = useState(false);
  const [enhance, setEnhance] = useState(false);
  const [full, setFull] = useState(false);
  const [addMode, setAddMode] = useState(false);
  const [draft, setDraft] = useState<Rect | null>(null);
  const [following, setFollowing] = useState(false);
  const [siteSpecies, setSiteSpecies] = useState<string[]>([]);
  const [toast, setToast] = useState("");
  const [checked, setChecked] = useState<number[]>([]);
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
    setChecked([]);
    api.event(id, "segment_open", { segment: seg.id });
  }, [segId]);

  useEffect(() => {
    if (!seg || full || !playing || !player.current) return;
    if (time >= seg.end) player.current.pause();
  }, [time, seg, full, playing]);

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

  const nextOpen = (afterId: number) => {
    const rest = segTracks.filter((t) => !t.state && t.id !== afterId);
    setSelected(rest[0]?.id ?? null);
    if (rest[0]) {
      player.current?.pause();
      seek(rest[0].first_t);
    }
  };

  const decide = useCallback(async (t: Track, species: string) => {
    const state = stateFor(t, species);
    patch(t.id, state, species);
    history.current.push({ id: t.id });
    if (!t.manual) nextOpen(t.id);  // a fish a person added stays selected, so its new name is seen
    await api.decide(t.id, state, species);
  }, [segTracks]);

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
    nextOpen(t.id);
    await api.decide(t.id, "Rejected", null);
  }, [segTracks, remove]);

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

  const toggleChecked = (trackId: number) =>
    setChecked((all) => (all.includes(trackId) ? all.filter((n) => n !== trackId) : [...all, trackId]));

  const mergeChecked = async () => {
    const { id: kept } = await api.merge(checked);
    setTracks(await api.tracks(id));
    setSelected(kept);
    setChecked([]);
    history.current = [];
    flash(`Merged ${checked.length} tracks into one fish`);
  };

  const applyChecked = async (reject: boolean) => {
    const picked = tracks.filter((t) => checked.includes(t.id));
    const plans = picked.map((t) => {
      const species = topName(t);
      return { t, state: (reject ? "Rejected" : stateFor(t, species)) as Track["state"], species: reject ? null : species };
    });
    setTracks((all) => all.map((t) => {
      const plan = plans.find((p) => p.t.id === t.id);
      return plan ? { ...t, state: plan.state, decided_species: plan.species } : t;
    }));
    plans.forEach((p) => history.current.push({ id: p.t.id }));
    setChecked([]);
    await Promise.all(plans.map((p) => api.decide(p.t.id, p.state as string, p.species)));
  };

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

  const school = () => {
    player.current?.pause();
    navigate(`/videos/${id}/school?t=${player.current?.currentTime ?? time}&seg=${seg?.id ?? ""}`);
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
    setFollowing(true);
    try {
      const added = await api.addFish(id, player.current?.currentTime ?? time, box);
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
    setDraft(null);
    setFollowing(false);
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (["INPUT", "SELECT", "TEXTAREA"].includes((e.target as HTMLElement).tagName)) return;
      const key = e.key.toLowerCase();
      if (key === " ") { e.preventDefault(); toggle(); }
      else if (key === "arrowleft") step(-1);
      else if (key === "arrowright") step(1);
      else if (key === "z") undo();
      else if (key === "b") setBoxes((v) => !v);
      else if (key === "g") setGrid((v) => !v);
      else if (key === "a") setAdding(!addMode);
      else if (key === "escape") setAdding(false);
      else if (key === "n") finish("reviewed");
      else if (current) {
        if (key === "c") { if (!current.manual) decide(current, topName(current)); }  // an added fish is counted already
        else if (key === "x") reject(current);
        else if (key === "u") decide(current, UNIDENTIFIED);
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

  const tally = useMemo(() => {
    const counts = new Map<string, number>();
    tracks.forEach((t) => {
      if (t.decided_species && t.state !== "Rejected") counts.set(t.decided_species, (counts.get(t.decided_species) ?? 0) + 1);
    });
    return [...counts].sort((a, b) => b[1] - a[1]);
  }, [tracks]);

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
  const toWatch = queue.reduce((n, s) => n + s.end - s.start, 0);
  const filter = [gray ? "grayscale(1)" : "", enhance ? "contrast(1.35) brightness(1.2) saturate(1.2)" : ""].join(" ").trim() || "none";

  return (
    <div className="stack review-page">
      <VideoHeader id={id} step="review" view="segments" review={{ done, total: queue.length }} />

      <div className="workspace">
        <section className="panel queue" aria-label="Review queue">
          <div className="panel-head">
            <h2>Review queue</h2>
            <p className="num meta">{clock(toWatch)} to watch of {clock(video.duration)}</p>
          </div>
          {queue.map((s) => {
            const label = segLabel(s);
            const here = tracks.filter((t) => inSeg(t, s) && t.state !== "Rejected");
            const added = here.filter((t) => t.manual).length;
            const fish = here.length - added;
            return (
              <button key={s.id} className="queue-item" aria-pressed={s.id === segId} onClick={() => setSegId(s.id)}>
                <span className="num" style={{ fontSize: 13, fontWeight: 600 }}>{clock(s.start)}–{clock(s.end)}</span>
                <span className="meta">
                  {s.is_dense ? "Dense school" : s.low_vis ? "Low visibility" : s.kind === "active" ? "AI detections" : "No AI detections"}
                  {fish ? ` · ${fish} AI ${fish === 1 ? "track" : "tracks"}` : ""}
                  {added ? ` · ${added} added by you` : ""}
                </span>
                <span className={`pill ${label.tone}`}>{label.text}</span>
              </button>
            );
          })}
        </section>

        <section className="stack review-mid" aria-label="Video">
          <div
            className={`stage ${addMode ? "adding" : ""}`}
            style={{ aspectRatio: `${ratio}`, width: `min(100%, max(320px, calc((100vh - 380px) * ${ratio})))` }}
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
                    onClick={(e) => { e.stopPropagation(); setSelected(t.id); player.current?.pause(); }}
                  >
                    <span>#{t.id} · {state} · {name}</span>
                  </button>
                );
              })}
              {draft && <div className={`fishbox draft ${following ? "busy" : ""}`} style={{ left: `${draft.x * 100}%`, top: `${draft.y * 100}%`, width: `${draft.w * 100}%`, height: `${draft.h * 100}%` }} />}
            </div>
            <span className="stamp">{clock(time)} / {clock(video.duration)}</span>
            {addMode && <span className="stage-note" role="status">{following ? "Following the fish through the video…" : <>Adding fish: drag a box around each fish AI missed.<span className="hide-phone"> Esc when done.</span></>}</span>}
          </div>

          <div className="panel row player-controls" style={{ padding: 8 }}>
            <button className="btn" style={{ width: 36, padding: 0 }} onClick={() => step(-1)} title="Back one frame (left arrow)" aria-label="Back one frame">‹</button>
            <button className="btn" style={{ minWidth: 68 }} onClick={toggle} title="Space">{playing ? "Pause" : "Play"}</button>
            <button className="btn" style={{ width: 36, padding: 0 }} onClick={() => step(1)} title="Forward one frame (right arrow)" aria-label="Forward one frame">›</button>
            <select className="run-model num" style={{ width: 96 }} aria-label="Playback speed" value={rate} onChange={(e) => setRate(Number(e.target.value))}>
              {RATES.map((r) => <option key={r} value={r}>{r}× speed</option>)}
            </select>
            <span className="spacer" />
            <button className="chip" aria-pressed={boxes} onClick={() => setBoxes(!boxes)}>AI boxes</button>
            <button className="chip" aria-pressed={grid} onClick={() => setGrid(!grid)}>Grid</button>
            <button className="chip" aria-pressed={enhance} onClick={() => setEnhance(!enhance)}>Enhance</button>
            <button className="chip" aria-pressed={gray} onClick={() => setGray(!gray)}>Grayscale</button>
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
          <div className="side-scroll">
          {current ? (
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
              {guess(current) && <p className="meta">Suggested species, from the site list</p>}
              {guess(current) && speciesButtons}
              {guess(current) && <button className="btn tall" onClick={() => decide(current, UNIDENTIFIED)}>Fish, unidentified</button>}
              {!current.manual && (
                <div className="row">
                  <button className="btn primary" style={{ flex: 1 }} onClick={() => decide(current, topName(current))}><kbd>C</kbd>{guess(current) ? `Confirm ${guess(current)}` : "Confirm fish"}</button>
                  <button className="btn tall" onClick={() => reject(current)}><kbd>X</kbd>Not a fish</button>
                </div>
              )}
              {!guess(current) && !!current.candidates.length && (
                <details className="guesses" key={current.id}>
                  <summary>Name the species. AI isn't sure, so its guesses are hidden.</summary>
                  <div className="stack" style={{ gap: 8 }}>{speciesButtons}</div>
                </details>
              )}
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
              {!!current.manual && <button className="btn" onClick={() => remove(current.id)}><kbd>X</kbd>Remove this fish</button>}
              <button className="btn" onClick={() => { player.current?.pause(); seek(current.first_t); }}>Show this fish in the video</button>
              <p className="meta">Applies to the whole track.</p>
            </div>
          ) : (
            <div className="panel panel-pad">
              <h2>{seg?.is_dense ? "Dense school" : seg?.low_vis ? "Hard to see" : segTracks.length ? "All tracks decided" : "No AI suggestions here"}</h2>
              <p style={{ color: "var(--text-2)", fontSize: 13 }}>
                {seg?.is_dense ? "Freeze a frame and count with dots." : seg?.low_vis ? "If you can't read this footage, mark it Could not see." : segTracks.length ? "Move on, or add a fish AI missed." : "Watch this segment. If you spot a fish, add it."}
              </p>
            </div>
          )}

          {segTracks.length > 0 && (
            <div className="panel">
              <div className="panel-head">
                <h2>Tracks in this segment</h2>
                <p className="meta">Tick pieces of one fish to merge them, or tick several to decide together.</p>
              </div>
              <div className="tracklist">
                {segTracks.map((t) => (
                  <label key={t.id} className={`trackrow ${t.id === selected ? "on" : ""}`}>
                    <input type="checkbox" checked={checked.includes(t.id)} onChange={() => toggleChecked(t.id)} />
                    {t.has_crop ? <img src={`/api/tracks/${t.id}/crop`} alt="" /> : <span className="nocrop" />}
                    <button
                      className="trackname"
                      onClick={(e) => { e.preventDefault(); setSelected(t.id); player.current?.pause(); seek(t.first_t); }}
                    >
                      <span className="num">#{t.id}</span> {t.decided_species ?? guess(t) ?? "Fish"}
                      <small>{t.manual ? "Added by you" : t.state ?? (t.static ? "Barely moves" : "Suggested")} · {clock(t.first_t)}</small>
                    </button>
                  </label>
                ))}
              </div>
              {checked.length > 0 && (
                <div className="panel-pad">
                  <button className="btn" disabled={checked.length < 2} onClick={mergeChecked}>Same fish, merge {checked.length}</button>
                  <div className="row">
                    <button className="btn" style={{ flex: 1 }} onClick={() => applyChecked(false)}>Confirm {checked.length}</button>
                    <button className="btn" style={{ flex: 1 }} onClick={() => applyChecked(true)}>Not fish</button>
                  </div>
                </div>
              )}
            </div>
          )}

          <div className="panel">
            <div className="panel-head"><h2>Confirmed so far</h2></div>
            {tally.map(([name, n]) => <div className="tally" key={name}><span>{name}</span><span className="num">{n}</span></div>)}
            {!tally.length && <p className="meta" style={{ padding: 12 }}>Nothing confirmed yet. AI suggestions don't count.</p>}
          </div>

          </div>

          <div className="panel panel-pad side-actions" aria-label="This segment">
            {undecided.length > 0 && <p className="meta" style={{ color: "var(--warn)" }}>{undecided.length} undecided will stay out of results.</p>}
            <div className="row" style={{ flexWrap: "nowrap" }}>
              <button className="btn" style={{ flex: 1 }} aria-pressed={addMode} onClick={() => setAdding(!addMode)}><kbd>{addMode ? "Esc" : "A"}</kbd>{addMode ? "Done adding" : "Add missed fish"}</button>
              <button className="btn" style={{ flex: 1 }} onClick={() => finish("could_not_see")}>Could not see</button>
            </div>
            <button className="btn" onClick={school}>Freeze frame and count school</button>
            <button className="btn primary" onClick={() => finish("reviewed")}><kbd>N</kbd>Mark reviewed, next</button>
          </div>
        </aside>
      </div>
      {toast && <div className="toast" role="status">{toast}</div>}
    </div>
  );
}
