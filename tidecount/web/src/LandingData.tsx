import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, SpeciesMediaSummary, SpeciesRow, WqiTable } from "./api";
import { SAMPLE_CELLS } from "./reportData";
import { badgeText } from "./speciesProfile";
import { RATINGS } from "./WqiTable";

const LICENCE = (l: string) => (/^public domain/i.test(l) ? "public domain" : l);
const list = (xs: string[]) => (xs.length < 2 ? xs.join("") : `${xs.slice(0, -1).join(", ")} and ${xs[xs.length - 1]}`);

/**
 * The species wiki at a glance: the most-seen fish that have reference photos, each opening its
 * own entry. Photos are CC BY or public domain, so every tile carries its credit in a tooltip and
 * the card names the photographers.
 */
export function SpeciesShowcase({ rows, media, count = 12 }: { rows: SpeciesRow[]; media: SpeciesMediaSummary; count?: number }) {
  const withPhoto = rows
    .filter((r) => media[r.species]?.compare?.thumb)
    .sort((a, b) => b.inat_obs - a.inat_obs)
    .slice(0, count);
  const photos = rows.filter((r) => media[r.species]?.image_count > 0).length;
  const notes = rows.filter((r) => media[r.species]?.has_profile).length;
  const status = rows.filter((r) => media[r.species]?.conservation).length;
  const shown = withPhoto.map((r) => media[r.species].compare!);
  const creators = [...new Set(shown.map((i) => i.creator).filter(Boolean))];
  const sources = [...new Set(shown.map((i) => i.source).filter(Boolean))];
  const licences = [...new Set(shown.map((i) => LICENCE(i.license)).filter(Boolean))].sort();

  return (
    <div className="ln-card">
      <div className="ln-figs">
        <div><b className="num">{rows.length || "…"}</b><span>fish recorded in Nova Scotia</span></div>
        <div><b className="num">{photos || "…"}</b><span>with reference photos</span></div>
        <div><b className="num">{notes || "…"}</b><span>with identification notes</span></div>
        <div><b className="num">{status || "…"}</b><span>with a verified at-risk or introduced status</span></div>
      </div>
      <ul className="ln-fish">
        {withPhoto.map((r) => {
          const m = media[r.species];
          const img = m.compare!;
          const c = m.conservation;
          return (
            <li key={r.species}>
              <Link to={`/species?species=${encodeURIComponent(r.species)}`} title={`Photo: ${img.creator || img.source}, ${LICENCE(img.license)}`}>
                <span className="ln-fish-img">
                  <img src={img.thumb} alt={`${r.common}, ${r.species}`} loading="lazy" />
                  {c && <span className={`pill status-badge ${c.kind}`}>{badgeText(c)}</span>}
                </span>
                <b>{r.common === r.species ? r.species : r.common}</b>
                <i className="meta">{r.species}</i>
              </Link>
            </li>
          );
        })}
        {!withPhoto.length && Array.from({ length: count }, (_, i) => <li key={i} className="ln-fish-empty" aria-hidden><span className="ln-fish-img" /></li>)}
      </ul>
      {creators.length > 0 && (
        <p className="ln-card-note">Photos by {list(creators)}, from {list(sources)} ({licences.join(", ")}). Hover a photo for its credit, or open the fish for the full one.</p>
      )}
      <Link className="ln-more" to="/species">Open the species wiki <span aria-hidden>→</span></Link>
    </div>
  );
}

type WqiSite = WqiTable["sites"][number];
const scored = (s: WqiSite) => s.scores.filter((c) => c.wqi !== null) as { year: number; wqi: number; rating: string }[];

/** The site whose score moved most between its first and last scored year, for the card's headline. */
function biggestChange(sites: WqiSite[]) {
  return sites
    .map((s) => { const v = scored(s); return { s, first: v[0], last: v[v.length - 1] }; })
    .filter((x) => x.first && x.last && x.first.year !== x.last.year)
    .sort((a, b) => Math.abs(b.last.wqi - b.first.wqi) - Math.abs(a.last.wqi - a.first.wqi))[0];
}

/**
 * Coastal Action's Water Quality Index report card, shrunk to fit the front page: the sites with
 * most years scored, headwaters at the top, and one colored cell per year. Real readings, worked
 * out by server/tidecount/wqi.py.
 */
