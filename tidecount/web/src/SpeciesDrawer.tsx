import { Component, lazy, ReactNode, Suspense, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { CompareImage, SpeciesImage, SpeciesMediaSummary, SpeciesProfile, SpeciesRow } from "./api";
import { speciesPagePath, speciesProfile } from "./speciesData";

// Leaflet is only downloaded when someone opens the map.
const OccurrenceMap = lazy(() => import("./OccurrenceMap"));

const VIEW_LABELS: Record<SpeciesImage["view"], string> = {
  side: "Side profile",
  underwater: "Underwater",
  in_hand: "In hand",
  illustration: "Illustration",
  other: "Photo",
};
const GROUPS: Record<string, string> = { Actinopterygii: "Ray-finned fish", Elasmobranchii: "Sharks and rays", "": "From fish surveys" };
const TABS = [
  { key: "photos", label: "Photos" },
  { key: "identify", label: "Identify" },
  { key: "map", label: "Map" },
  { key: "details", label: "Details" },
] as const;
type Tab = (typeof TABS)[number]["key"];

export type SpeciesTab = Tab;
export const isSpeciesTab = (t: string | null): t is Tab => TABS.some((x) => x.key === t);

type Shared = {
  /** Scientific name exactly as in species.csv. */
  species: string;
  /** The table row, when the caller has it. Without it the view shows reference material only. */
  row?: SpeciesRow;
  /** Every listed species, so links to related entries can show their common names. */
  rows?: SpeciesRow[];
  /** Thumbnails of other curated species, for side-by-side comparison. */
  media?: SpeciesMediaSummary;
  /** Opens another species. Links to related entries are only shown when this is given. */
  onSelect?: (species: string) => void;
};

type Props = Shared & {
  onClose: () => void;
  /** Opens the full page for this species on this tab. Without it, Expand goes there itself. */
  onExpand?: (tab: Tab) => void;
};

/**
 * Reference photos, identification notes, an OBIS map and credits for one species, in a drawer on
 * the right and a full-height sheet on a phone, for quick browsing. Expand opens the same view as
 * a full page (see SpeciesPage). It only needs a scientific name, so the video review screen can
 * open it for a BioCLIP suggestion the same way the Species page does.
 */
export function SpeciesDrawer({ species, row, rows, media, onSelect, onClose, onExpand }: Props) {
  const [tab, setTab] = useState<Tab>("photos");
  const closeRef = useRef<HTMLButtonElement>(null);
  const navigate = useNavigate();

  // Esc closes, focus moves in on open and back to the row that opened it, and the page behind stops scrolling.
  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    closeRef.current?.focus();
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = overflow;
      opener?.focus?.();
    };
  }, [onClose]);

  const expand = () => (onExpand ? onExpand(tab) : navigate(speciesPagePath(species, tab)));

  return (
    <div className="drawer-root">
      <div className="drawer-scrim" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-modal="true" aria-labelledby="drawer-title">
        <SpeciesView
          species={species} row={row} rows={rows} media={media} onSelect={onSelect}
          tab={tab} onTab={setTab} layout="drawer"
          actions={
            <div className="row drawer-actions">
              <button className="btn" onClick={expand} title="Open as a full page" aria-label="Expand: open this species as a full page">Expand</button>
              <button ref={closeRef} className="btn" onClick={onClose} aria-label="Close species details">Close</button>
            </div>
          }
        />
      </aside>
    </div>
  );
}

type ViewProps = Shared & {
  tab: Tab;
  onTab: (tab: Tab) => void;
  /** "drawer" for the panel on the right, "page" for the full page, which lays the tabs out wider. */
  layout: "drawer" | "page";
  /** Buttons at the right of the header. */
  actions?: ReactNode;
};

/**
 * The species itself: name, name check, the four tabs and their content. The drawer and the full
 * page both show this, so they can't drift apart. A profile that was loaded once is reused.
 */
