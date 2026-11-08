import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { SpeciesMediaSummary, SpeciesRow } from "./api";
import { SpeciesDrawer, SpeciesTab } from "./SpeciesDrawer";
import { lastViewed, speciesMedia, speciesPagePath, speciesRows } from "./speciesData";
import { badgeText, tabFromParam } from "./speciesProfile";

const GROUPS: Record<string, string> = { Actinopterygii: "Ray-finned fish", Elasmobranchii: "Sharks and rays", "": "Class not recorded" };
const SORTS = {
  inat_obs: "iNaturalist sightings",
  obis_nearshore_records: "OBIS nearshore records",
  seine_records: "Seine records",
  confirmed: "Named here",
} as const;
type SortKey = keyof typeof SORTS;

// The list as it was left, so coming back from a species page finds the same search, order and
// place. Kept for this session only.
const PHONE = "(max-width: 720px)"; // the same width the stylesheet treats as a phone
const memory = { query: "", sort: "inat_obs" as SortKey, scrollY: 0 };

/** The fish AI may suggest. Read-only: the list lives in the server's species.csv. */
export function Species() {
  // Shown at once from the last visit, then refreshed: "Named here" changes as people name tracks.
  const [rows, setRows] = useState<SpeciesRow[] | null>(() => speciesRows.peek() ?? null);
  const [error, setError] = useState("");
  const [query, setQuery] = useState(memory.query);
  const [sort, setSort] = useState<SortKey>(memory.sort);
  useEffect(() => { memory.query = query; memory.sort = sort; }, [query, sort]);

  const [media, setMedia] = useState<SpeciesMediaSummary>(() => speciesMedia.peek() ?? {});
  // The open species lives in the address (?species=Gadus morhua), so a link or the back button reopens it.
  const [params, setParams] = useSearchParams();
  const open = params.get("species");
  // The last fish opened stays marked after its drawer (or the full page) is closed, so you can find your place.
  const [lastSeen, setLastSeen] = useState(lastViewed.species);
  useEffect(() => { if (open) { lastViewed.species = open; setLastSeen(open); } }, [open]);
  const navigate = useNavigate();
  const location = useLocation();
  // On a phone a species opens as its own page (the drawer is for wider screens). listDepth 1 makes
  // the page's Back return to this list as it was left: search, order and scroll.
  const openSpecies = useCallback((name: string) => {
    if (window.matchMedia(PHONE).matches) navigate(speciesPagePath(name), { state: { listDepth: 1 } });
    else setParams({ species: name }, { state: { fromList: true } });
  }, [setParams, navigate]);
  const closeDrawer = useCallback(() => setParams({}, { replace: true }), [setParams]);
  // Expand swaps the drawer for the species' own page. The drawer's history entry is replaced, so
  // Back (the page's button or the browser's) returns to this list rather than to the drawer.
  const expand = useCallback((tab: SpeciesTab) => {
    if (!open) return;
    const fromList = Boolean((location.state as { fromList?: boolean } | null)?.fromList);
    navigate(speciesPagePath(open, tab), { replace: true, state: fromList ? { listDepth: 1 } : null });
  }, [open, location.state, navigate]);
  // A ?species= link opened on a phone, or a window narrowed to phone width with the drawer open, goes to the page.
  useEffect(() => {
    const phone = window.matchMedia(PHONE);
    const toPage = () => { if (phone.matches && open) expand("overview"); };
    toPage();
    phone.addEventListener("change", toPage);
    return () => phone.removeEventListener("change", toPage);
  }, [open, expand]);

  useEffect(() => { speciesRows.reload().then(setRows).catch((e) => setError(e.message)); }, []);
  useEffect(() => { speciesMedia.get().then(setMedia); }, []);

  // Back where the list was left. The scroll position is kept as it changes, because by the time
  // this page unmounts the next one may already have scrolled the window.
  const restored = useRef(false);
  useLayoutEffect(() => {
    if (!rows || restored.current) return;
    restored.current = true;
    if (memory.scrollY) window.scrollTo({ top: memory.scrollY });
  }, [rows]);
  useEffect(() => {
    const onScroll = () => { memory.scrollY = window.scrollY; };
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (rows ?? [])
      .filter((r) => !q || r.common.toLowerCase().includes(q) || r.species.toLowerCase().includes(q))
      .sort((a, b) => b[sort] - a[sort] || a.common.localeCompare(b.common));
  }, [rows, query, sort]);

  if (error) return <p className="meta">{error}</p>;
  if (!rows) return <p className="meta">Loading…</p>;
  const named = rows.filter((r) => r.confirmed > 0).length;

  return (
    <div className="stack" style={{ gap: 20 }}>
      <div>
        <h1>Species wiki</h1>
        <p className="lede">AI only suggests fish from this list, built from records of fish seen in Nova Scotia. A person always makes the final call.</p>
      </div>

      <div className="panel kpis">
        <div className="kpi"><span className="meta">Fish on the list</span><b>{rows.length}</b></div>
        <div className="kpi"><span className="meta">Sharks and rays</span><b>{rows.filter((r) => r.group === "Elasmobranchii").length}</b></div>
        <div className="kpi"><span className="meta">Class not recorded</span><b>{rows.filter((r) => r.group === "").length}</b></div>
        <div className="kpi"><span className="meta">Named by a person here</span><b>{named}</b></div>
      </div>

      <div className="panel">
        <div className="panel-head row">
          <label className="field" style={{ flex: "1 1 240px" }}>Search
            <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Common or scientific name" />
          </label>
          <label className="field">Most first
            <select value={sort} onChange={(e) => setSort(e.target.value as SortKey)}>
              {Object.entries(SORTS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
            </select>
          </label>
          <span className="num meta" style={{ alignSelf: "flex-end", paddingBottom: 10 }}>{shown.length} of {rows.length}</span>
        </div>
        <div style={{ overflowX: "auto" }}>
          <table className="sticky-first species-list">
            <thead>
              <tr>
                <th>Common name</th><th>Scientific name</th><th>Group</th>
                <th className="right" title="Sightings logged by the public on iNaturalist">iNaturalist sightings</th>
                <th className="right" title="Records near shore in OBIS, the Ocean Biodiversity Information System">OBIS nearshore</th>
                <th className="right" title="Records from beach seine net surveys">Seine surveys</th>
                <th className="right" title="Tracks a person gave this name on this PC">Named here</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((r) => (
                <tr key={r.species} className={`clickable ${open === r.species ? "open" : !open && lastSeen === r.species ? "last-viewed" : ""}`}
                  aria-current={!open && lastSeen === r.species ? "true" : undefined} onClick={() => openSpecies(r.species)}>
                  <td style={{ fontWeight: 500 }}>
                    <button className="rowlink" onClick={(e) => { e.stopPropagation(); openSpecies(r.species); }} aria-label={`Show details for ${r.common === r.species ? r.species : r.common}`}>
                      {r.common === r.species ? "—" : r.common}
                    </button>
                    {/* Phones show the list as rows, not a table: the scientific name goes under the common name. */}
                    <i className="sp-sci">{r.species}</i>
                    <span className="sp-badges">
                    {media[r.species]?.image_count > 0 && <span className="pill muted photos" title="Reference photos available">{media[r.species].image_count} photo{media[r.species].image_count === 1 ? "" : "s"}</span>}
                    {media[r.species]?.has_profile && <span className="pill muted photos" title="Identification notes available">ID notes</span>}
                    {/* Only verified statuses have a badge; no badge means unknown, not safe. */}
                    {media[r.species]?.conservation && (
                      <span
                        className={`pill photos status-badge ${media[r.species].conservation!.kind}`}
                        title={media[r.species].conservation!.scope === "populations"
                          ? "Verified status for some populations only, not the whole species"
                          : media[r.species].conservation!.kind === "at_risk" ? "Verified species-at-risk status" : "Verified as invasive in Nova Scotia"}
                      >
                        {badgeText(media[r.species].conservation!)}
                      </span>
                    )}
                    </span>
                  </td>
                  <td><i>{r.species}</i></td>
                  <td className="meta">{GROUPS[r.group] ?? r.group}</td>
                  <td className="num right">{r.inat_obs || "—"}</td>
                  <td className="num right">{r.obis_nearshore_records || "—"}</td>
                  <td className="num right">{r.seine_records || "—"}</td>
                  <td className="num right">{r.confirmed ? <span className="pill up">{r.confirmed}</span> : "—"}</td>
                </tr>
              ))}
              {!shown.length && <tr><td colSpan={7} className="meta">No fish match that search.</td></tr>}
            </tbody>
          </table>
        </div>
      </div>
      <p className="meta">The numbers show why a fish is on the list, not how common it is on your sites. To change the list, edit species.csv on the server. Select a fish to see reference photos, how to recognise it and where OBIS has records of it.</p>
      {open && rows.some((r) => r.species === open) && (
        <SpeciesDrawer species={open} row={rows.find((r) => r.species === open)} rows={rows} media={media} onSelect={openSpecies} onClose={closeDrawer} onExpand={expand} initialTab={tabFromParam(params.get("tab"))} />
      )}
    </div>
  );
}
