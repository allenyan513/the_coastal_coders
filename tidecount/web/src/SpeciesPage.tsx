import { useEffect, useState } from "react";
import { Link, useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { SpeciesMediaSummary, SpeciesRow } from "./api";
import { isSpeciesTab, SpeciesTab, SpeciesView } from "./SpeciesDrawer";
import { speciesMedia, speciesPagePath, speciesRows } from "./speciesData";

/**
 * One species as a full page in the main content area, beside Tideflow's sidebar: the same view as
 * the drawer, with room for a wider gallery and map. The address names the species and the tab
 * (/species/Scomber%20scombrus?tab=map), so it can be linked to, reloaded and reached with the
 * browser's Back and Forward.
 */
export function SpeciesPage() {
  const { name = "" } = useParams(); // React Router has decoded it already
  const species = name;
  const [params, setParams] = useSearchParams();
  const tab: SpeciesTab = isSpeciesTab(params.get("tab")) ? (params.get("tab") as SpeciesTab) : "photos";
  const navigate = useNavigate();
  const location = useLocation();
  // How many species pages ago the list was, when we came from it (Expand is 1, each look-alike
  // followed adds one), so Back returns to the list as it was: search, sort and scroll. A direct
  // link has no list behind it, so Back opens a fresh one.
  const depth = Number((location.state as { listDepth?: number } | null)?.listDepth) || 0;

  const [rows, setRows] = useState<SpeciesRow[] | null>(() => speciesRows.peek() ?? null);
  const [media, setMedia] = useState<SpeciesMediaSummary>(() => speciesMedia.peek() ?? {});
  const [error, setError] = useState("");
  useEffect(() => { speciesRows.get().then(setRows).catch((e) => setError(e.message)); }, []);
  useEffect(() => { speciesMedia.get().then(setMedia); }, []);
  // A new species starts at the top of the page.
  useEffect(() => { window.scrollTo({ top: 0 }); }, [species]);

  // A tab is a view of the same page, not a new history entry.
  const setTab = (t: SpeciesTab) => setParams(t === "photos" ? {} : { tab: t }, { replace: true, state: location.state });
  const back = () => (depth > 0 ? navigate(-depth) : navigate("/species"));

  const backButton = <button className="btn species-back" onClick={back}>← Back to Species list</button>;
  if (error) return <div className="stack">{backButton}<p className="meta">{error}</p></div>;
  if (!rows) return <div className="stack">{backButton}<p className="meta">Loading…</p></div>;
  const row = rows.find((r) => r.species === species);
  if (!row) {
    return (
      <div className="stack">
        {backButton}
        <div className="gallery-empty">
          <p><b>“{species}” is not on the species list</b></p>
          <p className="meta">The link may be out of date. <Link to="/species">Browse the Species wiki</Link>.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="species-page">
      <nav className="species-page-nav" aria-label="Species wiki">{backButton}</nav>
      <article className="species-page-card panel" aria-labelledby="drawer-title">
        <SpeciesView
          species={species} row={row} rows={rows} media={media}
          // A look-alike opens as its own page; Back returns to this one.
          onSelect={(other) => navigate(speciesPagePath(other, tab), { state: depth > 0 ? { listDepth: depth + 1 } : null })}
          tab={tab} onTab={setTab} layout="page"
        />
      </article>
    </div>
  );
}
