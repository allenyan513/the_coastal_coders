import { memo, MouseEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api, clock, Track, Video } from "./api";
import { guess, nameOf, stateFor, topName, UNIDENTIFIED } from "./trackHelpers";
import { KeyGroup, Shortcuts } from "./Shortcuts";
import { VideoHeader } from "./VideoHeader";

type Plan = { track_id: number; state: Track["state"]; species: string | null };
type Step = { plans: Plan[] } | { merged: number };

const duration = (t: Track) => t.last_t - t.first_t;
const SORTS: Record<string, { label: string; by: (a: Track, b: Track) => number }> = {
  time: { label: "Time", by: (a, b) => a.first_t - b.first_t },
  conf: { label: "Least sure first", by: (a, b) => a.conf - b.conf },
  length: { label: "Longest first", by: (a, b) => duration(b) - duration(a) },
};
const SORT_KEYS = Object.keys(SORTS);
const PICKER_SIZE = 5;
const KEYS: KeyGroup[] = [
  { title: "Move and select", keys: [["← → ↑ ↓", "Move between tracks"], ["Shift+arrows", "Extend the selection"], ["Space", "Select or unselect"], ["⌘/Ctrl+A", "Select all shown"], ["Esc", "Clear the selection"]] },
  { title: "Decide", keys: [["C", "Confirm"], ["1 2 3 4 5", "Name with a button in the bar"], ["U", "Fish, unidentified"], ["X", "Not a fish"], ["M", "Same fish, merge"], ["Z", "Undo"]] },
  { title: "View", keys: [["Enter O", "Watch the track in the video"], ["F", "Undecided or all"], ["S", "Change the sort"]] },
];

const TrackCard = memo(function TrackCard({ track: t, on, at, version, onPick, onOpen }: {
  track: Track;
  on: boolean;
  at: boolean;
  version: number;
  onPick: (id: number, shift: boolean) => void;
  onOpen: (id: number) => void;
}) {
  const top = guess(t);
  return (
    <article className={`tcard ${on ? "on" : ""} ${at ? "at" : ""} ${t.state === "Rejected" ? "rejected" : ""}`}>
      <button
        className="tcard-pick"
        data-track={t.id}
        tabIndex={at ? 0 : -1}
        aria-pressed={on}
        aria-label={`Track ${t.id}, ${t.state ?? "Suggested"}, ${t.decided_species ?? top ?? "Fish"}`}
        onClick={(e: MouseEvent) => onPick(t.id, e.shiftKey)}
      >
        {t.has_crop ? <img src={`/api/tracks/${t.id}/crop${version ? `?v=${version}` : ""}`} alt="" loading="lazy" decoding="async" /> : <span className="nocrop" />}
        <span className="tcard-line">
          <span className={`pill ${t.state ? (t.state === "Rejected" ? "down" : "up") : "warn"}`}>{t.state ?? "Suggested"}</span>
          <span className="num meta">#{t.id}</span>
        </span>
        {t.decided_species
          ? <span className="tcard-name">{t.decided_species}</span>
          : t.state !== "Rejected" && <span className="tcard-name ai">{top ? `${top}?` : "Fish"}</span>}
        <span className="tcard-line num meta">
          <span>{clock(t.first_t)}</span>
          <span>{duration(t).toFixed(1)} s</span>
          <span>{t.manual ? "Added by you" : `Det ${t.conf.toFixed(2)}`}</span>
        </span>
      </button>
      <button className="tcard-open" tabIndex={-1} onClick={() => onOpen(t.id)}>Watch in video</button>
      <span className="tcard-tick" aria-hidden>✓</span>
      {!!t.static && <span className="tcard-flag pill warn">Barely moves</span>}
    </article>
  );
});

