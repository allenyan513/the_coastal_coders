import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, WaterSite } from "./api";
import { countProgress } from "./Library";
import { bySeason, buildCells, Cell, SAMPLE_CELLS, SAMPLE_TREE, VideoResult } from "./reportData";
import { distanceKm, MapStation, parseCoordinates, StationMap } from "./StationMap";
import { activeTree, NO_DATE, useSurveys } from "./surveyStore";

const one = (n: number | null | undefined) => (n === null || n === undefined ? "—" : n.toFixed(1));
// A water sampling site further away than this isn't offered as the station's nearest.
const NEAR_KM = 5;
const signed = (n: number) => `${n > 0 ? "+" : n < 0 ? "−" : "±"}${Math.abs(n).toFixed(1)}`;

function csvRow(values: (string | number | null)[]) {
  return values.map((v) => `"${String(v ?? "").replace(/"/g, '""')}"`).join(",");
}

function download(name: string, rows: string[]) {
  const link = document.createElement("a");
  link.href = URL.createObjectURL(new Blob([`﻿${rows.join("\r\n")}`], { type: "text/csv" }));
  link.download = name;
  link.click();
  URL.revokeObjectURL(link.href);
}

type Bar = { label: string; season: string; value: number | null; latest: boolean };

function BarPair({ label, bars, most, picked, onPick }: { label: string; bars: Bar[]; most: number; picked: boolean; onPick: () => void }) {
  return (
    <div className={`rstation ${picked ? "picked" : ""}`} onClick={onPick}>
      <div className="rbars">
        {bars.map((b) => (
          <div className={`rbar ${b.latest ? "latest" : ""}`} key={b.season} tabIndex={0} aria-label={`${b.label}, ${b.season}: ${one(b.value)}`}>
            {b.latest && b.value !== null && <span className="rvalue num">{one(b.value)}</span>}
            <i style={{ height: `${((b.value ?? 0) / most) * 100}%` }} />
            <span className="rtip" role="tooltip"><b className="num">{one(b.value)}</b> {b.season}</span>
          </div>
        ))}
      </div>
      <button type="button" className="rlabel" aria-pressed={picked}>{label}</button>
    </div>
  );
}

