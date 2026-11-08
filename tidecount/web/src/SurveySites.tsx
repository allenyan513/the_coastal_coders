import { ReactNode, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Video } from "./api";
import { Modal } from "./Modal";
import { nameMismatch, season, setPlace, Site, Station, SurveyData, Transect, useSurveys, useSurveyStatus } from "./surveyStore";

/** A video and its re-runs with other models, keyed by the first import. */
export type Group = { root: string; runs: Video[] };
type Points = { done: number; total: number };

type StationInfo = { station: Station; transect: Transect; label: string; groups: Group[] } & Points;
type SiteInfo = Points & {
  site: Site;
  transects: { transect: Transect; stations: StationInfo[] }[];
  stations: StationInfo[];
  groups: Group[];
  filmed: number;
  last: string;
  noDate: Group[];
  misfiled: { group: Group; says: string; at: string }[];
  failed: Group[];
  empty: StationInfo[];
  fixes: number;
};

type Props = {
  groups: Group[];
  /** The run a row shows, of a video imported more than once. */
  shown: (g: Group) => Video;
  points: (g: Group) => Points;
  row: (g: Group) => ReactNode;
  onImport: (stationId?: string) => void;
  onPlace: (g: Group) => void;
  onRetry: (videoId: string) => void;
};

const SORTS = { attention: "Needs attention first", name: "Name", filmed: "Last filmed", counted: "Least counted" } as const;
type Sort = keyof typeof SORTS;
const FILTERS = { all: "All", attention: "Needs attention", unfilmed: "No footage yet", treatment: "Treatment", reference: "Reference" } as const;
type Filter = keyof typeof FILTERS;

const addUp = (all: Points[]) => all.reduce((a, b) => ({ done: a.done + b.done, total: a.total + b.total }), { done: 0, total: 0 });
const videos = (n: number) => `${n} ${n === 1 ? "video" : "videos"}`;

/** Everything the list and the detail say about one site, worked out once per change. */
function describe(data: SurveyData, site: Site, groups: Group[], shown: Props["shown"], points: Props["points"]): SiteInfo {
  const transects = data.transects.filter((t) => t.siteId === site.id).map((transect) => {
    const stations = data.stations.filter((s) => s.transectId === transect.id).map((station): StationInfo => {
      const here = groups.filter((g) => data.places[g.root] === station.id);
      return { station, transect, label: `${transect.name} · ${station.name}`, groups: here, ...addUp(here.map(points)) };
    });
    // Archived places drop out of view, unless footage is still filed there.
    return { transect, stations: stations.filter((s) => !(s.station.archived || transect.archived) || s.groups.length) };
  }).filter((t) => t.stations.length || !t.transect.archived);
  const stations = transects.flatMap((t) => t.stations);
  const here = stations.flatMap((s) => s.groups);
  const dates = here.map((g) => data.filmedOn[g.root]).filter(Boolean).sort();
  const noDate = here.filter((g) => !data.filmedOn[g.root]);
  const misfiled = stations.flatMap((s) => s.groups.flatMap((group) => {
    const says = nameMismatch(data, group.runs[0].name, s.station.id);
    return says ? [{ group, says, at: s.label }] : [];
  }));
  const failed = here.filter((g) => shown(g).status === "Failed");
  return {
    site, transects, stations, groups: here, ...addUp(stations),
    filmed: stations.filter((s) => s.groups.length).length,
    last: dates[dates.length - 1] ?? "",
    noDate, misfiled, failed,
    empty: stations.filter((s) => !s.groups.length && !s.station.archived),
    fixes: noDate.length + misfiled.length + failed.length,
  };
}

const ratio = (p: Points) => (p.total ? p.done / p.total : 1);

const sorters: Record<Sort, (a: SiteInfo, b: SiteInfo) => number> = {
  attention: (a, b) => b.fixes - a.fixes || a.site.name.localeCompare(b.site.name),
  name: (a, b) => a.site.name.localeCompare(b.site.name),
  filmed: (a, b) => (b.last || "0").localeCompare(a.last || "0") || a.site.name.localeCompare(b.site.name),
  counted: (a, b) => ratio(a) - ratio(b) || b.total - a.total,
};