export function SpeciesView({ species, row, rows, media, onSelect, tab, onTab, layout, actions }: ViewProps) {
  const [data, setData] = useState<SpeciesProfile | null>(() => speciesProfile(species).peek() ?? null);
  const [error, setError] = useState("");
  const bodyRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let live = true;
    const profile = speciesProfile(species);
    setData(profile.peek() ?? null); setError("");
    profile.get().then((d) => live && setData(d)).catch((e) => live && setError(e.message));
    bodyRef.current?.scrollTo({ top: 0 });
    return () => { live = false; };
  }, [species]);

  const common = row && row.common !== row.species ? row.common : data?.taxon?.inat_common_name || "";
  const title = common || species;
  const authority = data?.names?.authority || data?.taxon?.authority;
  const commonOf = (name: string) => {
    const r = rows?.find((x) => x.species === name);
    return r && r.common !== r.species ? r.common : "";
  };
  const listed = (name: string) => !rows || rows.some((x) => x.species === name);

  const onTabKey = (e: React.KeyboardEvent) => {
    const i = TABS.findIndex((t) => t.key === tab);
    const next = e.key === "ArrowRight" ? i + 1 : e.key === "ArrowLeft" ? i - 1 : null;
    if (next === null) return;
    e.preventDefault();
    const t = TABS[(next + TABS.length) % TABS.length].key;
    onTab(t);
    document.getElementById(`tab-${t}`)?.focus();
  };
  const Heading = layout === "page" ? "h1" : "h2";

  return (
    <>
        <header className="drawer-head">
          <div style={{ minWidth: 0 }}>
            <Heading id="drawer-title">{title}</Heading>
            {common && <p className="sci"><i>{species}</i>{authority ? <span className="meta"> {authority}</span> : null}</p>}
            {!common && authority && <p className="meta">{authority}</p>}
            {data && <NameCheck data={data} />}
          </div>
          {actions}
        </header>

        <div className="tabs" role="tablist" aria-label="Species details" onKeyDown={onTabKey}>
          {TABS.map((t) => (
            <button
              key={t.key} id={`tab-${t.key}`} role="tab" className="tab"
              aria-selected={tab === t.key} aria-controls={`panel-${t.key}`} tabIndex={tab === t.key ? 0 : -1}
              onClick={() => onTab(t.key)}
            >
              {t.label}
              {t.key === "photos" && data && data.images.length > 0 && <span className="tab-count">{data.images.length}</span>}
            </button>
          ))}
        </div>

        <div className={`drawer-body${layout === "page" ? " species-page-body" : ""}`} ref={bodyRef} role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`}>
          <TabBoundary key={`${species}:${tab}`}>
          {error && <p className="meta">{error}</p>}
          {!data && !error && <p className="meta">Loading…</p>}

          {data && tab === "photos" && <Photos key={species} data={data} title={title} />}

          {data && tab === "identify" && (
            <Identify data={data} media={media} commonOf={commonOf} listed={listed} onSelect={onSelect} />
          )}

          {tab === "map" && (
            <Suspense fallback={<p className="meta">Loading the map…</p>}>
              <OccurrenceMap species={species} names={data?.names ?? null} />
            </Suspense>
          )}

          {data && tab === "details" && <Details data={data} row={row} />}
          </TabBoundary>
        </div>
    </>
  );
}

/** Keeps a failure inside one tab, so a bad entry can't blank the whole app. */
class TabBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  componentDidCatch(error: unknown) { console.error("Species drawer tab failed", error); }
  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <div className="gallery-empty" role="alert">
        <p><b>This part of the entry couldn't be shown</b></p>
        <p className="meta">The other tabs still work. Reloading the page or restarting TideCount usually fixes it.</p>
      </div>
    );
  }
}

/** A one-line note when the list's name isn't the one WoRMS accepts, so nobody files records under a synonym unknowingly. */
function NameCheck({ data }: { data: SpeciesProfile }) {
  const n = data.names;
  if (!n) return null;
  if (n.status === "accepted") return null;
  if (n.status === "unmatched") return <p className="name-check warn">Name not found in WoRMS or GBIF. Treat it with care.</p>;
  return (
    <p className="name-check warn">
      {n.source} treats this name as {n.status}
      {n.accepted_name && n.accepted_name !== data.species ? <>; the accepted name is <i>{n.accepted_name}</i></> : null}.
      The AI list keeps the name it was built with.
    </p>
  );
}

function Photos({ data, title }: { data: SpeciesProfile; title: string }) {
  const [broken, setBroken] = useState<Set<string>>(new Set());
  const [view, setView] = useState<SpeciesImage["view"] | "all">("all");
  const [shot, setShot] = useState(0);
  const usable = data.images.filter((i) => !broken.has(i.id));
  const views = [...new Set(usable.map((i) => i.view))];
  const images = view === "all" ? usable : usable.filter((i) => i.view === view);
  const current = images[Math.min(shot, images.length - 1)];
  const lose = (id: string) => setBroken((b) => new Set(b).add(id));

  if (!usable.length) {
    return (
      <div className="gallery-empty">
        <p><b>{data.images.length ? "These photos couldn't be loaded" : "No reference photos yet"}</b></p>
        <p className="meta">
          {data.images.length
            ? "The source may be offline. The credits are still under Details."
            : "Photos are added only after the species match and the licence have been checked by a person."}
        </p>
        <a className="meta" href={`https://www.inaturalist.org/taxa/search?q=${encodeURIComponent(data.species)}`} target="_blank" rel="noreferrer noopener">Look it up on iNaturalist</a>
      </div>
    );
  }

  return (
    <section aria-label="Reference images" className="stack gallery" style={{ gap: 10 }}>
      {views.length > 1 && (
        <div className="row" role="group" aria-label="Show photos of">
          <button className="chip" aria-pressed={view === "all"} onClick={() => { setView("all"); setShot(0); }}>All {usable.length}</button>
          {views.map((v) => (
            <button key={v} className="chip" aria-pressed={view === v} onClick={() => { setView(v); setShot(0); }}>
              {VIEW_LABELS[v]} {usable.filter((i) => i.view === v).length}
            </button>
          ))}
        </div>
      )}
      {current && (
        <figure className="gallery-main">
          <div className="gallery-frame">
            <img
              key={current.id}
              src={current.url}
              alt={`${title}, ${VIEW_LABELS[current.view].toLowerCase()}${current.caption ? `: ${current.caption}` : ""}`}
              onError={() => lose(current.id)}
            />
            <span className="pill muted gallery-view">{VIEW_LABELS[current.view]}</span>
            {images.length > 1 && (
              <>
                <button className="gallery-nav prev" aria-label="Previous photo" onClick={() => setShot((s) => (s - 1 + images.length) % images.length)}>‹</button>
                <button className="gallery-nav next" aria-label="Next photo" onClick={() => setShot((s) => (s + 1) % images.length)}>›</button>
              </>
            )}
          </div>
          <Credit img={current} />
        </figure>
      )}
      {images.length > 1 && (
        <div className="thumbs" role="group" aria-label="Choose a reference image">
          {images.map((img, i) => (
            <button key={img.id} className="thumb" aria-pressed={i === shot} aria-label={`${VIEW_LABELS[img.view]}, image ${i + 1} of ${images.length}`} onClick={() => setShot(i)}>
              <img
                src={img.thumb_url ?? img.url} alt="" loading="lazy"
                // A missing thumbnail falls back to the full image; only drop the photo if both fail.
                onError={(e) => { const el = e.currentTarget; if (el.src !== img.url) el.src = img.url; else lose(img.id); }}
              />
            </button>
          ))}
        </div>
      )}
    </section>
  );
}

