import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { AccuracyRow, api, clock, DiversityStats, MaxnStats, SpeciesRow, Summary, surveyApi, SurveyTree, Track, Validation, validationApi, Video } from "./api";
import { AiImpact } from "./AiImpact";
import { TrendCard } from "./TrendChart";
import { MeanCard, NonFishCard, SpeciesDonut } from "./ReportCharts";
import { colorOf, isNonFish, loadSpecies, UNIDENTIFIED_COLOR, UNIDENTIFIED_LABEL } from "./speciesTally";
import { VideoHeader } from "./VideoHeader";

export function SummaryPage() {
  const { id = "" } = useParams();
  const [s, setS] = useState<Summary | null>(null);

  const [m, setM] = useState<MaxnStats | null>(null);

  useEffect(() => { api.summary(id).then(setS); }, [id]);
  // MaxN loads on its own, so if it fails the rest of the report still shows.
  useEffect(() => { api.maxn(id).then(setM).catch(() => setM(null)); }, [id]);
  const [dv, setDv] = useState<DiversityStats | null>(null);
  useEffect(() => { api.diversity(id).then(setDv).catch(() => setDv(null)); }, [id]);
  const [names, setNames] = useState<SpeciesRow[]>([]);
  useEffect(() => { api.species().then(setNames).catch(() => setNames([])); }, []);
  const [meanOf, setMeanOf] = useState("all"); // the Mean count card: all fish, or one species
  // Where and when this video was filmed, and the other stations, for the trend chart.
  const [me, setMe] = useState<Video | null>(null);
  useEffect(() => { api.videos().then((all) => setMe(all.find((v) => v.id === id) ?? null)).catch(() => setMe(null)); }, [id]);
  // AI's detections and blind-count accuracy, for the cards about AI's part in the review.
  const [tracks, setTracks] = useState<Track[] | null>(null);
  useEffect(() => { api.tracks(id).then(setTracks).catch(() => setTracks([])); }, [id]);
  const [acc, setAcc] = useState<AccuracyRow | null>(null);
  useEffect(() => { api.accuracy().then((r) => setAcc(r.videos.find((v) => v.id === id) ?? null)).catch(() => setAcc(null)); }, [id]);
  const [val, setVal] = useState<Validation | null>(null);
  useEffect(() => { validationApi.report(id).then(setVal).catch(() => setVal(null)); }, [id]);
  const [tree, setTree] = useState<SurveyTree | null>(null);
  useEffect(() => { surveyApi.tree().then(setTree).catch(() => setTree(null)); }, []);
  if (!s) return <p className="meta">Loading…</p>;

  const snap = s.snapshots;
  // Species counted on the Count tab. A trial kept in this browser, so it sits beside the saved numbers.
  const tagged = loadSpecies(id);
  const nameOf = (sp: string) => (sp ? names.find((r) => r.species === sp)?.common || sp : UNIDENTIFIED_LABEL);
  const counted = s.points.filter((p) => p.status === "checked");
  const perPoint = new Map(counted.map((p) => {
    const n = new Map<string, number>();
    (tagged.frames[p.id] ?? []).filter((t) => !isNonFish(t.species)).forEach((t) => n.set(t.species, (n.get(t.species) ?? 0) + 1));
    const named = [...n.values()].reduce((a, b) => a + b, 0);
    if ((p.total ?? 0) > named) n.set("", (p.total ?? 0) - named);
    return [p.id, n] as const;
  }));
  const speciesRows = ["", ...tagged.palette, ...new Set(counted.flatMap((p) => (tagged.frames[p.id] ?? []).map((t) => t.species)))]
    .filter((sp) => !isNonFish(sp))
    .filter((sp, i, all) => all.indexOf(sp) === i)
    .map((sp) => {
      const each = counted.map((p) => perPoint.get(p.id)?.get(sp) ?? 0);
      return { sp, total: each.reduce((a, b) => a + b, 0), seen: each.filter(Boolean).length, max: Math.max(0, ...each) };
    })
    .filter((r) => r.total > 0);
  const anyTagged = counted.some((p) => (tagged.frames[p.id] ?? []).some((t) => !isNonFish(t.species)));
  const countLink = `/videos/${id}/snapshots`;

  // The three cards at the top: fish by species, the mean count, and anything that isn't a fish.
  const fishCounted = counted.reduce((a, p) => a + (p.total ?? 0), 0);
  const slices = speciesRows.map((r) => ({ key: r.sp || "unidentified", label: nameOf(r.sp), n: r.total, color: colorOf(tagged.palette, r.sp) }))
    .sort((a, b) => b.n - a.n);
  const meanOptions = [
    { key: "all", label: "All fish", color: UNIDENTIFIED_COLOR },
    ...speciesRows.filter((r) => r.sp).map((r) => ({ key: r.sp, label: nameOf(r.sp), color: colorOf(tagged.palette, r.sp) })),
  ];
  const meanKey = meanOptions.some((o) => o.key === meanOf) ? meanOf : "all";
  const meanValues = [...counted].sort((a, b) => a.t - b.t)
    .map((p) => ({ id: p.id, t: p.t, n: meanKey === "all" ? p.total ?? 0 : perPoint.get(p.id)?.get(meanKey) ?? 0 }));
  const meanNow = meanKey === "all"
    ? snap.mean_count
    : counted.length ? meanValues.reduce((a, v) => a + v.n, 0) / counted.length : null;
  // The trend chart: this report's mean is the newest point of each line.
  const stationName = (sid: string) => {
    const st = tree?.stations.find((x) => x.id === sid);
    const tr = tree?.transects.find((t) => t.id === st?.transectId);
    const site = tree?.sites.find((x) => x.id === tr?.siteId);
    return st ? [site?.name, tr?.name, st.name].filter(Boolean).join(" · ") : "";
  };
  const trendSeries = meanOptions.map((o) => ({
    ...o,
    current: o.key === "all" ? snap.mean_count : counted.length ? counted.reduce((a, p) => a + (perPoint.get(p.id)?.get(o.key) ?? 0), 0) / counted.length : null,
  }));
  const stationId = me?.station_id || `site:${s.video.site || id}`;
  const otherStations = (tree?.stations ?? []).filter((x) => !x.archived && x.id !== me?.station_id).map((x) => ({ id: x.id, label: stationName(x.id) }));
  const filmedOn = me?.filmed_on || new Date().toISOString().slice(0, 10);
  const nonFishTotals = new Map<string, { n: number; seen: number }>();
  counted.forEach((p) => {
    const here = new Map<string, number>();
    (tagged.frames[p.id] ?? []).filter((t) => isNonFish(t.species)).forEach((t) => here.set(t.species, (here.get(t.species) ?? 0) + 1));
    here.forEach((n, sp) => {
      const was = nonFishTotals.get(sp) ?? { n: 0, seen: 0 };
      nonFishTotals.set(sp, { n: was.n + n, seen: was.seen + 1 });
    });
  });
  const nonFishRows = [...nonFishTotals].map(([sp, v]) => ({ key: sp, label: sp, ...v })).sort((a, b) => b.n - a.n);
  // Invertebrates saved on the record before non-fish could be tagged still show here.
  const recorded = counted.filter((p) => (p.invertebrates ?? 0) > 0);
  if (!nonFishRows.length && recorded.length) {
    nonFishRows.push({ key: "invertebrates", label: "Invertebrates", n: recorded.reduce((a, p) => a + (p.invertebrates ?? 0), 0), seen: recorded.length });
  }

  const total = s.video.duration || 1;
  const pct = (v: number) => `${Math.round((v / total) * 100)}%`;
  const queue = s.reviewed + s.could_not_see + s.pending;
  const school = s.schools.reduce((n, c) => n + c.total, 0);
  const most = Math.max(1, ...s.species.map((r) => r.entries));
  const mostMaxn = Math.max(1, ...(m?.species ?? []).map((r) => r.maxn));
  const mayRise = m?.partial ? `May rise: ${m.undecided_tracks} ${m.undecided_tracks === 1 ? "track" : "tracks"} not decided yet.` : "";
  const parts = [
    { name: "Reviewed", value: s.reviewed, color: "var(--up)" },
    { name: "Could not see", value: s.could_not_see, color: "var(--amber)" },
    { name: "Still in the queue", value: s.pending, color: "var(--text-2)" },
    { name: "Skipped by AI", value: s.skipped, color: "var(--skip)" },
  ];
  const facts: [string, string][] = [
    ["Fish AI missed, added by a person", `${s.entries_added} of ${s.entries} entries`],
    ["Open AI suggestions, not counted", String(s.open_suggestions)],
    ["Audit of skipped footage", `${s.audit_segments} of ${s.audit_total} done, ${s.audit_fish} fish found`],
    ["Time spent reviewing", clock(s.review_seconds)],
    ["Points could not see", String(snap.could_not_see)],
    ["Busiest moments checked", `${snap.peak_checked} of ${snap.peak_total}`],
  ];

  return (
    <div className="stack" style={{ gap: 16 }}>
      <VideoHeader id={id} step="report" />
      <div className="pagehead">
        <div>
          <h1>Report</h1>
          <p className="lede">Analysis window {clock(s.protocol.start)} to {clock(s.protocol.end)}. Only counts a person confirmed are included.</p>
          {val?.approval ? (
            <p className="report-approval"><span className="pill up">Validated</span> Approved by <b>{val.approval.approver}</b> on {new Date(`${val.approval.approved_at.replace(" ", "T")}Z`).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" })}</p>
          ) : val?.ready ? (
            <p className="report-approval"><span className="pill muted">Not approved yet</span> <Link to={`/videos/${id}/validate`}>{val.points.filter((p) => p.state === "agree").length} of {val.points.length} sampled points agree</Link></p>
          ) : null}
        </div>
        <a className="btn primary" href={`/api/videos/${id}/protocol.csv`}>Export analysis sheet</a>
      </div>

      <div className="report-hero">
        <SpeciesDonut slices={slices} total={fishCounted} countLink={countLink} />
        <MeanCard
          options={meanOptions}
          value={meanKey}
          onChange={setMeanOf}
          mean={meanNow}
          values={meanValues}
          checked={snap.frames_checked}
          totalPoints={snap.frames_total}
          countLink={countLink}
        />
        <NonFishCard rows={nonFishRows} checked={counted.length} countLink={countLink} />
      </div>

      <TrendCard
        series={trendSeries}
        stationId={stationId}
        stationLabel={me?.station_id ? stationName(me.station_id) : s.video.site}
        stations={otherStations}
        filmedOn={filmedOn}
      />

      {anyTagged && (
        <section className="panel" style={{ overflowX: "auto" }}>
          <div className="panel-head">
            <h2>Species at the sub-sample points</h2>
            <span className="pill muted">Trial, kept in this browser</span>
          </div>
          <table>
            <thead><tr><th>Species</th><th className="right">Fish counted</th><th className="right">Per point</th><th className="right">Most at one point</th><th className="right">Points seen at</th></tr></thead>
            <tbody>
              {speciesRows.map((r) => (
                <tr key={r.sp || "unidentified"}>
                  <td><span className="species-swatch" style={{ background: colorOf(tagged.palette, r.sp) }} />{nameOf(r.sp)}</td>
                  <td className="num right">{r.total}</td>
                  <td className="num right">{(r.total / (counted.length || 1)).toFixed(2)}</td>
                  <td className="num right">{r.max}</td>
                  <td className="num right">{r.seen} of {counted.length}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      <AiImpact s={s} tracks={tracks} accuracy={acc} nameOf={nameOf} />

      {!!s.peaks.length && (
        <section className="panel" style={{ overflowX: "auto" }}>
          <div className="panel-head"><h2>Busiest moments AI found</h2></div>
          <p className="meta" style={{ padding: "0 16px 12px", lineHeight: 1.6 }}>
            MeanCount only sees the sub-sample points, so a school that passes between two of them isn't in it. These are AI's busiest moments away from those points. AI's numbers are unchecked until a person opens the frame, and they never feed MeanCount.
          </p>
          <table>
            <thead><tr><th>Time</th><th>Where</th><th className="right">AI's count</th><th className="right">Person's count</th><th /></tr></thead>
            <tbody>
              {s.peaks.map((p) => (
                <tr key={p.id}>
                  <td className="num">{clock(p.t)}</td>
                  <td>{p.in_window ? "Between points" : "Outside the window"}</td>
                  <td className="num right">{p.ai_count}</td>
                  <td className="num right">{p.status === "checked" ? p.total : p.status ? "Could not see" : "—"}</td>
                  <td className="right"><Link className="btn" to={`/videos/${id}/snapshots?mode=ai&frame=${p.id}`}>Check frame</Link></td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      <details className="stack">
        <summary className="meta">AI-assisted review of the whole video</summary>
        <div className="stack" style={{ gap: 16, marginTop: 12 }}>
      <section className="panel" aria-label="Footage">
        <div className="kpis big">
          <div className="kpi"><span className="meta">Footage</span><b>{clock(s.video.duration)}</b></div>
          <div className="kpi">
            <span className="meta">Queued for a person to watch</span>
            <b>{clock(queue)}</b>
            <small className="meta num">{pct(queue)} of the footage</small>
          </div>
          <div className="kpi">
            <span className="meta">Skipped by AI</span>
            <b>{pct(s.skipped)}</b>
            <small className="meta num">{clock(s.skipped)} with no detections</small>
          </div>
        </div>
        <div className="panel-pad" style={{ gap: 10, padding: "4px 20px 16px" }}>
          <div className="band" role="img" aria-label={parts.map((p) => `${p.name} ${clock(p.value)}`).join(", ")}>
            {parts.filter((p) => p.value > 0).map((p) => <i key={p.name} title={`${p.name}: ${clock(p.value)}, ${pct(p.value)}`} style={{ flex: `${p.value} 0 0`, background: p.color }} />)}
          </div>
          <div className="legend">
            {parts.map((p) => <span key={p.name}><i style={{ background: p.color }} />{p.name} <b className="num" style={{ color: "var(--text)", fontWeight: 500 }}>{clock(p.value)}</b></span>)}
          </div>
        </div>
      </section>

      <div className="panel kpis">
        <div className="kpi">
          <span className="meta">Most fish in one frame</span>
          <b>{snap.largest_count ?? "—"}</b>
          <small className="meta">{snap.largest_count === null ? "Needs a count" : snap.largest_label}</small>
        </div>
        {m && (
          <div className="kpi">
            <span className="meta">Most confirmed fish at once</span>
            <b>{m.maxn}</b>
            <small className="meta num">
              {m.maxn_t === null ? "Nothing confirmed yet" : `MaxN from tracks, at ${clock(m.maxn_t)}`}
              {mayRise && <><br />{mayRise}</>}
            </small>
          </div>
        )}
        <div className="kpi">
          <span className="meta">Fish entries</span>
          <b>{s.entries}</b>
          <small className="meta">Confirmed tracks. One fish can count twice.</small>
        </div>
        <div className="kpi"><span className="meta">Species named</span><b>{s.species_count}</b></div>
        {!!s.schools.length && <div className="kpi"><span className="meta">Fish in counted schools</span><b>{school}</b></div>}
      </div>

      <div className="split report-split">
        <div className="stack">
          <section className="panel">
            <div className="panel-head">
              <h2>Fish entries by species</h2>
            </div>
            {s.species.map((r) => (
              <div className="sbar-row" key={r.name} title={`${r.name}: ${r.entries} ${r.entries === 1 ? "entry" : "entries"}`}>
                <span>{r.name}</span>
                <span><i className="sbar" style={{ width: `${(r.entries / most) * 100}%` }} /></span>
                <span className="num right">{r.entries}</span>
              </div>
            ))}
            {!s.species.length && <p className="meta" style={{ padding: 12 }}>Nothing confirmed yet.</p>}
          </section>
          {m && (
            <section className="panel">
              <div className="panel-head">
                <h2>MaxN by species</h2>
              </div>
              {m.species.map((r) => (
                <div className="sbar-row" key={r.species} title={`${r.species}: up to ${r.maxn} at once${r.t === null ? "" : `, first at ${clock(r.t)}`}`}>
                  <span>{r.species}{r.t !== null && <small className="meta num"> at {clock(r.t)}</small>}</span>
                  <span><i className="sbar" style={{ width: `${(r.maxn / mostMaxn) * 100}%` }} /></span>
                  <span className="num right">{r.maxn}</span>
                </div>
              ))}
              {!m.species.length && <p className="meta" style={{ padding: 12 }}>Nothing confirmed yet.</p>}
              <p className="meta" style={{ padding: "8px 12px 12px", lineHeight: 1.6 }}>
                The most confirmed fish of each species on screen at the same moment. One fish split into several tracks can't
                raise it. AI often misses fish in a dense school, so it can be lower than the hand count. {mayRise}
              </p>
            </section>
          )}
          {dv && (
            <section className="panel">
              <div className="panel-head">
                <h2>Species diversity</h2>
              </div>
              <div className="kpis">
                <div className="kpi">
                  <span className="meta">Shannon index (H)</span>
                  <b>{fixed(dv.shannon)}</b>
                  <small className="meta">0 is one species. Higher means more species, more evenly split.</small>
                </div>
                <div className="kpi">
                  <span className="meta">Evenness (J)</span>
                  <b>{fixed(dv.evenness)}</b>
                  <small className="meta">From 0 to 1. 1 means every species is equally common.</small>
                </div>
                <div className="kpi">
                  <span className="meta">Simpson's diversity (1 − D)</span>
                  <b>{fixed(dv.simpson_diversity)}</b>
                  <small className="meta">Chance two fish picked at random are different species.</small>
                </div>
                <div className="kpi">
                  <span className="meta">Inverse Simpson (1 / D)</span>
                  <b>{fixed(dv.inverse_simpson)}</b>
                  <small className="meta">Effective number of equally common species.</small>
                </div>
              </div>
              <p className="meta" style={{ padding: "8px 12px 12px", lineHeight: 1.6 }}>
                From {dv.richness} named species, using each species' MaxN as its count.
                {dv.unidentified_maxn > 0 && ` ${dv.unidentified_maxn} unidentified ${dv.unidentified_maxn === 1 ? "fish is" : "fish are"} left out.`}
                {dv.richness < 2 && " Diversity needs at least two named species, so some values are blank."}
                {dv.partial && " May change: some tracks are not decided yet."}
              </p>
            </section>
          )}
          {!!s.schools.length && (
            <section className="panel" style={{ overflowX: "auto" }}>
              <div className="panel-head"><h2>School counts</h2></div>
              <table>
                <thead><tr><th>Time</th><th className="right">Total</th><th className="right">AI proposed</th><th className="right">Removed</th><th className="right">Added</th></tr></thead>
                <tbody>
                  {s.schools.map((c, i) => (
                    <tr key={i}><td className="num">{clock(c.t)}</td><td className="num right">{c.total}</td><td className="num right">{c.proposed}</td><td className="num right">{c.removed}</td><td className="num right">{c.added}</td></tr>
                  ))}
                </tbody>
              </table>
            </section>
          )}
        </div>
        <section className="panel panel-pad">
          <h2>What this covers</h2>
          {facts.map(([k, v]) => (
            <div key={k} className="row" style={{ justifyContent: "space-between", fontSize: 13 }}><span>{k}</span><span className="num">{v}</span></div>
          ))}
          <p style={{ color: "var(--text-2)", fontSize: 13, lineHeight: 1.6, borderTop: "1px solid var(--border-2)", paddingTop: 12, marginTop: 4 }}>
            {s.audit_fish > 0 ? "The audit found fish in skipped footage, so totals may be low. " : ""}
            {s.partial && !snap.complete ? "MaxN isn't reported because this was a partial review. " : ""}
            {snap.complete && snap.peak_total > snap.peak_checked + snap.peak_could_not_see ? "Some peak frames are still open, so MaxN may rise. " : ""}
            Could not see is never counted as zero.
          </p>
          <p className="meta" style={{ lineHeight: 1.6 }}>{s.video.notes}</p>
        </section>
      </div>
      <a className="btn" style={{ alignSelf: "flex-start" }} href={`/api/videos/${id}/export.csv`}>Export review data</a>
        </div>
      </details>
    </div>
  );
}

/** A number to two decimal places, or a dash when there is no value. */
function fixed(v: number | null): string {
  return v === null ? "—" : v.toFixed(2);
}