const keeps: Record<Filter, (s: SiteInfo) => boolean> = {
  all: () => true,
  attention: (s) => s.fixes > 0,
  unfilmed: (s) => s.filmed === 0,
  treatment: (s) => s.site.flag === "treatment",
  reference: (s) => s.site.flag === "reference",
};

function FlagPill({ site }: { site: Site }) {
  if (!site.flag) return null;
  return <span className={`pill ${site.flag === "treatment" ? "accent" : "muted"}`}>{site.flag === "treatment" ? "Treatment" : "Reference"}</span>;
}

function Bar({ points }: { points: Points }) {
  const finished = points.total > 0 && points.done >= points.total;
  return <span className="bar wide"><i className={finished ? "up" : ""} style={{ width: `${points.total ? (points.done / points.total) * 100 : 0}%` }} /></span>;
}

/** One small square per station, filled once it has footage, with a gap between transects. */
function Dots({ info }: { info: SiteInfo }) {
  const finished = info.total > 0 && info.done >= info.total;
  return (
    <span className="sv-dots" aria-hidden>
      {info.transects.map((t) => (
        <span key={t.transect.id}>
          {t.stations.map((s) => <i key={s.station.id} className={s.groups.length ? (finished ? "up" : "on") : ""} />)}
        </span>
      ))}
    </span>
  );
}

/** Sets one filmed date on several videos at once, since a station's footage is usually filmed on one day. */
function DatesDialog({ title, groups, onClose }: { title: string; groups: Group[]; onClose: () => void }) {
  const data = useSurveys();
  const [date, setDate] = useState("");
  const [picked, setPicked] = useState(() => groups.map((g) => g.root));
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const save = async () => {
    setBusy(true);
    const problems = (await Promise.all(picked.map((root) => setPlace(root, data.places[root], date)))).filter(Boolean);
    setBusy(false);
    if (problems.length) setError(problems[0]);
    else onClose();
  };
  const flip = (root: string) => setPicked(picked.includes(root) ? picked.filter((r) => r !== root) : [...picked, root]);
  return (
    <Modal title={title} onClose={onClose} locked={busy}>
      <div className="stack">
        <label className="field">Filmed on
          <input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
          <span>Reports compare seasons by this date.</span>
        </label>
        <div className="sv-pick">
          {groups.map((g) => (
            <label key={g.root}>
              <input type="checkbox" checked={picked.includes(g.root)} onChange={() => flip(g.root)} />
              <span>{g.runs[0].name}</span>
              {data.filmedOn[g.root] && <span className="meta">{data.filmedOn[g.root]}</span>}
            </label>
          ))}
        </div>
        {error && <p className="meta" role="alert" style={{ color: "var(--down)" }}>{error}</p>}
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <button className="btn" onClick={onClose} disabled={busy}>Cancel</button>
          <button className="btn go" disabled={!date || !picked.length || busy} onClick={save}>
            {busy ? "Saving…" : `Set date for ${videos(picked.length)}`}
          </button>
        </div>
      </div>
    </Modal>
  );
}

/**
 * Surveys for many sites: every site as one short row on the left, and only the chosen site on the right,
 * as its stations and what needs fixing there. The chosen site and station live in the address,
 * so Back and shared links land on the same place.
 */
