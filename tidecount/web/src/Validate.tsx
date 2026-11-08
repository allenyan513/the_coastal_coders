import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { clock, Dot, snapshotApi, SnapshotList, Validation, validationApi, ValidationPoint } from "./api";
import { DotStage } from "./Dots";
import { Magnifier } from "./Magnifier";
import { PicturePanel, pictureFilter, SharpenFilter, usePicture } from "./Picture";
import { useUser } from "./session";
import { KeyGroup, Shortcuts } from "./Shortcuts";
import { VideoHeader } from "./VideoHeader";

/**
 * Validate, from the protocol's quality control: a second person blind-counts a random sample of the
 * counted points. They never see AI's dots or the first count until they've saved their own. Counts
 * more than the allowed share apart are counted again, and a manager approves once every point agrees.
 */
const KEYS: KeyGroup[] = [
  { title: "This point", keys: [["N", "Save my count"], ["Z", "Undo the last dot"]] },
  { title: "Move", keys: [["← →", "Previous or next point"]] },
  { title: "View", keys: [["D", "Show or hide my dots"], ["M", "Zoom: a magnifying glass over the frame"], ["Space", "Play the seconds around the frame"]] },
];
const CLIP_RATES = [0.25, 0.5, 1];
const STATE = {
  to_count: { text: "To count", tone: "muted" },
  agree: { text: "Agrees", tone: "up" },
  recount: { text: "Recount", tone: "warn" },
} as const;
const pct = (v: number) => `${+(v * 100).toFixed(1)}%`;