export function WqiPreview() {
  const [data, setData] = useState<WqiTable | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => { api.wqiTable().then(setData).catch(() => setFailed(true)); }, []);

  const sites = (data?.sites ?? []).filter((s) => scored(s).length >= 4);
  const change = biggestChange(sites);
  const rating = (n: string) => RATINGS.find((r) => r.name === n);

  return (
    <div className="ln-card">
      <div className="ln-card-head">
        <div>
          <b>Water Quality Index</b>
          <p className="meta">Coastal Action's LaHave River readings, scored year by year, from the headwaters down to the estuary</p>
        </div>
        {failed ? <span className="pill warn">Unavailable</span> : <span className="pill up">Live</span>}
      </div>
      {change && (
        <p className="ln-headline">
          <b>{change.s.site_name}</b> went from <span className="num">{change.first.wqi.toFixed(1)}</span> ({change.first.rating}) in {change.first.year} to <span className="num">{change.last.wqi.toFixed(1)}</span> ({change.last.rating}) in {change.last.year}.
        </p>
      )}
      <div className="ln-wqi-wrap">
        {data ? (
          <table className="ln-wqi">
            <thead><tr><th>Site</th>{data.years.map((y) => <th key={y} className="num">{String(y).slice(2).padStart(3, "’")}</th>)}</tr></thead>
            <tbody>
              {sites.map((s) => (
                <tr key={s.site_id}>
                  <td>{s.site_name}{s.salty && <span className="meta"> · estuary</span>}</td>
                  {s.scores.map((c) => {
                    const r = rating(c.rating);
                    return (
                      <td key={c.year} className="num" title={`${s.site_name}, ${c.year}: ${c.wqi === null ? "not enough data" : `${c.wqi.toFixed(1)}, ${c.rating}`}`}
                        style={{ background: c.wqi === null ? "var(--panel-2)" : r?.color, color: c.wqi === null ? "var(--muted-2)" : r?.ink }}>
                        {c.wqi === null ? "–" : Math.round(c.wqi)}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        ) : <p className="meta" style={{ padding: "0 20px" }}>{failed ? "The report card couldn't load." : "Loading the report card…"}</p>}
      </div>
      <div className="ln-legend">
        {RATINGS.map((r) => <span key={r.name}><i style={{ background: r.color }} />{r.name}</span>)}
      </div>
      <p className="ln-card-note">The CCME index, worked out by Tideflow from the raw readings. Not Coastal Action's official scores, though within about 5 points of the ones they published for 2017 to 2023.</p>
      <Link className="ln-more" to="/analysis/trends">Open fish and water trends <span aria-hidden>→</span></Link>
    </div>
  );
}

const STATIONS = [
  { id: "t1-s1", label: "STAT1", transect: "T1" }, { id: "t1-s2", label: "STAT2", transect: "T1" }, { id: "t1-s3", label: "STAT3", transect: "T1" },
  { id: "t2-s1", label: "STAT1", transect: "T2" }, { id: "t2-s2", label: "STAT2", transect: "T2" }, { id: "t2-s3", label: "STAT3", transect: "T2" },
];
const SEASONS = ["Fall 2025", "Spring 2026"];

/**
 * The Station report's chart, for one site: MeanCount at each station, last season against this one.
 * It uses the report's own sample numbers and says so, because no site has two counted seasons yet.
 */
export function StationPreview() {
  const value = (id: string, season: string) => SAMPLE_CELLS.find((c) => c.stationId === id && c.season === season)?.mean ?? 0;
  const most = Math.max(...STATIONS.flatMap((s) => SEASONS.map((n) => value(s.id, n))));
  const up = STATIONS.filter((s) => value(s.id, SEASONS[1]) > value(s.id, SEASONS[0])).length;
  const mean = STATIONS.reduce((n, s) => n + value(s.id, SEASONS[1]), 0) / STATIONS.length;
  const maxn = Math.max(...SAMPLE_CELLS.filter((c) => STATIONS.some((s) => s.id === c.stationId) && c.season === SEASONS[1]).map((c) => c.maxn ?? 0));

  return (
    <div className="ln-card">
      <div className="ln-card-head">
        <div>
          <b>Station report</b>
          <p className="meta">Confirmed counts by transect and station, season against season, ready to export as CSV</p>
        </div>
        <span className="pill warn">Sample data</span>
      </div>
      <p className="ln-headline"><b className="num">{up} of {STATIONS.length}</b> stations counted higher in {SEASONS[1]} than in {SEASONS[0]}.</p>
      <div className="ln-figs two">
        <div><b className="num">{mean.toFixed(1)}</b><span>MeanCount, {SEASONS[1]}</span></div>
        <div><b className="num">{maxn}</b><span>MaxN, the most fish seen at once</span></div>
      </div>
      <div className="ln-bars" role="img" aria-label={STATIONS.map((s) => `${s.transect} ${s.label}: ${value(s.id, SEASONS[0])} then ${value(s.id, SEASONS[1])}`).join(", ")}>
        {["T1", "T2"].map((t) => (
          <div key={t} className="ln-bars-group">
            <div className="ln-bars-row">
              {STATIONS.filter((s) => s.transect === t).map((s) => (
                <div key={s.id} className="ln-bars-station">
                  <div className="ln-bars-pair">
                    {SEASONS.map((n, i) => (
                      <i key={n} className={i ? "latest" : ""} style={{ height: `${(value(s.id, n) / most) * 100}%` }} title={`${t} · ${s.label}, ${n}: ${value(s.id, n).toFixed(1)}`} />
                    ))}
                  </div>
                  <small>{s.label}</small>
                </div>
              ))}
            </div>
            <b>{t}</b>
          </div>
        ))}
      </div>
      <div className="ln-legend">
        <span><i style={{ background: "#8aa8f8" }} />{SEASONS[0]}</span>
        <span><i style={{ background: "var(--accent)" }} />{SEASONS[1]}</span>
      </div>
      <p className="ln-card-note">Made-up numbers in the report's real layout. Once a site has two counted seasons, this chart fills in from the counts volunteers confirm.</p>
      <Link className="ln-more" to="/analysis">Open the data analysis <span aria-hidden>→</span></Link>
    </div>
  );
}
