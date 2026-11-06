import { MouseEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api, Candidate, clock, Segment, Track, VideoDetail } from "./api";
import { pos } from "./tracks";

const UNIDENTIFIED = "Fish, unidentified";
const RATES = [0.5, 1, 2, 4];
const FRAME = 1 / 30;

const nameOf = (c: Candidate) => c.common;
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
  const [toast, setToast] = useState("");
  const [checked, setChecked] = useState<number[]>([]);
  const history = useRef<number[]>([]);

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
      setSegId(queue.find((s) => s.id === wanted)?.id ?? queue.find((s) => s.status === "needs_review")?.id ?? queue[0]?.id ?? null);
    });
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
    setAddMode(false);
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
    const state = t.candidates[0] && nameOf(t.candidates[0]) === species ? "Confirmed" : "Corrected";
    patch(t.id, state, species);
    history.current.push(t.id);
    nextOpen(t.id);
    await api.decide(t.id, state, species);
  }, [segTracks]);

  const reject = useCallback(async (t: Track) => {
    patch(t.id, "Rejected", null);
    history.current.push(t.id);
    nextOpen(t.id);
    await api.decide(t.id, "Rejected", null);
  }, [segTracks]);

  const undo = useCallback(async () => {
    const last = history.current.pop();
    if (!last) return flash("Nothing to undo");
    patch(last, null, null);
    setSelected(last);
    await api.undo(last);
    flash("Decision undone");
  }, []);

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
      const species = t.candidates[0] ? nameOf(t.candidates[0]) : UNIDENTIFIED;
      return { t, state: (reject ? "Rejected" : t.candidates[0] ? "Confirmed" : "Corrected") as Track["state"], species: reject ? null : species };
    });
    setTracks((all) => all.map((t) => {
      const plan = plans.find((p) => p.t.id === t.id);
      return plan ? { ...t, state: plan.state, decided_species: plan.species } : t;
    }));
    plans.forEach((p) => history.current.push(p.t.id));
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

  const onStage = async (e: MouseEvent<HTMLDivElement>) => {
    if (!addMode) return;
    const box = e.currentTarget.getBoundingClientRect();
    const x = (e.clientX - box.left) / box.width - 0.05;
    const y = (e.clientY - box.top) / box.height - 0.04;
    const t = player.current?.currentTime ?? time;
    const { id: trackId } = await api.addFish(id, t, x, y);
    setAddMode(false);
    setTracks(await api.tracks(id));
    setSelected(trackId);
    history.current.push(trackId);
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).tagName === "INPUT") return;
      const key = e.key.toLowerCase();
      if (key === " ") { e.preventDefault(); toggle(); }
      else if (key === "arrowleft") step(-1);
      else if (key === "arrowright") step(1);
      else if (key === "z") undo();
      else if (key === "b") setBoxes((v) => !v);
      else if (key === "g") setGrid((v) => !v);
      else if (key === "a") setAddMode((v) => !v);
      else if (key === "n") finish("reviewed");
      else if (current) {
        if (key === "c") decide(current, current.candidates[0] ? nameOf(current.candidates[0]) : UNIDENTIFIED);
        else if (key === "x") reject(current);
        else if (key === "u") decide(current, UNIDENTIFIED);
        else if (["1", "2", "3"].includes(key) && current.candidates[+key - 1]) decide(current, nameOf(current.candidates[+key - 1]));
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const visible = useMemo(() => tracks.flatMap((t) => {
    if (t.state === "Rejected") return [];
    const p = pos(t, time);
    return p ? [{ track: t, box: p }] : [];
  }), [tracks, time]);

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
  const done = queue.filter((s) => s.status !== "needs_review").length;
  const toWatch = queue.reduce((n, s) => n + s.end - s.start, 0);
  const filter = [gray ? "grayscale(1)" : "", enhance ? "contrast(1.35) brightness(1.2) saturate(1.2)" : ""].join(" ").trim() || "none";

  return (
    <div className="stack">
      <div className="row">
        <Link className="btn" to="/">← All videos</Link>
        <h2>{video.name}{video.site ? `, ${video.site}` : ""}</h2>
        <span className="spacer" />
        <span className="num meta">{done} of {queue.length} segments done</span>
        <Link className="btn" to={`/videos/${id}/compare`}>Compare models</Link>
        <Link className="btn" to={`/videos/${id}/summary`}>Summary</Link>
      </div>

      <div className="workspace">
        <section className="panel queue" aria-label="Review queue">
          <div className="panel-head">
            <h2>Review queue</h2>
            <p className="num meta">{clock(toWatch)} to watch of {clock(video.duration)}</p>
          </div>
          {queue.map((s) => {
            const label = segLabel(s);
            const fish = tracks.filter((t) => inSeg(t, s) && t.state !== "Rejected").length;
            return (
              <button key={s.id} className="queue-item" aria-pressed={s.id === segId} onClick={() => setSegId(s.id)}>
                <span className="num" style={{ fontSize: 13, fontWeight: 600 }}>{clock(s.start)}–{clock(s.end)}</span>
                <span className="meta">
                  {s.is_dense ? "Dense school" : s.low_vis ? "Low visibility" : s.kind === "active" ? "AI detections" : "No AI detections"}
                  {fish ? ` · ${fish} AI ${fish === 1 ? "track" : "tracks"}` : ""}
                </span>
                <span className={`pill ${label.tone}`}>{label.text}</span>
              </button>
            );
          })}
        </section>

        <section className="stack" aria-label="Video">
          <div className="stage" style={{ aspectRatio: `${video.width || 16} / ${video.height || 9}`, cursor: addMode ? "crosshair" : "default" }} onClick={onStage}>
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
                const name = t.decided_species ?? (t.candidates[0] ? `${nameOf(t.candidates[0])}?` : "Fish?");
                const state = t.state ?? "Suggested";
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
            </div>
            <span className="stamp">{clock(time)} / {clock(video.duration)}</span>
            {addMode && <span className="stage-note">Click the fish to add it</span>}
          </div>

          <div className="panel row" style={{ padding: 8 }}>
            <button className="btn" onClick={() => step(-1)} title="Left arrow">−1 frame</button>
            <button className="btn" style={{ minWidth: 68 }} onClick={toggle} title="Space">{playing ? "Pause" : "Play"}</button>
            <button className="btn" onClick={() => step(1)} title="Right arrow">+1 frame</button>
            {RATES.map((r) => <button key={r} className="chip num" aria-pressed={rate === r} onClick={() => setRate(r)}>{r}×</button>)}
            <span className="spacer" />
            <button className="chip" aria-pressed={boxes} onClick={() => setBoxes(!boxes)}>AI boxes</button>
            <button className="chip" aria-pressed={grid} onClick={() => setGrid(!grid)}>Grid</button>
            <button className="chip" aria-pressed={enhance} onClick={() => setEnhance(!enhance)}>Enhance</button>
            <button className="chip" aria-pressed={gray} onClick={() => setGray(!gray)}>Grayscale</button>
          </div>

          <div className="panel panel-pad">
            <div className="row" style={{ justifyContent: "space-between" }}>
              <span className="meta">AI detections across the video. Click to jump.</span>
              <button className="chip" aria-pressed={full} onClick={() => setFull(!full)}>{full ? "Playing through" : "Stop at segment end"}</button>
            </div>
            <div className="timeline">
              {bars.map((b, i) => {
                const s = b.seg;
                const bg = s && s.id === segId ? "var(--accent)" : s?.status === "reviewed" ? "var(--up)" : s?.status === "could_not_see" ? "var(--warn)" : s && s.status === "needs_review" ? "var(--text-2)" : "#d5dbe5";
                return <button key={i} aria-label={`Jump to ${clock(b.at)}`} style={{ height: `${b.height}%`, background: bg }} onClick={() => { if (s && s.status !== "skipped") setSegId(s.id); seek(b.at); }} />;
              })}
              <span className="playhead" style={{ left: `${(time / (video.duration || 1)) * 100}%` }} />
            </div>
            <div className="row meta" style={{ gap: 16 }}><span>Dark: in queue</span><span>Pale: skipped, still reachable</span><span>Green: reviewed</span><span>Blue: current</span></div>
          </div>
        </section>

        <aside className="stack" aria-label="Details">
          {current ? (
            <div className="panel panel-pad">
              <div className="row" style={{ justifyContent: "space-between" }}>
                <h2 className="num">Track #{current.id}</h2>
                <span className={`pill ${current.state ? (current.state === "Rejected" ? "down" : "up") : "warn"}`}>{current.state ?? "Suggested"}</span>
              </div>
              {current.has_crop && <img className="crop" src={`/api/tracks/${current.id}/crop`} alt="Best view of this fish" />}
              <p className="meta num">{current.manual ? "Added by you" : `Detector ${current.conf.toFixed(2)}`} · {clock(current.first_t)}–{clock(current.last_t)}</p>
              {!!current.static && !current.state && <p className="meta" style={{ color: "var(--warn)" }}>This barely moves. It may be background, not a fish.</p>}
              {!!current.candidates.length && <p className="meta">Suggested species, from the site list</p>}
              {current.candidates.map((c, i) => (
                <button key={c.species} className="species" aria-pressed={current.decided_species === nameOf(c)} onClick={() => decide(current, nameOf(c))}>
                  <span>{i + 1}. {nameOf(c)}</span><span className="num meta">{Math.round(c.score * 100)}%</span>
                </button>
              ))}
              <button className="btn tall" onClick={() => decide(current, UNIDENTIFIED)}>Fish, unidentified</button>
              <div className="row">
                <button className="btn primary" style={{ flex: 1 }} onClick={() => decide(current, current.candidates[0] ? nameOf(current.candidates[0]) : UNIDENTIFIED)}>Confirm</button>
                <button className="btn tall" onClick={() => reject(current)}>Not a fish</button>
              </div>
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
                      <span className="num">#{t.id}</span> {t.decided_species ?? (t.candidates[0] ? nameOf(t.candidates[0]) : "Fish")}
                      <small>{t.state ?? (t.static ? "Barely moves" : "Suggested")} · {clock(t.first_t)}</small>
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

          <div className="panel panel-pad">
            <button className="btn tall" onClick={school}>Freeze frame and count school</button>
            <button className="btn tall" onClick={() => setAddMode(!addMode)}>{addMode ? "Cancel add" : "Add missed fish"}</button>
            <button className="btn tall" onClick={() => finish("could_not_see")}>Could not see</button>
            <button className="btn primary" onClick={() => finish("reviewed")}>Mark reviewed, next</button>
            {undecided.length > 0 && <p className="meta" style={{ color: "var(--warn)" }}>{undecided.length} undecided will stay out of results.</p>}
          </div>

          <div className="panel">
            <div className="panel-head"><h2>Confirmed so far</h2></div>
            {tally.map(([name, n]) => <div className="tally" key={name}><span>{name}</span><span className="num">{n}</span></div>)}
            {!tally.length && <p className="meta" style={{ padding: 12 }}>Nothing confirmed yet. AI suggestions don't count.</p>}
          </div>

          <p className="keys">Space play · ← → frame · C confirm · X reject<br />1 2 3 species · U unidentified · Z undo<br />A add · G grid · B boxes · N next</p>
        </aside>
      </div>
      {toast && <div className="toast" role="status">{toast}</div>}
    </div>
  );
}