export function Validate() {
  const { id = "" } = useParams();
  const user = useUser();
  const [list, setList] = useState<SnapshotList | null>(null);
  const [v, setV] = useState<Validation | null>(null);
  const [error, setError] = useState("");
  const [currentId, setCurrentId] = useState<number | null>(null);
  const [drafts, setDrafts] = useState<Record<number, Dot[]>>({});
  // Which frame has loaded or failed, so a cached frame that loads before an effect runs still counts.
  const [loaded, setLoaded] = useState<{ id: number | null; ok: boolean }>({ id: null, ok: false });
  const [showDots, setShowDots] = useState(true);
  const [zoom, setZoom] = useState(false);
  const [picture, setPicture] = usePicture();
  const [original, setOriginal] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [clipRate, setClipRate] = useState(CLIP_RATES[0]);
  const [toast, setToast] = useState("");
  const [busy, setBusy] = useState(false);
  const clip = useRef<HTMLVideoElement>(null);
  const timer = useRef<ReturnType<typeof setTimeout>>();

  const flash = (msg: string) => {
    setToast(msg);
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setToast(""), 2600);
  };

  useEffect(() => {
    snapshotApi.list(id).then(setList).catch((e) => setError(e.message));
    validationApi.report(id, user.name).then((r) => {
      setV(r);
      // Start at the first point this person can still count, else the first point.
      const open = r.points.find((p) => canCountPoint(p, r, user.name)) ?? r.points[0];
      setCurrentId(open?.id ?? null);
    }).catch((e) => setError(e.message));
  }, [id, user.name]);

  useEffect(() => { setPlaying(false); }, [currentId]);
  const image = loaded.id !== currentId ? "loading" : loaded.ok ? "ready" : "failed";

  const points = v?.points ?? [];
  const at = points.findIndex((p) => p.id === currentId);
  const point = at >= 0 ? points[at] : null;
  const mine = currentId !== null ? drafts[currentId] ?? [] : [];
  const canCount = !!point && !!v && canCountPoint(point, v, user.name);
  const ownPoint = !!point?.original_counter && point.original_counter === user.name;
  const agreeing = points.filter((p) => p.state === "agree").length;
  const recounts = points.filter((p) => p.state === "recount").length;

  const setMine = (next: Dot[]) => currentId !== null && setDrafts((d) => ({ ...d, [currentId]: next }));
  const step = (dir: 1 | -1) => {
    const next = points[at + dir];
    if (next) setCurrentId(next.id);
  };
  const playClip = () => {
    const el = clip.current;
    if (!el) return;
    if (playing) { el.pause(); setPlaying(false); return; }
    el.currentTime = 0;
    el.playbackRate = clipRate;
    setPlaying(true);
    el.play().catch(() => setPlaying(false));
  };

  const save = async () => {
    if (!point || !canCount || busy || image !== "ready") return;
    setBusy(true);
    try {
      const next = await validationApi.save(point.id, user.name, mine);
      setV(next);
      setDrafts((d) => { const { [point.id]: _, ...rest } = d; return rest; });
      const now = next.points.find((p) => p.id === point.id);
      flash(now?.state === "agree" ? "Saved. The counts agree." : now?.state === "recount" ? "Saved. The counts are too far apart, so this point needs a recount." : "Saved.");
      const open = next.points.find((p) => p.id !== point.id && canCountPoint(p, next, user.name));
      if (open && now?.state === "agree") setCurrentId(open.id);
    } catch (e) {
      flash((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const approve = async () => {
    setBusy(true);
    try {
      setV(await validationApi.approve(id, user.name, user.role));
      flash("Approved. The report is final.");
    } catch (e) {
      flash((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null;
      if (e.ctrlKey || e.metaKey || e.altKey || el?.closest?.("input, textarea, select")) return;
      const key = e.key.toLowerCase();
      if (key === "arrowleft") step(-1);
      else if (key === "arrowright") step(1);
      else if (key === "n") save();
      else if (key === "z" && mine.length) setMine(mine.slice(0, -1));
      else if (key === "d") setShowDots((x) => !x);
      else if (key === "m") setZoom((x) => !x);
      else if (key === " ") { e.preventDefault(); playClip(); }
      else return;
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const progress = { done: agreeing, total: points.length };
  const header = (
    <VideoHeader
      id={id}
      step="validate"
      validate={v?.ready ? progress : undefined}
      actions={
        <div className="count-top">
          {v?.ready && (
            <span className="val-top num">
              <b>{agreeing}</b> of {points.length} points agree{recounts ? <span className="val-warn"> · {recounts} to recount</span> : null}
            </span>
          )}
          <Shortcuts groups={KEYS} />
        </div>
      }
    />
  );

  if (error) return <div className="stack">{header}<p className="meta">{error}</p></div>;
  if (!v || !list) return <div className="stack">{header}<p className="meta">Loading…</p></div>;
  if (!v.ready) {
    return (
      <div className="stack">
        {header}
        <section className="panel val-empty">
          <h2>Not ready to validate</h2>
          <p className="meta">{v.reason} Then {v.sample_size} of the counted points are picked at random for a second, blind count.</p>
          <Link className="btn primary" to={`/videos/${id}/snapshots`}>Go to Count</Link>
        </section>
      </div>
    );
  }

  const video = list.video;
  const context = list.protocol.context_s;
  const limit = pct(v.max_difference);

  return (
    <div className="stack count-page">
      {header}
      <SharpenFilter id="val-sharpen" amount={picture.sharpness} />
      <div className="split count-split" style={{ "--ratio": (video.width || 16) / (video.height || 9) } as React.CSSProperties}>
        <div className="count-view" style={{ "--pic": original ? "none" : pictureFilter(picture, "val-sharpen") } as React.CSSProperties}>
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
              <span>My dots</span><kbd className="switch-key">D</kbd>
            </label>
          </PicturePanel>
          <button className="count-nav" disabled={at <= 0} onClick={() => step(-1)} aria-label="Previous point" title="Previous point (←)">‹</button>
          <div className={`count-col ${zoom ? "zooming" : ""}`}>
            <DotStage
              key={currentId}
              src={snapshotApi.image(currentId ?? 0)}
              dots={canCount ? mine : []}
              showDots={showDots && !playing}
              showGrid={false}
              aspect={`${video.width || 16} / ${video.height || 9}`}
              onAdd={(x, y) => {
                if (playing) { clip.current?.pause(); setPlaying(false); return; }
                if (!canCount) return flash(ownPoint ? "You counted this point, so someone else has to validate it." : "This point doesn't need another count.");
                setMine([...mine, { x, y, source: "user" }]);
              }}
              onRemove={(dot) => setMine(mine.filter((d) => d !== dot))}
              onLoad={() => setLoaded({ id: currentId, ok: true })}
              onError={() => setLoaded({ id: currentId, ok: false })}
            >
              <video
                ref={clip}
                className="clip"
                src={currentId ? snapshotApi.clip(currentId) : undefined}
                muted
                playsInline
                preload="auto"
                style={{ display: playing ? "block" : "none" }}
                onEnded={() => setPlaying(false)}
                onError={() => { setPlaying(false); flash("This clip can't be played."); }}
              />
              {image === "failed" && <span className="stage-note">This frame can't be read.</span>}
              {zoom && !playing && image === "ready" && (
                <Magnifier src={snapshotApi.image(currentId ?? 0)} dots={showDots && canCount ? mine.map((d) => ({ x: d.x, y: d.y, className: "dot user" })) : []} />
              )}
            </DotStage>

            <div className="panel count-bar">
              <button className={`btn ${playing ? "" : "go"} count-play`} onClick={playClip}>
                {playing ? "■ Stop" : `▶ Play ±${context} s`}
              </button>
              <div className="row count-speed" role="group" aria-label="Clip speed">
                {CLIP_RATES.map((r) => (
                  <button key={r} className="chip" aria-pressed={clipRate === r} onClick={() => { setClipRate(r); if (clip.current) clip.current.playbackRate = r; }}>{r}×</button>
                ))}
              </div>
              <span className="count-time num">{point ? `${clock(point.t)} / ${clock(video.duration)}` : "…"}</span>
              <div className="val-strip" role="tablist" aria-label="Sampled points">
                {points.map((p, i) => (
                  <button
                    key={p.id}
                    role="tab"
                    aria-selected={p.id === currentId}
                    className={`val-chip ${p.state}`}
                    onClick={() => setCurrentId(p.id)}
                    title={`Point ${p.number} at ${clock(p.t)}: ${STATE[p.state].text}`}
                  >
                    <b className="num">{i + 1}</b>
                    <span className="num">{clock(p.t)}</span>
                    <i aria-hidden />
                  </button>
                ))}
              </div>
            </div>
          </div>
          <button className="count-nav" disabled={at < 0 || at >= points.length - 1} onClick={() => step(1)} aria-label="Next point" title="Next point (→)">›</button>
        </div>

        <aside className="count-side">
          {point && (
            <div className="panel count-card">
              <div className="row" style={{ justifyContent: "space-between" }}>
                <b className="count-where">
                  Sample {at + 1} of {points.length}
                  <span className="meta num"> · point {point.number} at {clock(point.t)}</span>
                </b>
                <span className={`pill ${STATE[point.state].tone}`}>{STATE[point.state].text}</span>
              </div>

              {canCount ? (
                <>
                  <div className="count-total">
                    <span className="num">{mine.length}</span>
                    <small>fish you've marked</small>
                  </div>
                  <p className="meta count-hint">
                    {point.state === "recount"
                      ? `The counts are more than ${limit} apart, so this point is counted again, preferably by someone who hasn't counted it yet. `
                      : "Count on your own: AI's dots and the first count stay hidden until you save, so they can't sway you. "}
                    Click each fish. Click a dot to remove it.
                  </p>
                  <button className="btn primary count-save" disabled={image !== "ready" || busy} onClick={save}>
                    Save my count<kbd>N</kbd>
                  </button>
                </>
              ) : (
                <p className="meta count-hint">
                  {v.approval
                    ? "The video is approved, so its counts are final."
                    : ownPoint
                      ? "You counted this point on the Count tab, so someone else has to validate it."
                      : point.state === "agree"
                        ? "The counts agree, so this point is done."
                        : "Nothing for you to count here."}
                </p>
              )}

              <Comparison point={point} limit={v.max_difference} />
            </div>
          )}

          <div className="panel val-approve">
            {v.approval ? (
              <>
                <span className="pill up">Approved</span>
                <p>Approved by <b>{v.approval.approver}</b> on {new Date(`${v.approval.approved_at.replace(" ", "T")}Z`).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" })}.</p>
                <Link className="btn" to={`/videos/${id}/summary`}>See the report</Link>
              </>
            ) : v.all_agree ? (
              <>
                <p><b>All {points.length} points agree within {limit}.</b></p>
                {user.role === "manager"
                  ? <button className="btn primary" disabled={busy} onClick={approve}>Approve</button>
                  : <p className="meta">Waiting for a manager to approve.</p>}
              </>
            ) : (
              <p className="meta">
                {agreeing} of {points.length} points agree within {limit}.
                {" "}A manager can approve once they all do.
              </p>
            )}
          </div>
        </aside>
      </div>
      {toast && <div className="toast" role="status">{toast}</div>}
    </div>
  );
}

/** Whether this person can add a count to the point now. */
function canCountPoint(p: ValidationPoint, v: Validation, name: string) {
  if (v.approval || p.state === "agree") return false;
  if (p.original_counter && p.original_counter === name) return false;
  return p.state === "recount" || !p.counted_by_viewer;
}

/** Every count of the point, once this person may see them, and how far apart the closest two are. */
function Comparison({ point, limit }: { point: ValidationPoint; limit: number }) {
  const shown = point.counts.some((c) => c.total !== null);
  if (!shown) {
    return <p className="val-hidden meta">{point.counts.length} {point.counts.length === 1 ? "count" : "counts"} so far, hidden until you've counted.</p>;
  }
  return (
    <div className="val-compare">
      {point.counts.map((c, i) => (
        <div key={c.id ?? `original-${i}`} className="val-count">
          <span>{c.counter || "Count tab"}<small className="meta">{c.original ? " · first count" : ` · count ${i + 1}`}</small></span>
          <b className="num">{c.total}</b>
        </div>
      ))}
      {point.difference !== null && (
        <p className={`val-diff ${point.state}`}>
          {point.state === "agree"
            ? <>Within {pct(limit)}: {pct(point.difference)} apart. Validated count <b className="num">{point.agreed}</b></>
            : <>{pct(point.difference)} apart, over {pct(limit)}. Needs a recount.</>}
        </p>
      )}
    </div>
  );
}
