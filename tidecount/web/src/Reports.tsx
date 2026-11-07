import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "./api";
import { countProgress } from "./Library";
import { bySeason, buildCells, Cell, SAMPLE_CELLS, VideoResult } from "./reportData";
import { activeTree, NO_DATE, useSurveys } from "./surveyStore";

const one = (n: number | null | undefined) => (n === null || n === undefined ? "—" : n.toFixed(1));

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

function BarPair({ label, bars, most }: { label: string; bars: Bar[]; most: number }) {
  return (
    <div className="rstation">
      <div className="rbars">
        {bars.map((b) => (
          <div className={`rbar ${b.latest ? "latest" : ""}`} key={b.season} tabIndex={0} aria-label={`${b.label}, ${b.season}: ${one(b.value)}`}>
            {b.latest && b.value !== null && <span className="rvalue num">{one(b.value)}</span>}
            <i style={{ height: `${((b.value ?? 0) / most) * 100}%` }} />
            <span className="rtip" role="tooltip"><b className="num">{one(b.value)}</b> {b.season}</span>
          </div>
        ))}
      </div>
      <span className="rlabel">{label}</span>
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
  const tree = activeTree(data);
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
          <h1>Reports</h1>
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
              const change = now?.mean != null && before?.mean != null ? Number(now.mean.toFixed(1)) - Number(before.mean.toFixed(1)) : null;
              const all = inSite.filter((c) => c.stationId === s.station.id);
              const waiting = all.reduce((n, c) => n + c.videos - c.finished, 0);
              const links = all.flatMap((c) => c.links);
              return (
                <tr key={s.station.id}>
                  <td><b>{s.label}</b></td>
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
            Not included: {[unfiled > 0 && `${unfiled} without a station`, undated > 0 && `${undated} without a filmed date are under No date`].filter(Boolean).join(", ")}. <Link to="/">Fix in Surveys</Link>
          </p>
        )}
      </div>
    </div>
  );
}
