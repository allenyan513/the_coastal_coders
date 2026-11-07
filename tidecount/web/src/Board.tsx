import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, Summary, Video } from "./api";
import { countProgress } from "./Library";
import { useUser } from "./session";
import { placeLabel, season, siteOf, SurveyData, useSurveys } from "./surveyStore";

const READY = "Ready to review";
const STAGES = ["Analysing", "To count", "Counting", "Counted"] as const;
type Stage = (typeof STAGES)[number];
type Card = { video: Video; root: string; done: number; total: number; stage: Stage };

/** What each column means, and the colour it carries everywhere it shows. */
const ABOUT: Record<Stage, { text: string; tone: string }> = {
  Analysing: { text: "AI is scanning the footage for fish.", tone: "muted" },
  "To count": { text: "Ready for someone to start counting.", tone: "accent" },
  Counting: { text: "Sub-sample points partly counted.", tone: "warn" },
  Counted: { text: "Every point counted. Ready to report.", tone: "up" },
};

function stageOf(video: Video, done: number, total: number): Stage {
  if (video.status !== READY) return "Analysing";
  if (total > 0 && done >= total) return "Counted";
  return done > 0 ? "Counting" : "To count";
}

/** One card per video. Re-runs of a video with another model share a card, showing the run with the most counted. */
function toCards(videos: Video[], summaries: Record<string, Summary>): Card[] {
  const best = new Map<string, Card>();
  videos.forEach((video) => {
    const summary = summaries[video.id];
    const { done, total } = summary ? countProgress(summary) : { done: 0, total: 0 };
    const root = video.source_id || video.id;
    const card = { video, root, done, total, stage: stageOf(video, done, total) };
    const held = best.get(root);
    if (!held || done > held.done) best.set(root, card);
  });
  return [...best.values()];
}

function useCards() {
  const [videos, setVideos] = useState<Video[] | null>(null);
  const [summaries, setSummaries] = useState<Record<string, Summary>>({});
  const [error, setError] = useState("");

  const load = () => api.videos().then(setVideos).catch((e) => setError(e.message));
  useEffect(() => {
    load();
    const timer = setInterval(load, 5000);
    return () => clearInterval(timer);
  }, []);

  const readyIds = (videos ?? []).filter((v) => v.status === READY).map((v) => v.id).join(",");
  useEffect(() => {
    if (!readyIds) return;
    Promise.all(readyIds.split(",").map(async (id) => [id, await api.summary(id)] as const))
      .then((all) => setSummaries(Object.fromEntries(all)))
      .catch(() => {});
  }, [readyIds]);

  return { cards: videos ? toCards(videos, summaries) : null, error, reload: load };
}

const openPath = (c: Card) => `/videos/${c.video.id}/${c.stage === "Counted" ? "summary" : "snapshots"}`;
const openLabel = (c: Card) => (c.stage === "Counted" ? "Open report" : c.stage === "Counting" ? "Continue" : "Count");

/** Where a card's video belongs, once someone has filed it. */
function useWhere() {
  const data = useSurveys();
  return (c: Card) => placeLabel(data, data.places[c.root]) || c.video.site || "Not filed yet";
}

function Progress({ card }: { card: Card }) {
  if (!card.total) return null;
  return (
    <>
      <span className="num meta">{card.done} of {card.total} points</span>
      <span className="bar wide"><i className={card.stage === "Counted" ? "up" : ""} style={{ width: `${(card.done / card.total) * 100}%` }} /></span>
    </>
  );
}

/** A still from early in the video, so a card can be recognised at a glance. */
function Thumb({ video }: { video: Video }) {
  return video.status === READY
    ? <video className="flow-thumb" src={`/api/videos/${video.id}/proxy#t=${Math.min(3, video.duration / 2).toFixed(1)}`} preload="metadata" muted playsInline tabIndex={-1} aria-hidden />
    : <span className="flow-thumb" aria-hidden />;
}

const UNFILED = "unfiled";

function FlowCard({ card, data, onRetry }: { card: Card; data: SurveyData; onRetry: (id: string) => void }) {
  const { video, stage } = card;
  const station = data.places[card.root];
  const filmed = data.filmedOn[card.root];
  const failed = video.status === "Failed";
  return (
    <article className={`flow-card ${failed ? "failed" : ""}`}>
      <div className="flow-card-top">
        <Thumb video={video} />
        <div className="stack" style={{ gap: 2, minWidth: 0 }}>
          {stage === "Analysing"
            ? <span className="vname flow-name" title={video.name}>{video.name}</span>
            : <Link className="vname flow-name" to={openPath(card)} title={video.name}>{video.name}</Link>}
          <span className="meta">{filmed ? season(filmed) : "No filmed date"}</span>
        </div>
      </div>
      {station
        ? <span className="flow-where">{placeLabel(data, station)}</span>
        : <Link className="flow-where unfiled" to="/">Not filed yet · choose a station</Link>}
      {stage === "Analysing" ? (
        failed ? (
          <div className="stack" style={{ gap: 6 }}>
            <span className="pill down" style={{ alignSelf: "flex-start" }}>Failed</span>
            {video.error && <span className="meta flow-error">{video.error}</span>}
            <button className="btn" onClick={() => onRetry(video.id)}>Retry</button>
          </div>
        ) : (
          <div className="stack" style={{ gap: 6 }}>
            <span className="meta">{video.stage || video.status}{video.status === "Analyzing" ? ` · ${Math.round(video.progress * 100)}%` : ""}</span>
            <span className="bar wide"><i className="pulse" style={{ width: `${Math.max(4, video.progress * 100)}%` }} /></span>
          </div>
        )
      ) : (
        <>
          {card.total > 0 && <span className="bar wide"><i className={stage === "Counted" ? "up" : ""} style={{ width: `${(card.done / card.total) * 100}%` }} /></span>}
          <div className="flow-foot">
            <span className="num meta">{card.total ? `${card.done} of ${card.total} points` : ""}</span>
            <Link className={`btn ${stage === "Counted" ? "" : "go"}`} to={openPath(card)}>{openLabel(card)}</Link>
          </div>
        </>
      )}
    </article>
  );
}

