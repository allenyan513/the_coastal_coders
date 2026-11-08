import { ReactNode } from "react";
import { ModelOption } from "./api";

/*
 * The front page's computer vision section. Every number below is copied from the team's own
 * measurements, with where it came from next to it, so it can be checked and updated:
 *   data/bench/scores-dev.md and still-dev.md   detector speed, review queue, flicker rule (ml/bench.py, ml/still.py)
 *   data/reports/team-update.html               species bake-off on FjordFish (ml/species_bench.py, PR #54)
 *   ml/01_brackish_classification.ipynb         split by video against split by frame
 * They are provisional: few labelled frames, and none of Coastal Action's own footage yet.
 */

const I = {
  detect: <><path d="M4 8V4h4M16 4h4v4M20 16v4h-4M8 20H4v-4" /><path d="M7 12c2-2.6 5-2.6 7.5 0-2.5 2.6-5.5 2.6-7.5 0Zm7.5 0 2.5-1.8v3.6Z" /></>,
  filter: <><path d="M3 5h18l-7 8v6l-4 2v-8Z" /></>,
  track: <><path d="M4 18c3-1 4-6 8-6s5-5 8-6" strokeDasharray="2 3" /><circle cx="4" cy="18" r="1.6" /><circle cx="12" cy="12" r="1.6" /><circle cx="20" cy="6" r="1.6" /></>,
  identify: <><path d="M3 12V4h8l10 10-8 8Z" /><circle cx="7.5" cy="8.5" r="1.4" /></>,
  confirm: <><circle cx="12" cy="12" r="9" /><path d="m8 12.5 3 3 5-6" /></>,
  chip: <><rect x="6" y="6" width="12" height="12" rx="2" /><path d="M9 9h6v6H9zM9 2v4M15 2v4M9 18v4M15 18v4M2 9h4M2 15h4M18 9h4M18 15h4" /></>,
};
const Icon = ({ name }: { name: keyof typeof I }) => (
  <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden>{I[name]}</svg>
);

const PIPELINE: { icon: keyof typeof I; title: string; model: string; text: string }[] = [
  { icon: "detect", title: "Detect", model: "RF-DETR · Community Fish Detector", text: "Boxes every fish, two frames each second." },
  { icon: "filter", title: "Filter", model: "Flicker rule", text: "Drops boxes that blink on for a frame, so empty water stays out of the queue." },
  { icon: "track", title: "Track", model: "ByteTrack", text: "Links boxes into one path per fish, so a fish swimming past counts once." },
  { icon: "identify", title: "Identify", model: "BioCLIP 2.5 · ViT-H/14", text: "Suggests three species, only from fish recorded in Nova Scotia." },
  { icon: "confirm", title: "Confirm", model: "A person", text: "Confirms, corrects or rejects. Only their decisions reach a report." },
];

export function Pipeline() {
  return (
    <ol className="ln-pipe" aria-label="How a video is analysed">
      {PIPELINE.map((p, i) => (
        <li key={p.title} className={i === PIPELINE.length - 1 ? "human" : ""}>
          <span className="ln-pipe-icon"><Icon name={p.icon} /></span>
          <span className="ln-pipe-n num">0{i + 1}</span>
          <b>{p.title}</b>
          <code>{p.model}</code>
          <p>{p.text}</p>
        </li>
      ))}
    </ol>
  );
}

/** What runs inside the app, with the detectors read live from the server. */
export function VisionStack({ models, species }: { models: ModelOption[]; species: number }) {
  const main = models.find((m) => m.default);
  const others = models.filter((m) => !m.default);
  const Row = ({ k, v, tag }: { k: string; v: ReactNode; tag?: ReactNode }) => (
    <div className="ln-model"><span><small className="ln-stack-k">{k}</small>{v}</span>{tag}</div>
  );
  return (
    <aside className="ln-ai-card" aria-label="Models inside Tideflow">
      <p className="ln-card-kicker"><Icon name="chip" /> Inside the app</p>
      <Row k="Detect" v={main?.label ?? "Community Fish Detector Nano"} tag={<span className="pill accent">Default</span>} />
      {others.length > 0 && <Row k="Or choose" v={<span className="ln-stack-alt">{others.map((m) => m.label).join(" · ")}</span>} />}
      <Row k="Track" v="ByteTrack at 2 frames a second" />
      <Row k="Identify" v="BioCLIP 2.5, the Nova Scotia list" tag={<span className="num meta">{species || "…"} species</span>} />
      <Row k="Runs on" v="An ordinary PC: CPU, Apple GPU or NVIDIA GPU" tag={<span className="pill ln-pill-dark">No cloud</span>} />
      <p className="ln-ai-rule">Nothing AI suggests reaches a report until a person confirms it. A frame nobody could see into is left out, never counted as zero.</p>
    </aside>
  );
}

type Bar = { label: string; value: number; before?: number; tone?: "main" | "dim" | "dashed" | "warn" | "total"; note?: string };