export function Tracks() {
  const { id = "" } = useParams();
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const [video, setVideo] = useState<Video | null>(null);
  const [tracks, setTracks] = useState<Track[]>([]);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [cursor, setCursor] = useState<number | null>(Number(params.get("at")) || null);
  const [versions, setVersions] = useState<Record<number, number>>({});
  const [toast, setToast] = useState("");
  const grid = useRef<HTMLDivElement>(null);
  const anchor = useRef<number | null>(null);
  const history = useRef<Step[]>([]);
  const saving = useRef<Promise<unknown>>(Promise.resolve());
  const lastIndex = useRef(0);
  const timer = useRef(0);

  const showAll = params.get("show") === "all";
  const sort = SORT_KEYS.includes(params.get("sort") ?? "") ? params.get("sort")! : "time";

  const flash = (msg: string) => {
    setToast(msg);
    clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setToast(""), 3200);
  };

  useEffect(() => {
    Promise.all([api.video(id), api.tracks(id)]).then(([v, t]) => {
      setVideo(v);
      setTracks(t);
    });
    api.event(id, "track_sheet_open");
  }, [id]);

  const shown = useMemo(() => {
    const open = showAll ? tracks : tracks.filter((t) => !t.state);
    return [...open].sort((a, b) => SORTS[sort].by(a, b) || a.first_t - b.first_t || a.id - b.id);
  }, [tracks, showAll, sort]);

  const undecided = useMemo(() => tracks.filter((t) => !t.state).length, [tracks]);
  const here = shown.findIndex((t) => t.id === cursor);

  // The cursor always sits on a card, so the keyboard works straight away.
  useEffect(() => {
    if (here >= 0) lastIndex.current = here;
    else if (shown.length) setCursor(shown[Math.min(lastIndex.current, shown.length - 1)].id);
  }, [here, shown]);

  useEffect(() => {
    const card = cursor === null ? null : grid.current?.querySelector<HTMLElement>(`[data-track="${cursor}"]`);
    if (!card) return;
    card.focus({ preventScroll: true });
    card.parentElement?.scrollIntoView({ block: "nearest" });
  }, [cursor, sort, showAll, shown.length > 0]);

  const targets = useMemo(() => {
    const picked = shown.filter((t) => selected.has(t.id));
    if (picked.length) return picked;
    return shown[here] ? [shown[here]] : [];
  }, [shown, selected, here]);

  /** Names a person already used on this video, then AI's guesses for what's selected. */
  const picker = useMemo(() => {
    const scores = new Map<string, number>();
    targets.forEach((t) => t.candidates.forEach((c) => scores.set(nameOf(c), (scores.get(nameOf(c)) ?? 0) + c.score)));
    const suggested = [...scores].sort((a, b) => b[1] - a[1]).map(([name]) => ({ name, ai: true }));
    const taken = new Set(suggested.map((s) => s.name).concat(UNIDENTIFIED));
    const used = [...new Set(tracks.flatMap((t) => t.decided_species ?? []))].filter((n) => !taken.has(n)).map((name) => ({ name, ai: false }));
    return [...used, ...suggested].slice(0, PICKER_SIZE);
  }, [targets, tracks]);

  /** Saves run one at a time, in order. If one fails, the server's copy wins. */
  const save = (action: () => Promise<unknown>) => {
    saving.current = saving.current.then(action).catch(async (e) => {
      flash(`Not saved: ${(e as Error).message}`);
      history.current = [];
      setTracks(await api.tracks(id));
    });
    return saving.current;
  };

  const patch = (plans: Plan[]) => {
    const byId = new Map(plans.map((p) => [p.track_id, p]));
    setTracks((all) => all.map((t) => {
      const p = byId.get(t.id);
      return p ? { ...t, state: p.state, decided_species: p.species } : t;
    }));
  };

  const moveOff = (ids: Set<number>) => {
    const at = Math.max(here, 0);
    const next = shown.slice(at + 1).find((t) => !ids.has(t.id)) ?? shown.slice(0, at).reverse().find((t) => !ids.has(t.id));
    if (next) setCursor(next.id);
  };

  const apply = (plans: Plan[], message: string) => {
    if (!plans.length) return;
    const before = plans.flatMap((p): Plan[] => {
      const t = tracks.find((x) => x.id === p.track_id);
      return t ? [{ track_id: t.id, state: t.state, species: t.decided_species }] : [];
    });
    history.current.push({ plans: before });
    patch(plans);
    moveOff(new Set(plans.map((p) => p.track_id)));
    setSelected(new Set());
    anchor.current = null;
    flash(message);
    save(() => api.decideMany(plans));
  };

  const plural = (n: number) => `${n} ${n === 1 ? "track" : "tracks"}`;

  const confirm = () => {
    // One bulk key must not wipe out what a person already decided.
    const open = targets.length > 1 ? targets.filter((t) => !t.state) : targets;
    if (!open.length) return flash("Those tracks are already decided");
    const kept = targets.length - open.length;
    apply(
      open.map((t) => ({ track_id: t.id, state: stateFor(t, topName(t)), species: topName(t) })),
      `Confirmed ${plural(open.length)}${kept ? `, left ${kept} already decided` : ""}`,
    );
  };

  const name = (species: string) =>
    apply(targets.map((t) => ({ track_id: t.id, state: stateFor(t, species), species })), `${species}: ${plural(targets.length)}`);

  const reject = () =>
    apply(targets.map((t) => ({ track_id: t.id, state: "Rejected", species: null })), `Not a fish: ${plural(targets.length)}`);

  const picked = shown.filter((t) => selected.has(t.id));
  const overlapping = useMemo(() => {
    const byStart = [...picked].sort((a, b) => a.first_t - b.first_t);
    return byStart.some((t, i) => i > 0 && t.first_t < byStart[i - 1].last_t);
  }, [selected, shown]);
  const names = [...new Set(picked.flatMap((t) => (t.state && t.state !== "Rejected" ? t.decided_species ?? [] : [])))];

  const merge = async () => {
    if (picked.length < 2) return flash("Select at least two tracks to merge");
    const ids = picked.map((t) => t.id);
    setSelected(new Set());
    anchor.current = null;
    await save(async () => {
      const { id: kept } = await api.merge(ids);
      setTracks(await api.tracks(id));
      setVersions((all) => ({ ...all, [kept]: Date.now() }));
      setCursor(kept);
      history.current.push({ merged: kept });
      flash(`Merged ${ids.length} tracks into one fish`);
    });
  };

  const undo = async () => {
    const step = history.current.pop();
    if (!step) return flash("Nothing to undo");
    if ("plans" in step) {
      patch(step.plans);
      setCursor(step.plans[0].track_id);
      setSelected(new Set());
      flash(`Undone: ${plural(step.plans.length)}`);
      await save(() => api.decideMany(step.plans));
      return;
    }
    await save(async () => {
      await api.unmerge(step.merged);
      setTracks(await api.tracks(id));
      setVersions((all) => ({ ...all, [step.merged]: Date.now() }));
      setCursor(step.merged);
      flash("Merge undone");
    });
  };

  const open = (trackId: number) => {
    const next = new URLSearchParams(params);
    next.set("at", String(trackId));
    navigate(`?${next}`, { replace: true });
    navigate(`/videos/${id}?track=${trackId}`);
  };

  const view = (key: string, value: string | null) => {
    const next = new URLSearchParams(params);
    next.delete("at");
    if (value) next.set(key, value);
    else next.delete(key);
    navigate(`?${next}`, { replace: true });
  };

  const setSort = (key: string) => view("sort", key === "time" ? null : key);

  const setFilter = (all: boolean) => {
    setSelected(new Set());
    anchor.current = null;
    view("show", all ? "all" : null);
  };

  const between = (from: number, to: number) => {
    const [a, b] = [shown.findIndex((t) => t.id === from), shown.findIndex((t) => t.id === to)].sort((x, y) => x - y);
    return a < 0 ? [to] : shown.slice(a, b + 1).map((t) => t.id);
  };

  const pick = (trackId: number, shift: boolean) => {
    setCursor(trackId);
    if (shift && anchor.current !== null) {
      setSelected((all) => new Set([...all, ...between(anchor.current!, trackId)]));
      return;
    }
    anchor.current = trackId;
    setSelected((all) => {
      const next = new Set(all);
      if (!next.delete(trackId)) next.add(trackId);
      return next;
    });
  };

  const latest = useRef({ pick, open });
  latest.current = { pick, open };
  const onPick = useCallback((trackId: number, shift: boolean) => latest.current.pick(trackId, shift), []);
  const onOpen = useCallback((trackId: number) => latest.current.open(trackId), []);

  const go = (step: number, extend: boolean) => {
    const target = shown[Math.max(0, Math.min(shown.length - 1, here + step))];
    if (!target) return;
    if (extend) {
      anchor.current ??= shown[here]?.id ?? target.id;
      setSelected((all) => new Set([...all, ...between(anchor.current!, target.id)]));
    }
    setCursor(target.id);
  };

  const columns = () => (grid.current ? getComputedStyle(grid.current).gridTemplateColumns.split(" ").length : 1);
  const selectAll = () => {
    setSelected(new Set(shown.map((t) => t.id)));
    anchor.current = shown[0]?.id ?? null;
  };
  const clear = () => {
    setSelected(new Set());
    anchor.current = null;
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement;
      if (["INPUT", "SELECT", "TEXTAREA"].includes(el.tagName)) return;
      const key = e.key.toLowerCase();
      if (e.metaKey || e.ctrlKey) {
        if (key === "a") { e.preventDefault(); selectAll(); }
        return;
      }
      if (key === "arrowleft") { e.preventDefault(); go(-1, e.shiftKey); }
      else if (key === "arrowright") { e.preventDefault(); go(1, e.shiftKey); }
      else if (key === "arrowup") { e.preventDefault(); go(-columns(), e.shiftKey); }
      else if (key === "arrowdown") { e.preventDefault(); go(columns(), e.shiftKey); }
      else if (e.repeat) return;
      else if (key === " " || key === "enter") {
        // A focused toolbar button keeps its own Space and Enter.
        if (el.closest("button, a") && !el.dataset.track) return;
        e.preventDefault();
        if (cursor === null) return;
        if (key === " ") pick(cursor, e.shiftKey);
        else open(cursor);
      }
      else if (key === "o") { if (cursor !== null) open(cursor); }
      else if (key === "escape") clear();
      else if (key === "z") undo();
      else if (key === "f") setFilter(!showAll);
      else if (key === "s") setSort(SORT_KEYS[(SORT_KEYS.indexOf(sort) + 1) % SORT_KEYS.length]);
      else if (key === "m") merge();
      else if (!targets.length) return;
      else if (key === "c") confirm();
      else if (key === "x") reject();
      else if (key === "u") name(UNIDENTIFIED);
      else if (/^[1-5]$/.test(key) && picker[+key - 1]) name(picker[+key - 1].name);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  if (!video) return <p className="meta">Loading…</p>;
  const none = !targets.length;
  const label = selected.size ? `${picked.length} selected` : targets[0] ? `Track #${targets[0].id}` : "Nothing to decide";

  return (
    <div className="stack">
      <VideoHeader id={id} step="review" view="tracks" />

      <section className="panel sheet-bar" aria-label="Filter and decide">
        <div className="row">
          <button className="chip" aria-pressed={!showAll} onClick={() => setFilter(false)}>Undecided</button>
          <button className="chip" aria-pressed={showAll} onClick={() => setFilter(true)}>All</button>
          <span className="meta">Sort</span>
          {SORT_KEYS.map((k) => <button key={k} className="chip" aria-pressed={sort === k} onClick={() => setSort(k)}>{SORTS[k].label}</button>)}
          <span className="spacer" />
          <span className="num meta">{undecided} undecided of {tracks.length}</span>
          <button className="btn" disabled={!shown.length} onClick={selectAll}>Select all {shown.length}</button>
          <button className="btn" disabled={!selected.size} onClick={clear}>Clear</button>
          <button className="btn" onClick={undo}><kbd>Z</kbd>Undo</button>
          <Shortcuts groups={KEYS} />
        </div>
        <div className="row sheet-actions">
          <b className="num" style={{ fontSize: 13, minWidth: 96 }}>{label}</b>
          <button className="btn primary" style={{ height: 36 }} disabled={none} onClick={confirm} title="A track keeps its suggested name when AI is sure. The rest count as unidentified fish."><kbd>C</kbd>Confirm as fish</button>
          {picker.map((p, i) => (
            <button key={p.name} className="btn" disabled={none} onClick={() => name(p.name)} title={p.ai ? "AI suggestion" : "Already used on this video"}>
              <kbd>{i + 1}</kbd>{p.name}{p.ai ? "?" : ""}
            </button>
          ))}
          <button className="btn" disabled={none} onClick={() => name(UNIDENTIFIED)}><kbd>U</kbd>{UNIDENTIFIED}</button>
          <button className="btn" disabled={none} onClick={reject}><kbd>X</kbd>Not a fish</button>
          <button className="btn" disabled={picked.length < 2} onClick={merge}><kbd>M</kbd>Same fish, merge</button>
        </div>
        <p className={`meta sheet-note ${overlapping ? "warn" : ""}`}>
          {overlapping
            ? "Before merging: these overlap in time, so they may be two fish."
            : names.length > 1
              ? `Merging keeps the earliest name and drops the other: ${names.join(", ")}.`
              : "Names with ? are AI suggestions. Decisions apply to the whole track and save straight away."}
        </p>
      </section>

      <div className="sheet-grid" ref={grid}>
        {shown.map((t) => (
          <TrackCard key={t.id} track={t} on={selected.has(t.id)} at={t.id === cursor} version={versions[t.id] ?? 0} onPick={onPick} onOpen={onOpen} />
        ))}
      </div>
      {!shown.length && (
        <div className="panel panel-pad">
          <h2>{tracks.length ? "Every track is decided" : "No AI tracks on this video"}</h2>
          <p className="meta">{tracks.length ? "Check the footage in the review queue. Deciding tracks here doesn't mark any footage as reviewed." : "Watch the review queue, and add any fish AI missed."}</p>
        </div>
      )}

      {toast && <div className="toast" role="status">{toast}</div>}
    </div>
  );
}