/** The site's answer: is each station changing? Everything below the chart is the detail behind it. */
export function Reports() {
  const data = useSurveys();
  const [results, setResults] = useState<VideoResult[] | null>(null);
  const [error, setError] = useState("");
  const [picked, setPicked] = useState<boolean | null>(null);
  const [siteId, setSiteId] = useState("");
  const [pickedId, setPickedId] = useState("");
  const [water, setWater] = useState<WaterSite[]>([]);
  const navigate = useNavigate();

  // Coastal Action's water sampling sites, shown on the station map. The map still works without them.
  useEffect(() => { api.waterSites().then(setWater).catch(() => setWater([])); }, []);

  useEffect(() => {
    api.videos()
      .then((all) => Promise.all(all.filter((v) => v.status === "Ready to review").map(async (video) => ({
        video,
        summary: await api.summary(video.id),
        // MaxN loads on its own, so a video without it still reports its MeanCount.
        maxn: await api.maxn(video.id).then((m) => m.maxn).catch(() => null),
      }))))
      .then((rows) => {
        const best = new Map<string, VideoResult>();
        rows.forEach((r) => {
          const root = r.video.source_id || r.video.id;
          const kept = best.get(root);
          if (!kept || countProgress(r.summary).done > countProgress(kept.summary).done) best.set(root, r);
        });
        setResults([...best.values()]);
      })
      .catch((e) => setError(e.message));
  }, []);

  const realCells = useMemo(() => buildCells(results ?? [], data), [results, data]);
  if (error) return <p className="meta">{error}</p>;
  if (!results) return <p className="meta">Loading…</p>;

  const hasReal = realCells.some((c) => c.finished > 0);
  const sample = picked ?? !hasReal;
  // Sample data comes with its own made-up stations, so the page can show a full site with a map.
  const tree = sample ? SAMPLE_TREE : activeTree(data);
  const current = tree.find((t) => t.site.id === siteId) ?? tree[0];
  const stations = current?.stations ?? [];
  const inSite = (sample ? SAMPLE_CELLS : realCells).filter((c) => stations.some((s) => s.station.id === c.stationId));
  const finishedSeasons = [...new Set(inSite.filter((c) => c.finished > 0).map((c) => c.season))].sort(bySeason);
  // Undated videos can't be placed in time, so they only stand in when nothing has a date.
  const dated = finishedSeasons.filter((s) => s !== NO_DATE);
  const seasons = dated.length ? dated : finishedSeasons;
  const latest = seasons[seasons.length - 1];
  const base = seasons[seasons.length - 2];
  const cellAt = (stationId: string, name?: string): Cell | undefined => inSite.find((c) => c.stationId === stationId && c.season === name);
  const counted = stations.filter((s) => cellAt(s.station.id, latest)?.mean != null);
  const compared = stations.filter((s) => cellAt(s.station.id, latest)?.mean != null && cellAt(s.station.id, base)?.mean != null);
  const higher = compared.filter((s) => cellAt(s.station.id, latest)!.mean! > cellAt(s.station.id, base)!.mean!);
  const latestCells = counted.map((s) => cellAt(s.station.id, latest)!);
  const siteMean = latestCells.length ? latestCells.reduce((n, c) => n + c.mean!, 0) / latestCells.length : null;
  const siteMax = latestCells.some((c) => c.maxn !== null) ? Math.max(...latestCells.map((c) => c.maxn ?? 0)) : null;
  const siteSpecies = new Set(latestCells.flatMap((c) => c.species)).size;
  const most = Math.max(1, ...inSite.map((c) => c.mean ?? 0));
  const shownSeasons = [base, latest].filter((s): s is string => !!s);
  const transects = [...new Map(stations.map((s) => [s.transect.id, s.transect])).values()];
  const changeOf = (stationId: string) => {
    const now = cellAt(stationId, latest)?.mean;
    const before = cellAt(stationId, base)?.mean;
    return now != null && before != null ? Number(now.toFixed(1)) - Number(before.toFixed(1)) : null;
  };

  // The map places every station with coordinates. The rest are listed under it.
  const mapStations: MapStation[] = stations.flatMap((s) => {
    const at = parseCoordinates(s.station.coordinates);
    if (!at) return [];
    const now = cellAt(s.station.id, latest)?.mean ?? null;
    return [{ id: s.station.id, label: s.label, transectId: s.transect.id, transect: s.transect.name, at, now, change: changeOf(s.station.id), size: Math.round(22 + ((now ?? 0) / most) * 22) }];
  });
  const unplaced = stations.filter((s) => !parseCoordinates(s.station.coordinates));
  const focus = stations.find((s) => s.station.id === pickedId) ?? stations.find((s) => mapStations.some((m) => m.id === s.station.id)) ?? stations[0];
  const pickedAt = focus ? parseCoordinates(focus.station.coordinates) : null;
  const pickedNow = focus && cellAt(focus.station.id, latest);
  const pickedBefore = focus && cellAt(focus.station.id, base);
  const pickedChange = focus ? changeOf(focus.station.id) : null;
  const pickedLinks = focus ? inSite.filter((c) => c.stationId === focus.station.id).flatMap((c) => c.links) : [];
  const nearestWater = pickedAt
    ? water.map((w) => ({ w, km: distanceKm(pickedAt, [w.lat, w.lon]) })).sort((a, b) => a.km - b.km)[0]
    : undefined;

  const unfiled = results.filter((r) => !data.places[r.video.source_id || r.video.id]).length;
  const undated = results.filter((r) => { const root = r.video.source_id || r.video.id; return data.places[root] && !data.filmedOn[root]; }).length;

  const answer = !latest
    ? "No station has a finished count yet."
    : compared.length
      ? `${higher.length} of ${compared.length} ${compared.length === 1 ? "station" : "stations"} counted higher in ${latest} than in ${base}.`
      : `${counted.length} of ${stations.length} ${stations.length === 1 ? "station" : "stations"} counted${latest === NO_DATE ? "" : ` in ${latest}`}.`;

  const exportRows = () => download(`tideflow-report-${(current?.site.name ?? "site").replace(/\W+/g, "-").toLowerCase()}.csv`, [
    csvRow(["data", "site", "transect", "station", "season", "videos", "videos_fully_counted", "mean_count", "maxn", "species_observed", "species"]),
    ...stations.flatMap((s) => inSite.filter((c) => c.stationId === s.station.id).sort((a, b) => bySeason(a.season, b.season)).map((c) => csvRow([
      sample ? "sample, not survey results" : "survey", current.site.name, s.transect.name, s.station.name, c.season, c.videos, c.finished, c.mean?.toFixed(2) ?? "", c.maxn, c.species.length, c.species.join("; "),
    ]))),
  ]);

  return (
    <div className="stack" style={{ gap: 20 }}>
      <div className="pagehead">
        <div>
          <h1>Station report</h1>
          <p className="lede">{answer}</p>
        </div>
        <div className="row">
          <label className="field report-site">Site
            <select value={current?.site.id ?? ""} onChange={(e) => setSiteId(e.target.value)}>
              {tree.map((t) => <option key={t.site.id} value={t.site.id}>{t.site.name}</option>)}
            </select>
          </label>
          <button className="btn tall" disabled={!inSite.length} onClick={exportRows}>Download CSV</button>
        </div>
      </div>

      {sample && <p className="sample-note"><b>Sample data, not survey results.</b> It shows how this page reads once stations are counted.</p>}

      <div className="panel kpis">
        <div className="kpi"><span className="meta">MeanCount{latest ? `, ${latest}` : ""}</span><b>{one(siteMean)}</b><small className="meta">Average across stations</small></div>
        <div className="kpi"><span className="meta">MaxN</span><b>{siteMax ?? "—"}</b><small className="meta">Highest at any station</small></div>
        <div className="kpi"><span className="meta">Species</span><b>{latest ? siteSpecies : "—"}</b><small className="meta">Across the site</small></div>
        <div className="kpi"><span className="meta">Stations counted</span><b>{counted.length} of {stations.length}</b><small className="meta">Fully counted videos only</small></div>
      </div>

      {focus && (
        <section className="panel smap-panel" aria-label="Station map">
          <div className="smap-main">
            <div>
              <h2>Where the stations are</h2>
              <p className="meta">
                Circle size is MeanCount{latest ? ` in ${latest}` : ""}.{base ? ` Color is the change since ${base}.` : ""} Click a station to see its numbers.
              </p>
            </div>
            {mapStations.length > 0 ? (
              <>
                <StationMap
                  stations={mapStations}
                  water={water.map((w) => ({ id: w.site_id, name: w.site_name, at: [w.lat, w.lon] }))}
                  picked={focus.station.id}
                  onPick={setPickedId}
                  onWater={() => navigate("/analysis/trends")}
                  fitKey={`${sample}|${current?.site.id}`}
                  base={base}
                />
                <div className="row smap-legend">
                  <span><i className="up" />Counted higher ▲</span>
                  <span><i className="down" />Counted lower ▼</span>
                  <span><i className="line" />Transect</span>
                  <span><i className="water" />Water site, opens Fish and water</span>
                </div>
                {unplaced.length > 0 && (
                  <p className="smap-note">
                    Not on the map: <b>{unplaced.map((s) => s.label).join(", ")}</b> {unplaced.length === 1 ? "has" : "have"} no coordinates.{" "}
                    {!sample && <Link to="/workspace">Add them in Surveys</Link>}
                  </p>
                )}
              </>
            ) : (
              <p className="smap-note">
                No station at {current?.site.name} has coordinates yet. <Link to="/workspace">Add them in Surveys</Link> to see the stations on a map.
              </p>
            )}
          </div>

          <aside className="smap-side" aria-live="polite">
            <span className="side-label" style={{ padding: 0 }}>Picked station</span>
            <div>
              <h2 className="smap-name">{focus.label}</h2>
              <span className="meta num">
                {pickedAt ? `${pickedAt[0].toFixed(4)}, ${pickedAt[1].toFixed(4)}` : "No coordinates"}
                {focus.station.depth && ` · ${focus.station.depth} m deep`}
              </span>
            </div>
            <div>
              <span className="meta">MeanCount{latest ? `, ${latest}` : ""}</span>
              <div className="row" style={{ gap: 10, marginTop: 4 }}>
                <b className="smap-big num">{one(pickedNow?.mean)}</b>
                {pickedChange !== null && <span className={`pill ${pickedChange >= 0 ? "up" : "down"}`}>{signed(pickedChange)} since {base}</span>}
              </div>
            </div>
            <dl className="smap-facts">
              <div><dt>{base ?? "Season before"}</dt><dd className="num">{one(pickedBefore?.mean)}</dd></div>
              <div><dt>MaxN</dt><dd className="num">{pickedNow?.maxn ?? "—"}</dd></div>
              <div><dt>Species</dt><dd className="num">{pickedNow ? pickedNow.species.length : "—"}</dd></div>
              <div>
                <dt>Nearest water site</dt>
                <dd>
                  {nearestWater && nearestWater.km <= NEAR_KM
                    ? <Link to="/analysis/trends">{nearestWater.w.site_name}, {nearestWater.km.toFixed(1)} km</Link>
                    : pickedAt ? `None within ${NEAR_KM} km` : "—"}
                </dd>
              </div>
            </dl>
            {pickedNow && pickedNow.species.length > 0 && <p className="meta">{pickedNow.species.join(", ")}</p>}
            <div className="row">
              {pickedLinks.map((l) => <Link key={l.id} className="vname" to={`/videos/${l.id}/summary`}>{l.name}</Link>)}
              {sample && <span className="meta">Sample station, no footage</span>}
              {!sample && pickedLinks.length === 0 && <span className="meta">No footage yet</span>}
            </div>
          </aside>
        </section>
      )}

      <section className="panel">
        <div className="panel-head rhead">
          <h2>MeanCount by station</h2>
          {shownSeasons.length > 0 && (
            <div className="row rlegend">
              {shownSeasons.map((s) => <span key={s}><i className={s === latest ? "latest" : ""} />{s}</span>)}
            </div>
          )}
        </div>
        {latest ? (
          <div className="rchart">
            {transects.map((t) => (
              <div className="rgroup" key={t.id}>
                <div className="rgroup-bars">
                  {stations.filter((s) => s.transect.id === t.id).map((s) => (
                    <BarPair
                      key={s.station.id}
                      label={s.station.name}
                      most={most}
                      picked={s.station.id === focus?.station.id}
                      onPick={() => setPickedId(s.station.id)}
                      bars={shownSeasons.map((name) => ({ label: s.label, season: name, value: cellAt(s.station.id, name)?.mean ?? null, latest: name === latest }))}
                    />
                  ))}
                </div>
                <span className="rtransect">{t.name}</span>
              </div>
            ))}
          </div>
        ) : <p className="meta" style={{ padding: 16 }}>Finish counting a video to see it here.</p>}
      </section>

      <section className="panel" style={{ overflowX: "auto" }}>
        <table className="cards">
          <thead>
            <tr>
              <th>Station</th>
              {base && <th className="right">{base}</th>}
              <th className="right">{latest ?? "MeanCount"}</th>
              {base && <th className="right">Change</th>}
              <th className="right">MaxN</th><th className="right">Species</th><th>Videos</th>
            </tr>
          </thead>
          <tbody>
            {stations.map((s) => {
              const now = cellAt(s.station.id, latest);
              const before = cellAt(s.station.id, base);
              const change = changeOf(s.station.id);
              const all = inSite.filter((c) => c.stationId === s.station.id);
              const waiting = all.reduce((n, c) => n + c.videos - c.finished, 0);
              const links = all.flatMap((c) => c.links);
              return (
                <tr key={s.station.id} className={s.station.id === focus?.station.id ? "picked" : ""}>
                  <td><button type="button" className="rowpick" aria-pressed={s.station.id === focus?.station.id} onClick={() => setPickedId(s.station.id)}>{s.label}</button></td>
                  {base && <td className="num right" data-label={base}>{one(before?.mean)}</td>}
                  <td className="num right" data-label={latest ?? "MeanCount"}>{one(now?.mean)}</td>
                  {base && <td className="num right" data-label="Change">{change === null ? "—" : `${change > 0 ? "+" : ""}${change.toFixed(1)}`}</td>}
                  <td className="num right" data-label="MaxN">{now?.maxn ?? "—"}</td>
                  <td className="num right" data-label="Species">{now ? now.species.length : "—"}</td>
                  <td data-label="Videos">
                    <div className="row">
                      {links.map((l) => <Link key={l.id} className="vname" to={`/videos/${l.id}/summary`}>{l.name}</Link>)}
                      {sample && all.length > 0 && <span className="meta">Sample</span>}
                      {!sample && all.length === 0 && <span className="meta">No footage yet</span>}
                      {waiting > 0 && <span className="pill warn">{waiting} in progress</span>}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </section>

      <div className="row" style={{ justifyContent: "space-between" }}>
        <div className="row">
          {hasReal && <button className="chip" aria-pressed={sample} onClick={() => setPicked(!sample)}>Show sample data</button>}
          {!hasReal && !sample && <button className="chip" onClick={() => setPicked(true)}>Show sample data</button>}
          {!hasReal && sample && <button className="chip" onClick={() => setPicked(false)}>Show your data</button>}
        </div>
        {!sample && (unfiled > 0 || undated > 0) && (
          <p className="meta">
            Not included: {[unfiled > 0 && `${unfiled} without a station`, undated > 0 && `${undated} without a filmed date are under No date`].filter(Boolean).join(", ")}. <Link to="/workspace">Fix in Surveys</Link>
          </p>
        )}
      </div>
    </div>
  );
}