/** Horizontal bars on a 0 to max scale. `before` draws a ghost bar behind, for a before and after. */
function Bars({ rows, max, unit, wide }: { rows: Bar[]; max: number; unit: string; wide?: boolean }) {
  return (
    <div className={`ln-hbars ${wide ? "wide" : ""}`} role="img" aria-label={rows.map((r) => `${r.label}: ${r.before !== undefined ? `${r.before}${unit} to ` : ""}${r.value}${unit}`).join(", ")}>
      {rows.map((r) => (
        <div key={r.label} className={`ln-hbar ${r.tone ?? "main"}`}>
          <span className="ln-hbar-label">{r.label}{r.note && <small>{r.note}</small>}</span>
          <span className="ln-hbar-track">
            {r.before !== undefined && <i className="ghost" style={{ width: `${(r.before / max) * 100}%` }} />}
            <i style={{ width: `${(r.value / max) * 100}%` }} />
          </span>
          <span className="ln-hbar-v num">{r.before !== undefined && r.before !== r.value && <s>{r.before}</s>}{r.value}{unit}</span>
        </div>
      ))}
    </div>
  );
}

function Finding({ kicker, big, lead, children, note }: { kicker: string; big: string; lead: string; children: ReactNode; note: string }) {
  return (
    <article className="ln-find">
      <p className="ln-card-kicker">{kicker}</p>
      <div className="ln-find-big"><b className="num">{big}</b><span>{lead}</span></div>
      {children}
      <p className="ln-find-note">{note}</p>
    </article>
  );
}

export function Research() {
  return (
    <div className="ln-research">
      <Finding kicker="Review queue · flicker rule" big="84% → 66%" lead="of the footage left for a person to watch, with every fish frame still in it (25 of 25)"
        note="Today's detector at threshold 0.20 on six development videos. False alarms flicker for a frame; real fish stay in view.">
        <Bars unit="%" max={100} rows={[
          { label: "Seagrass bed", before: 100, value: 82 },
          { label: "Trout stream", before: 100, value: 100 },
          { label: "Nova Scotia river", before: 99, value: 50 },
          { label: "Jetty", before: 45, value: 14 },
          { label: "Lake", before: 91, value: 63 },
          { label: "Crab camera", before: 100, value: 100 },
          { label: "All six videos", before: 84, value: 66, tone: "total" },
        ]} />
      </Finding>

      <Finding kicker="Species model · bake-off" big="2.5×" lead="more first suggestions right after the upgrade to BioCLIP 2.5 with common and scientific names"
        note="5,420 fish crops of 12 species from the FjordFish dataset, in clear Nordic water, so read these as a ceiling. Under 64 pixels a guess was no better than chance, so the app gives none.">
        <Bars unit="%" max={100} wide rows={[
          { label: "BioCLIP 1", note: "scientific names, 190 species", value: 18.8, tone: "dim" },
          { label: "BioCLIP 2.5", note: "both names, 190 species", value: 46.8 },
          { label: "+ site short list", note: "12 species", value: 55.8 },
          { label: "+ 20 labels a species", note: "next step, 10 species", value: 71.7, tone: "dashed" },
        ]} />
        <div className="ln-size" role="img" aria-label="Right first time by fish size: under 64 px 2%, 64 to 127 px 31%, 128 to 255 px 70%, 256 px and over 86%">
          <span className="ln-size-k">Right first time, by fish size (190-species list)</span>
          {[["< 64 px", 2.2], ["64–127", 30.9], ["128–255", 69.9], ["256+ px", 85.6]].map(([k, v]) => (
            <span key={k as string} className="ln-size-col">
              <span className="ln-size-bar"><i style={{ height: `${v}%` }} /></span>
              <b className="num">{Math.round(v as number)}%</b>
              <small>{k}</small>
            </span>
          ))}
        </div>
      </Finding>

      <Finding kicker="Detector · speed against size" big="62 ms" lead="per frame for the Nano detector, the fastest of five setups we benchmarked"
        note="Bigger wasn't better here. At threshold 0.30, Medium queued 84% of footage against Nano's 74% and kept 23 of 25 fish frames against 25, so Nano is the default.">
        <Bars unit=" ms" max={540} rows={[
          { label: "Nano", note: "default", value: 62 },
          { label: "Small", value: 152, tone: "dim" },
          { label: "Medium", value: 155, tone: "dim" },
          { label: "Nano, tiled", value: 433, tone: "dim" },
          { label: "Medium, tiled", value: 540, tone: "dim" },
        ]} />
      </Finding>

      <Finding kicker="Honest scoring · data leakage" big="85%, not 97%" lead="the accuracy we report for a classifier, because test videos never appear in training"
        note="Same ResNet-18 on the public Brackish dataset. A random split by frame puts near-copies of test frames in training and adds 12 points that aren't real skill. Three benchmark videos stay locked until the final score.">
        <Bars unit="%" max={100} wide rows={[
          { label: "Split by video", note: "what we report", value: 85.4 },
          { label: "Split by frame", note: "leaky, inflated", value: 97.4, tone: "warn" },
          { label: "BioCLIP, untrained", note: "baseline to beat", value: 22.5, tone: "dim" },
        ]} />
      </Finding>
    </div>
  );
}
