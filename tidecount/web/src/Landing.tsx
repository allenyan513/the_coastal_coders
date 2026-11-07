import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, ModelOption, SpeciesRow, Summary, Video } from "./api";
import { countProgress } from "./Library";
import { useSession } from "./session";

const READY = "Ready to review";

/** Live numbers for the public page, read from the same API the workspace uses. */
function useFacts() {
  const [videos, setVideos] = useState<Video[] | null>(null);
  const [summaries, setSummaries] = useState<Record<string, Summary>>({});
  const [species, setSpecies] = useState<SpeciesRow[]>([]);
  const [models, setModels] = useState<ModelOption[]>([]);

  useEffect(() => {
    api.videos().then(setVideos).catch(() => setVideos([]));
    api.species().then(setSpecies).catch(() => {});
    api.models().then(setModels).catch(() => {});
  }, []);
  const readyIds = (videos ?? []).filter((v) => v.status === READY).map((v) => v.id).join(",");
  useEffect(() => {
    if (!readyIds) return;
    Promise.all(readyIds.split(",").map(async (id) => [id, await api.summary(id)] as const))
      .then((all) => setSummaries(Object.fromEntries(all)))
      .catch(() => {});
  }, [readyIds]);

  // Re-runs of one video with another model count once.
  const firsts = (videos ?? []).filter((v) => !v.source_id);
  const progress = (v: Video) => (summaries[v.id] ? countProgress(summaries[v.id]) : { done: 0, total: 0 });
  const ready = firsts.filter((v) => v.status === READY);
  const summarised = firsts.filter((v) => summaries[v.id]);
  const skipped = (v: Video) => summaries[v.id]?.skipped ?? 0;
  return {
    loaded: videos !== null && (readyIds === "" || summarised.length > 0),
    videos: firsts.length,
    hours: firsts.reduce((n, v) => n + v.duration, 0) / 3600,
    species,
    models,
    /** The ready video with the most points to count, so the sample shows the procedure best. */
    sample: [...ready].sort((a, b) => progress(b).total - progress(a).total)[0] as Video | undefined,
    progress,
    /** Share of the footage AI set aside as having no fish, so nobody has to watch it. */
    skippedShare: (vs: Video[]) => {
      const total = vs.reduce((n, v) => n + v.duration, 0);
      return total ? vs.reduce((n, v) => n + skipped(v), 0) / total : 0;
    },
    summarised,
  };
}
type Facts = ReturnType<typeof useFacts>;

const hours = (h: number) => (h >= 1 ? `${h.toFixed(1)} h` : `${Math.round(h * 60)} min`);
/** Opens the sample in the workspace. Sign-in comes first and then returns there, via ?next. */
const sampleTo = (v: Video | undefined, page: "snapshots" | "summary") => (v ? `/videos/${v.id}/${page}` : "/workspace");
/** Where a new volunteer starts. Sign-in opens on the volunteer role. */
const JOIN = "/login";

const STEPS = [
  { title: "Import the footage", text: "Each video is filed under its site, transect and station. File names like T1-STAT2 fill that in." },
  { title: "AI-enhanced recognition", text: "AI marks every fish it sees, follows each one through the video, suggests its species and sets aside the stretches with none." },
  { title: "AI-enhanced counting", text: "Volunteers count each snapshot point the procedure asks for. AI's dots are already in place; people confirm, add or remove them." },
  { title: "Data visualization", text: "Confirmed counts become charts by station and site, so treatment and reference sites sit side by side, season by season." },
];

const AI_POINTS = [
  { title: "Finds the fish", text: "An object detector boxes every fish it sees, frame by frame. Pick the model that suits the water." },
  { title: "Skips empty water", text: "Stretches with no detections, and boxes that flicker in and out, are set aside so people don't sit through them." },
  { title: "Follows each fish", text: "Boxes are linked into tracks, so one fish swimming past reads as one fish, not fifty frames." },
  { title: "Suggests the species", text: "BioCLIP names each fish, choosing only from species recorded in Nova Scotia." },
];