function Credit({ img }: { img: SpeciesImage }) {
  return (
    <figcaption className="credit">
      {img.caption && <span>{img.caption}. </span>}
      <span>{img.view === "illustration" ? "Illustration" : "Photo"} by {img.creator}. </span>
      <a href={img.license_url} target="_blank" rel="noreferrer noopener">{img.license}</a>
      {" · "}
      <a href={img.source_url} target="_blank" rel="noreferrer noopener">Original on {img.source}</a>
      {img.place ? <span> · {img.place}</span> : null}
      <span className="verify"> {img.verification}</span>
    </figcaption>
  );
}

type IdentifyProps = {
  data: SpeciesProfile;
  media?: SpeciesMediaSummary;
  commonOf: (name: string) => string;
  listed: (name: string) => boolean;
  onSelect?: (species: string) => void;
};

function Identify({ data, media, commonOf, listed, onSelect }: IdentifyProps) {
  const p = data.profile;
  // Entries that compare themselves with this one, which this one doesn't already list.
  const backlinks = data.mentioned_by.filter((m) => !p?.similar.some((s) => s.species === m.species));

  return (
    <div className="stack identify-tab" style={{ gap: 20 }}>
      {p ? (
        <section>
          <h3>How to recognise it</h3>
          <p>{p.summary}</p>
          <ul className="features">{p.features.map((f) => <li key={f}>{f}</li>)}</ul>
        </section>
      ) : (
        <section className="gallery-empty" style={{ minHeight: 120 }}>
          <p><b>No identification notes yet</b></p>
          <p className="meta">Notes are written from published descriptions and listed with their sources.</p>
        </section>
      )}

      {p && p.similar.length > 0 && (
        <section>
          <h3>Easily confused with</h3>
          <div className="compare">
            {p.similar.map((s) => (
              <CompareCard
                key={s.species} name={s.species} common={commonOf(s.species)} note={s.note}
                photo={media?.[s.species]?.compare ?? null}
                onOpen={onSelect && listed(s.species) ? () => onSelect(s.species) : undefined}
              />
            ))}
          </div>
        </section>
      )}

      {backlinks.length > 0 && (
        <section>
          <h3>Compared with this fish in other entries</h3>
          <ul className="features">
            {backlinks.map((m) => (
              <li key={m.species}>
                <SpeciesLink name={m.species} common={commonOf(m.species)} onOpen={onSelect && listed(m.species) ? () => onSelect(m.species) : undefined} />
                <span className="meta"> {m.note}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {p && !p.expert_reviewed && (
        <p className="note warn">These notes are a first draft from the sources below and have not been reviewed by a fish biologist. Check them against the sources before relying on them.</p>
      )}
      {p && p.sources.length > 0 && (
        <section>
          <h3>Sources for these notes</h3>
          <ul className="features">
            {p.sources.map((s) => <li key={s.url}><a href={s.url} target="_blank" rel="noreferrer noopener">{s.label}</a></li>)}
          </ul>
        </section>
      )}
    </div>
  );
}

function SpeciesLink({ name, common, onOpen }: { name: string; common: string; onOpen?: () => void }) {
  const label = <>{common ? `${common} ` : ""}(<i>{name}</i>)</>;
  return onOpen ? <button className="linklike" onClick={onOpen}>{label}</button> : <span>{label}</span>;
}

type CompareProps = { name: string; common: string; note: string; photo: CompareImage | null; onOpen?: () => void };

const COMPARE_VIEW: Record<string, string> = { side: "Side profile", underwater: "Underwater", in_hand: "In hand", illustration: "Illustration", other: "Photo" };

/** A look-alike: its own reference photo, its name and the difference that tells it apart. */
function CompareCard({ name, common, note, photo, onOpen }: CompareProps) {
  const [broken, setBroken] = useState(false);
  const label = common || name;
  const shown = photo && !broken;
  return (
    <div className="compare-card">
      <figure className="compare-photo">
        {shown ? (
          <img src={photo.thumb} alt={`${label}, ${COMPARE_VIEW[photo.view ?? "other"]?.toLowerCase() ?? "photo"}`} loading="lazy" onError={() => setBroken(true)} />
        ) : (
          <div className="compare-placeholder" role="img" aria-label={`No verified photo of ${label} yet`}>
            <span>No verified photo yet</span>
          </div>
        )}
      </figure>
      <div className="compare-text">
        <SpeciesLink name={name} common={common} onOpen={onOpen} />
        <p className="meta" style={{ marginTop: 2 }}>{note}</p>
        {shown && (
          <p className="compare-credit">
            {COMPARE_VIEW[photo.view ?? "other"] ?? "Photo"} · {photo.creator} ·{" "}
            <a href={photo.license_url} target="_blank" rel="noreferrer noopener">{photo.license}</a> ·{" "}
            <a href={photo.source_url} target="_blank" rel="noreferrer noopener">{photo.source}</a>
          </p>
        )}
      </div>
    </div>
  );
}

function Details({ data, row }: { data: SpeciesProfile; row?: SpeciesRow }) {
  const n = data.names;
  return (
    <div className="stack details-tab" style={{ gap: 20 }}>
      {row && (
        <section>
          <h3>In TideCount</h3>
          <dl className="facts">
            <div><dt>Group</dt><dd>{GROUPS[row.group] ?? row.group}</dd></div>
            <div><dt>Family</dt><dd>{n?.family || data.taxon?.family || "—"}</dd></div>
            <div><dt>iNaturalist sightings</dt><dd className="num">{row.inat_obs || "—"}</dd></div>
            <div><dt>OBIS nearshore</dt><dd className="num">{row.obis_nearshore_records || "—"}</dd></div>
            <div><dt>Seine surveys</dt><dd className="num">{row.seine_records || "—"}</dd></div>
            <div><dt>Named here</dt><dd className="num">{row.confirmed || "—"}</dd></div>
          </dl>
          <p className="meta" style={{ marginTop: 6 }}>These counts are why the fish is on the AI list. They come from species.csv and don't change with the map.</p>
        </section>
      )}

      <section>
        <h3>Name check</h3>
        {n ? (
          <dl className="facts">
            <div><dt>Checked against</dt><dd>{n.source ?? "Not found"}</dd></div>
            <div><dt>Status</dt><dd>{n.status}</dd></div>
            {n.aphia_id && <div><dt>WoRMS AphiaID</dt><dd className="num">{n.url ? <a href={n.url} target="_blank" rel="noreferrer noopener">{n.aphia_id}</a> : n.aphia_id}</dd></div>}
            {n.accepted_name && n.accepted_name !== data.species && <div><dt>Accepted name</dt><dd><i>{n.accepted_name}</i></dd></div>}
            <div><dt>Habitat in WoRMS</dt><dd>{n.source === "WoRMS" ? [n.is_marine && "marine", n.is_brackish && "brackish", n.is_freshwater && "freshwater"].filter(Boolean).join(", ") || "—" : "—"}</dd></div>
          </dl>
        ) : <p className="meta">This name hasn't been checked yet.</p>}
        {n && n.synonyms.length > 0 && (
          <details className="synonyms">
            <summary>{n.synonyms.length} other name{n.synonyms.length === 1 ? "" : "s"} in older records</summary>
            <p className="meta">{n.synonyms.map((s, i) => <span key={s}>{i ? ", " : ""}<i>{s}</i></span>)}</p>
          </details>
        )}
      </section>

      <section>
        <h3>Photo credits</h3>
        {data.images.length ? (
          <ul className="features">
            {data.images.map((img) => (
              <li key={img.id}>
                {img.creator} · <a href={img.license_url} target="_blank" rel="noreferrer noopener">{img.license}</a> · <a href={img.source_url} target="_blank" rel="noreferrer noopener">{img.source}</a>
              </li>
            ))}
          </ul>
        ) : <p className="meta">No photos yet.</p>}
      </section>

      <section>
        <h3>Look it up elsewhere</h3>
        <ul className="features">
          {data.taxon && <li><a href={`https://www.inaturalist.org/taxa/${data.taxon.inat_taxon_id}`} target="_blank" rel="noreferrer noopener">iNaturalist</a></li>}
          {n?.aphia_id && <li><a href={`https://obis.org/taxon/${n.accepted_aphia_id || n.aphia_id}`} target="_blank" rel="noreferrer noopener">OBIS</a></li>}
          <li><a href={`https://www.fishbase.se/summary/${data.species.replace(" ", "-")}.html`} target="_blank" rel="noreferrer noopener">FishBase</a></li>
          <li><a href={data.taxon ? `https://www.gbif.org/species/${data.taxon.gbif_key}` : `https://www.gbif.org/species/search?q=${encodeURIComponent(data.species)}`} target="_blank" rel="noreferrer noopener">GBIF</a></li>
        </ul>
        <p className="meta">Photos and map tiles load from their original hosts, so opening this drawer contacts iNaturalist, Wikimedia and OpenStreetMap. OBIS records come through this app and are cached for a week.</p>
      </section>
    </div>
  );
}