/** Where every video stands, from import to the finished count, for the volunteers counting and the managers following it. */
export function Workflow() {
  const manager = useUser().role === "manager";
  const data = useSurveys();
  const { cards, error, reload } = useCards();
  const [query, setQuery] = useState("");
  const [site, setSite] = useState("");
  const [retryError, setRetryError] = useState("");

  const retry = (id: string) => {
    setRetryError("");
    api.retry(id).then(reload).catch((e) => setRetryError(e.message));
  };

  const shown = (cards ?? []).filter((c) => {
    if (query && !c.video.name.toLowerCase().includes(query.toLowerCase())) return false;
    if (site === UNFILED) return !data.places[c.root];
    return !site || siteOf(data, data.places[c.root])?.id === site;
  });
  const done = shown.reduce((n, c) => n + c.done, 0);
  const total = shown.reduce((n, c) => n + c.total, 0);
  const unfiled = (cards ?? []).filter((c) => !data.places[c.root]).length;

  return (
    <div className="stack" style={{ gap: 20 }}>
      <div className="pagehead">
        <div>
          <h1>Workflow</h1>
          <p className="lede">Every video from import to the finished count.</p>
        </div>
        {manager && <Link className="btn primary" to="/?import=1">Import video</Link>}
      </div>

      <div className="flow-bar">
        <input className="flow-search" type="search" placeholder="Find a video" value={query} onChange={(e) => setQuery(e.target.value)} aria-label="Find a video by name" />
        <select className="run-model flow-site" value={site} onChange={(e) => setSite(e.target.value)} aria-label="Site">
          <option value="">All sites</option>
          {data.sites.filter((s) => !s.archived).map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          <option value={UNFILED}>Not filed yet</option>
        </select>
        <span className="spacer" />
        {total > 0 && (
          <div className="flow-total">
            <span className="meta"><span className="num">{done} of {total}</span> points counted</span>
            <span className="bar wide"><i className={done >= total ? "up" : ""} style={{ width: `${(done / total) * 100}%` }} /></span>
          </div>
        )}
      </div>

      {manager && unfiled > 0 && site !== UNFILED && (
        <p className="meta">{unfiled} {unfiled === 1 ? "video has" : "videos have"} no station yet, so reports leave {unfiled === 1 ? "it" : "them"} out. <Link to="/">File them in Surveys</Link></p>
      )}
      {(error || retryError) && <p className="meta" style={{ color: "var(--down)" }}>{error || retryError}</p>}
      {!cards ? <p className="meta">Loading…</p> : (
        <div className="board">
          {STAGES.map((stage) => {
            const here = shown.filter((c) => c.stage === stage);
            return (
              <section className={`board-col ${ABOUT[stage].tone}`} key={stage} aria-label={stage}>
                <div className="board-head">
                  <h2><span className={`flow-dot ${ABOUT[stage].tone}`} aria-hidden />{stage}<span className="num board-count">{here.length}</span></h2>
                  <p className="meta">{ABOUT[stage].text}</p>
                </div>
                {here.map((c) => <FlowCard key={c.root} card={c} data={data} onRetry={retry} />)}
                {here.length === 0 && <p className="board-empty">{query || site ? "No match here." : "Nothing here."}</p>}
              </section>
            );
          })}
        </div>
      )}
    </div>
  );
}

/** A volunteer's home. The server doesn't assign videos to people yet, so this lists every video still to count. */
export function MyTasks() {
  const { cards, error } = useCards();
  const where = useWhere();
  const open = cards?.filter((c) => c.stage === "To count" || c.stage === "Counting") ?? [];
  return (
    <div className="stack" style={{ gap: 20 }}>
      <div>
        <h1>My tasks</h1>
        <p className="lede">Videos waiting for your count.</p>
      </div>
      {error && <p className="meta" style={{ color: "var(--down)" }}>{error}</p>}
      {!cards ? <p className="meta">Loading…</p> : (
        <div className="panel">
          {open.map((c) => (
            <div className="task-row" key={c.video.id}>
              <div className="stack" style={{ gap: 4, minWidth: 0 }}>
                <Link className="vname" to={openPath(c)}>{c.video.name}</Link>
                <span className="meta">{where(c)}</span>
              </div>
              <div className="stack" style={{ gap: 6 }}><Progress card={c} /></div>
              <Link className="btn go" to={openPath(c)}>{openLabel(c)}</Link>
            </div>
          ))}
          {open.length === 0 && <p className="meta" style={{ padding: 16 }}>Nothing to count right now.</p>}
        </div>
      )}
    </div>
  );
}