const WATER = [
  { name: "Temperature", unit: "°C" },
  { name: "pH", unit: "" },
  { name: "Dissolved oxygen", unit: "mg/L" },
  { name: "Conductance", unit: "µS/cm" },
  { name: "Salinity", unit: "ppt" },
];

const VOLUNTEER = [
  { title: "Join", text: "Sign in as a volunteer. Your tasks list the videos waiting for a count." },
  { title: "Open a video", text: "Tideflow takes you to each snapshot point in turn, with a grid to count in." },
  { title: "Count what you see", text: "Confirm AI's dots, add the fish it missed, and note the visibility. That's one point done." },
];

function Brand({ dark }: { dark?: boolean }) {
  return <Link to="/" className={`ln-brand ${dark ? "dark" : ""}`}><img src="/favicon.svg" alt="" />Tideflow</Link>;
}

function Waves() {
  return (
    <svg className="ln-waves" viewBox="0 0 1440 320" preserveAspectRatio="none" aria-hidden>
      {[0, 1, 2, 3].map((i) => (
        <path key={i} d={`M0 ${190 + i * 34} C 240 ${150 + i * 34}, 480 ${230 + i * 34}, 720 ${190 + i * 34} S 1200 ${150 + i * 34}, 1440 ${190 + i * 34}`} fill="none" stroke="currentColor" strokeWidth="1.2" opacity={0.28 - i * 0.05} />
      ))}
    </svg>
  );
}

function Nav() {
  const { user } = useSession();
  return (
    <header className="ln-wrap ln-nav">
      <Brand />
      <nav className="ln-links" aria-label="Sections">
        <a href="#how">How it works</a>
        <a href="#ai">AI</a>
        <a href="#data">Species and water</a>
        <a href="#volunteer">Volunteer</a>
      </nav>
      <span className="spacer" />
      {user
        ? <Link className="btn go" to="/workspace">Go to workspace</Link>
        : (
          <>
            <Link className="btn ln-ghost hide-phone" to={JOIN}>Join as a volunteer</Link>
            <Link className="btn go" to="/login">Sign in</Link>
          </>
        )}
    </header>
  );
}

/** The counting screen, drawn from the real sample: its frame, the grid volunteers count in, and how much of it AI set aside. */
function ProductShot({ f }: { f: Facts }) {
  const v = f.sample;
  const share = v ? Math.round(f.skippedShare([v]) * 100) : 0;
  return (
    <div className="ln-shot">
      <div className="ln-shot-bar"><i /><i /><i /><span>Snapshot count{v ? ` · ${v.name}` : ""}</span></div>
      <div className="ln-shot-stage">
        {v && <video src={`/api/videos/${v.id}/proxy#t=${Math.min(11, v.duration / 2).toFixed(1)}`} preload="metadata" muted playsInline tabIndex={-1} aria-hidden />}
        <div className="gridlines" aria-hidden>{Array.from({ length: 15 }, (_, i) => <div key={i}><span>{i + 1}</span></div>)}</div>
      </div>
      <div className="ln-shot-card">
        <span className="meta">Set aside as empty by AI</span>
        <b className="num">{v ? `${share}%` : "—"}</b>
        <span className="bar wide"><i className="up" style={{ width: `${share}%` }} /></span>
        <span className="meta">of this video, so nobody has to watch it</span>
      </div>
    </div>
  );
}

function Head({ eyebrow, title, text, light }: { eyebrow: string; title: string; text?: string; light?: boolean }) {
  return (
    <div className={`ln-head ${light ? "light" : ""}`}>
      <p className="ln-eyebrow">{eyebrow}</p>
      <h2 className="ln-h2">{title}</h2>
      {text && <p className="ln-sub">{text}</p>}
    </div>
  );
}