export function SurveySites({ groups, shown, points, row, onImport, onPlace, onRetry }: Props) {
  const data = useSurveys();
  const { loaded, error } = useSurveyStatus();
  const [params, setParams] = useSearchParams();
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const [sort, setSort] = useState<Sort>("attention");
  const [dating, setDating] = useState<{ title: string; groups: Group[] } | null>(null);

  const sites = useMemo(
    () => data.sites.filter((s) => !s.archived).map((s) => describe(data, s, groups, shown, points)),
    [data, groups, shown, points],
  );

  /** Where a search matched inside a site: the station of the first video or station it named. */
  const q = query.trim().toLowerCase();
  const hitIn = (info: SiteInfo) => {
    if (!q) return { site: true, station: "" };
    const video = info.stations.find((s) => s.groups.some((g) => g.runs.some((r) => r.name.toLowerCase().includes(q))));
    const station = info.stations.find((s) => s.label.toLowerCase().includes(q) || s.station.name.toLowerCase() === q);
    const site = info.site.name.toLowerCase().includes(q);
    return site || video || station ? { site: true, station: (video ?? station)?.station.id ?? "" } : null;
  };
  const listed = sites.filter((s) => keeps[filter](s) && hitIn(s)).sort(sorters[sort]);

  const asked = params.get("site");
  const current = sites.find((s) => s.site.id === asked) ?? listed[0] ?? sites[0] ?? null;
  const askedStation = current?.stations.find((s) => s.station.id === params.get("station"));
  const searched = current && q ? current.stations.find((s) => s.station.id === hitIn(current)?.station) : undefined;
  const station = askedStation ?? searched ?? current?.stations.find((s) => s.groups.length) ?? null;

  const go = (siteId: string | null, stationId = "") => setParams((p) => {
    const next = new URLSearchParams(p);
    if (siteId) next.set("site", siteId); else next.delete("site");
    if (stationId) next.set("station", stationId); else next.delete("station");
    return next;
  });

  if (!loaded) return <div className="panel panel-pad"><p className="meta" role={error ? "alert" : undefined}>{error || "Loading the surveys…"}</p></div>;
  if (!sites.length) return <div className="panel panel-pad"><p className="meta">No sites yet. Use Edit structure to add one.</p></div>;

  const counts = Object.fromEntries((Object.keys(FILTERS) as Filter[]).map((f) => [f, sites.filter(keeps[f]).length]));

  return (
    <div className={`sv ${asked ? "has-site" : ""}`}>
      <section className="panel sv-list" aria-label="Sites">
        <div className="sv-tools">
          <input
            className="flow-search sv-search"
            type="search"
            placeholder="Find a site, station or video"
            aria-label="Find a site, station or video"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <div className="row sv-chips">
            {(Object.keys(FILTERS) as Filter[]).filter((f) => f === "all" || counts[f] > 0).map((f) => (
              <button key={f} className="chip" aria-pressed={filter === f} onClick={() => setFilter(f)}>
                {FILTERS[f]} <span className="num">{counts[f]}</span>
              </button>
            ))}
          </div>
          <div className="sv-sort">
            <span className="meta">{listed.length === sites.length ? `${sites.length} sites` : `${listed.length} of ${sites.length} sites`}</span>
            <label className="meta">Sort{" "}
              <select value={sort} onChange={(e) => setSort(e.target.value as Sort)}>
                {(Object.keys(SORTS) as Sort[]).map((k) => <option key={k} value={k}>{SORTS[k]}</option>)}
              </select>
            </label>
          </div>
        </div>
        <ul className="sv-items">
          {listed.map((info) => {
            const filmedOf = `${info.filmed} of ${info.stations.length} stations filmed`;
            return (
              <li key={info.site.id}>
                <button
                  className="sv-item"
                  aria-current={info.site.id === current?.site.id ? "true" : undefined}
                  onClick={() => go(info.site.id, hitIn(info)?.station ?? "")}
                >
                  <span className="sv-item-top">
                    <b>{info.site.name}</b>
                    {info.fixes > 0 && <span className="pill warn">{info.fixes} to fix</span>}
                    <FlagPill site={info.site} />
                  </span>
                  <span className="sv-item-mid">
                    <Dots info={info} />
                    <span className="meta">{filmedOf}</span>
                    <span className="num meta">{info.total ? `${info.done}/${info.total}` : "—"}</span>
                  </span>
                  <Bar points={info} />
                </button>
              </li>
            );
          })}
          {listed.length === 0 && <li className="meta sv-none">No site matches.</li>}
        </ul>
      </section>

      {current && (
        <section className="sv-detail" aria-label={current.site.name}>
          <button className="btn quiet sv-back" onClick={() => go(null)}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden><path d="M15 6l-6 6 6 6" /></svg>
            All sites
          </button>
          <div className="panel sv-site">
            <div className="sv-site-head">
              <div className="stack" style={{ gap: 4, minWidth: 0 }}>
                <div className="row"><h2>{current.site.name}</h2><FlagPill site={current.site} /></div>
                <p className="meta">
                  {current.transects.length} {current.transects.length === 1 ? "transect" : "transects"}
                  {" · "}{current.filmed} of {current.stations.length} stations filmed
                  {" · "}{videos(current.groups.length)}
                  {current.total > 0 && <> · <span className="num">{current.done} of {current.total}</span> points counted</>}
                  {current.last && <> · last filmed {season(current.last)}</>}
                </p>
              </div>
              <div className="row">
                <Link className="btn" to="/analysis/stations">Station report</Link>
                <button className="btn" onClick={() => onImport(station?.station.id)}>Import here</button>
              </div>
            </div>

            {(current.fixes > 0 || current.empty.length > 0) && (
              <ul className="sv-fixes" aria-label="To fix at this site">
                {current.noDate.length > 0 && (
                  <li>
                    <span>{videos(current.noDate.length)} {current.noDate.length === 1 ? "has" : "have"} no filmed date, so season reports leave {current.noDate.length === 1 ? "it" : "them"} out.</span>
                    <button className="link" onClick={() => setDating({ title: `Filmed date at ${current.site.name}`, groups: current.noDate })}>Set dates</button>
                  </li>
                )}
                {current.misfiled.map((m) => (
                  <li key={m.group.root}>
                    <span><b>{m.group.runs[0].name}</b> is filed at {m.at}, but its name says {m.says}.</span>
                    <button className="link" onClick={() => onPlace(m.group)}>Check</button>
                  </li>
                ))}
                {current.failed.map((g) => (
                  <li key={g.root}>
                    <span>AI couldn't scan <b>{g.runs[0].name}</b>.</span>
                    <button className="link" onClick={() => onRetry(shown(g).id)}>Retry</button>
                  </li>
                ))}
                {current.empty.length > 0 && (
                  <li className="sv-fix-info">
                    <span>No footage yet at {current.empty.map((s) => s.label).join(", ")}.</span>
                  </li>
                )}
              </ul>
            )}

            {current.transects.length === 0 && <p className="meta">No transects yet. Use Edit structure to add them.</p>}
            <div className="sv-grid">
              {current.transects.map(({ transect, stations }) => (
                <div className="sv-tr" key={transect.id}>
                  <span className="num sv-tr-name">{transect.name}</span>
                  <div className="sv-tiles">
                    {stations.map((s) => {
                      const flagged = current.misfiled.some((m) => s.groups.includes(m.group)) || s.groups.some((g) => current.failed.includes(g));
                      return s.groups.length ? (
                        <button
                          key={s.station.id}
                          className="sv-tile"
                          aria-pressed={s.station.id === station?.station.id}
                          onClick={() => go(current.site.id, s.station.id)}
                        >
                          <span className="sv-tile-top"><b>{s.station.name}</b>{flagged && <i className="sv-flag" title="Something to fix here" />}</span>
                          <span className="meta">{videos(s.groups.length)}</span>
                          {s.total > 0 && <span className="num">{s.done}/{s.total} <small className="meta">points</small></span>}
                          <Bar points={s} />
                        </button>
                      ) : (
                        <div key={s.station.id} className="sv-tile empty">
                          <b>{s.station.name}</b>
                          <span className="meta">No footage</span>
                          {!s.station.archived && <button className="link" onClick={() => onImport(s.station.id)}>Import</button>}
                        </div>
                      );
                    })}
                    {stations.length === 0 && <p className="meta">No stations yet.</p>}
                  </div>
                </div>
              ))}
            </div>
          </div>

          {station ? (
            <div className="panel">
              <div className="sv-station-head">
                <h3>{station.label} <span className="meta">{videos(station.groups.length)}{station.total > 0 && <> · <span className="num">{station.done} of {station.total}</span> points counted</>}</span></h3>
                <div className="row">
                  {station.groups.length > 1 && <button className="btn" onClick={() => setDating({ title: `Filmed date at ${station.label}`, groups: station.groups })}>Set filmed date for all</button>}
                  <button className="btn" onClick={() => onImport(station.station.id)}>Import here</button>
                </div>
              </div>
              <div className="tree-videos sv-videos">{station.groups.map(row)}</div>
            </div>
          ) : current.stations.length > 0 && (
            <div className="panel panel-pad"><p className="meta">No footage at this site yet. Import a video into one of its stations.</p></div>
          )}
        </section>
      )}
      {dating && <DatesDialog title={dating.title} groups={dating.groups} onClose={() => setDating(null)} />}
    </div>
  );
}
