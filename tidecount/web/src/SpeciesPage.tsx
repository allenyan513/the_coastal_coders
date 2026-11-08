import { useEffect, useState } from "react";
import { Link, useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { SpeciesMediaSummary, SpeciesRow } from "./api";
import { SpeciesTab, SpeciesView } from "./SpeciesDrawer";
import { tabFromParam } from "./speciesProfile";
import { lastViewed, speciesMedia, speciesPagePath, speciesRows } from "./speciesData";

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
  const asked = params.get("tab");
  const tab: SpeciesTab = tabFromParam(asked);
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
  // A new species starts at the top of the page, and becomes the one the list marks as last viewed.
  useEffect(() => { window.scrollTo({ top: 0 }); lastViewed.species = species; }, [species]);

  // A tab is a view of the same page, not a new history entry.
  const setTab = (t: SpeciesTab) => setParams(t === "overview" ? {} : { tab: t }, { replace: true, state: location.state });
  // Old links (?tab=photos, ?tab=identify, or a name that never existed) are rewritten to the section they now mean.
  useEffect(() => {
    if (asked !== null && asked !== tab) setTab(tab);
  }, [asked, tab]);
  const back = () => (depth > 0 ? navigate(-depth) : navigate("/species"));

  // The reverse of Expand: the page's history entry becomes the list with this species open in its
  // drawer, on the same tab. The list restores its own search, sort and scroll.
  const collapse = () => {
    const q = new URLSearchParams({ species });
    if (tab !== "overview") q.set("tab", tab);
    navigate(`/species?${q}`, { replace: true, state: { fromList: true } });
  };

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
      <nav className="species-page-nav" aria-label="Species wiki">
        {backButton}
        <button className="btn hide-phone" style={{ marginLeft: "auto" }} onClick={collapse} title="Back to the list with this species in the side drawer" aria-label="Collapse: open this species in the side drawer">Collapse</button>
      </nav>
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