/** The public front page: what Tideflow is, how the work flows, the AI, the data it opens up, and how to help. */
export function Landing() {
  const f = useFacts();
  // Every figure here is computed from the data, or true by how Tideflow works. None is an estimate.
  const stats: [string, string][] = [
    [`${Math.round(f.skippedShare(f.summarised) * 100)}%`, "of the footage set aside by AI as empty, so nobody has to watch it"],
    ["100%", "of the counts in a report confirmed by a person"],
    [String(f.species.length), "Nova Scotia species the AI suggests from, and no others"],
    [hours(f.hours), `of survey video scanned, across ${f.videos} ${f.videos === 1 ? "video" : "videos"}`],
  ];
  const named = f.species.filter((s) => s.confirmed > 0).length;
  const topSpecies = [...f.species].sort((a, b) => b.inat_obs - a.inat_obs).slice(0, 6);

  return (
    <div className="ln">
      <section className="ln-hero">
        <Waves />
        <Nav />
        <div className="ln-wrap ln-hero-in">
          <div className="stack" style={{ gap: 20 }}>
            <p className="ln-eyebrow">Shoreline fish surveys · Nova Scotia</p>
            <h1>Fish counts from survey video, checked by a person.</h1>
            <p className="ln-lede">Tideflow is where shoreline survey video becomes fish counts. AI marks the fish and sets aside the stretches with none. Volunteers count each snapshot point the way the video analysis procedure asks, and only their counts reach a report.</p>
            <div className="row">
              <Link className="btn primary ln-cta" to="/workspace">Go to workspace</Link>
              <Link className="btn ln-cta ln-ghost" to={JOIN}>Join as a volunteer</Link>
            </div>
          </div>
          <ProductShot f={f} />
        </div>
      </section>

      <section className="ln-wrap ln-stats" aria-label="Tideflow so far">
        {stats.map(([n, label]) => <div key={label}><b className="num">{f.loaded ? n : "…"}</b><span>{label}</span></div>)}
      </section>

      <section className="ln-wrap ln-section" id="how">
        <Head eyebrow="The workflow" title="From the camera to the report, in one place" text="Managers, volunteers and AI each take the part they're best at. The Workflow board shows where every video stands." />
        <ol className="ln-steps">
          {STEPS.map((s, i) => (
            <li key={s.title}><span className="ln-step-n num">0{i + 1}</span><b>{s.title}</b><p>{s.text}</p></li>
          ))}
        </ol>
        <Link className="ln-more" to={sampleTo(f.sample, "summary")}>See a sample report <span aria-hidden>→</span></Link>
      </section>

      <section className="ln-dark" id="ai">
        <div className="ln-wrap ln-section ln-ai">
          <div className="stack" style={{ gap: 28 }}>
            <Head light eyebrow="The AI" title="AI does the searching. People make the call." text="Long stretches of survey video show no fish at all. Tideflow's models find the ones that do, so volunteers spend their time counting, not scrubbing." />
            <div className="ln-ai-grid">
              {AI_POINTS.map((x) => <div key={x.title}><b>{x.title}</b><p>{x.text}</p></div>)}
            </div>
          </div>
          <aside className="ln-ai-card" aria-label="Models">
            <p className="ln-card-kicker">Detection models</p>
            {f.models.map((m) => (
              <div className="ln-model" key={m.key}>
                <span>{m.label}</span>
                {m.default ? <span className="pill accent">Default</span> : <span className="meta">Optional</span>}
              </div>
            ))}
            <p className="ln-card-kicker" style={{ marginTop: 16 }}>Species</p>
            <div className="ln-model"><span>BioCLIP, limited to the Nova Scotia list</span><span className="num meta">{f.species.length} species</span></div>
            <p className="ln-ai-rule">Nothing AI suggests reaches a report until a person confirms it. A frame nobody could see into is left out, never counted as zero.</p>
          </aside>
        </div>
      </section>

      <section className="ln-wrap ln-section" id="data">
        <Head eyebrow="Explore the data" title="Fish and water, side by side" text="Every count adds to a picture of the shoreline: which species live there, and the water they live in." />
        <div className="ln-data">
          <div className="ln-card">
            <div className="ln-card-head">
              <div><b>Species wiki</b><p className="meta">{f.species.length} species recorded in Nova Scotia · {named} named in our footage</p></div>
              <span className="pill up">Live</span>
            </div>
            <table className="ln-table">
              <thead><tr><th>Species</th><th className="right">iNaturalist sightings</th></tr></thead>
              <tbody>
                {topSpecies.map((s) => (
                  <tr key={s.species}>
                    <td><b>{s.common || s.species}</b><span className="meta"><i>{s.species}</i></span></td>
                    <td className="right num">{s.inat_obs.toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <Link className="ln-more" to="/species">Open the species wiki <span aria-hidden>→</span></Link>
          </div>
          <div className="ln-card">
            <div className="ln-card-head">
              <div><b>Water quality</b><p className="meta">Coastal Action's public river readings, from the LaHave River</p></div>
              <span className="pill warn">Coming soon</span>
            </div>
            <div className="ln-water">
              {WATER.map((w) => (
                <div key={w.name}><span className="meta">{w.name}</span><b className="num">—{w.unit && <small> {w.unit}</small>}</b></div>
              ))}
            </div>
            <p className="ln-card-note">Readings will sit beside the fish counts from the same sites, so a change in one can be checked against the other.</p>
          </div>
        </div>
      </section>

      <section className="ln-wrap ln-section" id="volunteer">
        <div className="ln-volunteer">
          <div className="stack" style={{ gap: 16 }}>
            <Head light eyebrow="Volunteer" title="Help count the fish of your shoreline" text="No experience needed. The procedure walks you through each frame, on a laptop or a phone, and every point you save goes into the site reports." />
            <div className="row">
              <Link className="btn primary ln-cta ln-white" to={JOIN}>Join as a volunteer</Link>
              <Link className="btn ln-cta ln-ghost" to={sampleTo(f.sample, "snapshots")}>Try a sample first</Link>
            </div>
          </div>
          <ol className="ln-join">
            {VOLUNTEER.map((s, i) => <li key={s.title}><span className="num">{i + 1}</span><div><b>{s.title}</b><p>{s.text}</p></div></li>)}
          </ol>
        </div>
      </section>

      <footer className="ln-foot">
        <div className="ln-wrap ln-foot-grid">
          <div className="stack" style={{ gap: 10 }}>
            <Brand dark />
            <p className="meta" style={{ maxWidth: 340, lineHeight: 1.6 }}>Underwater video in, confirmed fish counts out, for the people who survey Nova Scotia's living shorelines. Built at RBC HubHacks 2026 with Coastal Action.</p>
          </div>
          <div className="ln-foot-col"><b>Platform</b><Link to="/workspace">Workspace</Link><Link to="/workflow">Workflow board</Link><Link to="/reports">Reports</Link><Link to="/login">Sign in</Link></div>
          <div className="ln-foot-col"><b>Explore</b><Link to="/species">Species wiki</Link><Link to="/river">Water quality</Link><a href="#ai">How the AI works</a></div>
          <div className="ln-foot-col"><b>Project</b><a href="https://github.com/allenyan513/the_coastal_coders" target="_blank" rel="noreferrer">Source on GitHub</a><span className="meta">RBC HubHacks 2026</span><span className="meta">Coastal Action</span></div>
        </div>
        <div className="ln-wrap ln-foot-fine meta">
          <span>Fish detection by the Community Fish Detector and other open models; species suggestions by BioCLIP. Species list from iNaturalist and OBIS records.</span>
          <span>© 2026 Tideflow</span>
        </div>
      </footer>
    </div>
  );
}
