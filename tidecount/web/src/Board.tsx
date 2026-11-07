import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, Summary, Video } from "./api";
import { countProgress } from "./Library";
import { placeLabel, useSurveys } from "./surveyStore";

const READY = "Ready to review";
const STAGES = ["Analysing", "To count", "Counting", "Counted"] as const;
type Stage = (typeof STAGES)[number];
type Card = { video: Video; done: number; total: number; stage: Stage };

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
    const card = { video, done, total, stage: stageOf(video, done, total) };
    const root = video.source_id || video.id;
    const held = best.get(root);
    if (!held || done > held.done) best.set(root, card);
  });
  return [...best.values()];
}

function useCards() {
  const [videos, setVideos] = useState<Video[] | null>(null);
  const [summaries, setSummaries] = useState<Record<string, Summary>>({});
  const [error, setError] = useState("");

  useEffect(() => {
    const load = () => api.videos().then(setVideos).catch((e) => setError(e.message));
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

  return { cards: videos ? toCards(videos, summaries) : null, error };
}

const openPath = (c: Card) => `/videos/${c.video.id}/${c.stage === "Counted" ? "summary" : "snapshots"}`;
const openLabel = (c: Card) => (c.stage === "Counted" ? "Open report" : c.stage === "Counting" ? "Continue" : "Count");

/** Where a card's video belongs, once someone has filed it. */
function useWhere() {
  const data = useSurveys();
  return (c: Card) => placeLabel(data, data.places[c.video.source_id || c.video.id]) || c.video.site || "Not filed yet";
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

/** Where every video stands, for the volunteers doing the counting and the managers following it. */
export function Analyse() {
  const { cards, error } = useCards();
  const where = useWhere();
  return (
    <div className="stack" style={{ gap: 20 }}>
      <div>
        <h1>Analyse</h1>
        <p className="lede">Where every video stands, from analysis to the finished count.</p>
      </div>
      {error && <p className="meta" style={{ color: "var(--down)" }}>{error}</p>}
      {!cards ? <p className="meta">Loading…</p> : (
        <div className="board">
          {STAGES.map((stage) => {
            const here = cards.filter((c) => c.stage === stage);
            return (
              <section className="board-col" key={stage} aria-label={stage}>
                <h2>{stage} <span className="num meta">{here.length}</span></h2>
                {here.map((c) => (
                  <div className="board-card" key={c.video.id}>
                    {c.stage === "Analysing"
                      ? <span className="vname">{c.video.name}</span>
                      : <Link className="vname" to={openPath(c)}>{c.video.name}</Link>}
                    <span className="meta">{c.stage === "Analysing" ? c.video.status : where(c)}</span>
                    <Progress card={c} />
                  </div>
                ))}
                {here.length === 0 && <p className="meta">Nothing here.</p>}
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
