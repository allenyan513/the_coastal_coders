import { Component, lazy, ReactNode, Suspense, useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { CompareImage, SpeciesImage, SpeciesMediaSummary, SpeciesProfile, SpeciesRow } from "./api";
import { speciesPagePath, speciesProfile } from "./speciesData";
import {
  badgeText, environmentLabels, shortAuthority, splitFirstSentence, statusSummary,
  STATUS_TYPE_LABEL, STATUS_TYPE_ORDER, type SpeciesTabKey,
} from "./speciesProfile";
import type { SpeciesConservation } from "./api";
import { editDrafts, PhotoEditor, VIEW_LABELS } from "./PhotoLibrary";

// Leaflet is only downloaded when someone opens the map.
const OccurrenceMap = lazy(() => import("./OccurrenceMap"));

const GROUPS: Record<string, string> = { Actinopterygii: "Ray-finned fish", Elasmobranchii: "Sharks and rays", "": "Class not recorded" };
// Photos and Identify are now both in Overview; old ?tab=photos and ?tab=identify links go there (tabFromParam).
const TABS: { key: SpeciesTabKey; label: string }[] = [
  { key: "overview", label: "Overview" },
  { key: "map", label: "Map" },
  { key: "details", label: "Details & Sources" },
];
type Tab = SpeciesTabKey;

export type SpeciesTab = Tab;

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
  /** The tab to open on, e.g. when the full page is collapsed back into the drawer. */
  initialTab?: Tab;
};

/**
 * Reference photos, identification notes, an OBIS map and credits for one species, in a drawer on
 * the right and a full-height sheet on a phone, for quick browsing. Expand opens the same view as
 * a full page (see SpeciesPage). It only needs a scientific name, so the video review screen can
 * open it for a BioCLIP suggestion the same way the Species page does.
 */
export function SpeciesDrawer({ species, row, rows, media, onSelect, onClose, onExpand, initialTab }: Props) {
  const [tab, setTab] = useState<Tab>(initialTab ?? "overview");
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

  const expand = () => (onExpand ? onExpand(tab) : navigate(speciesPagePath(species, tab), { state: editDrafts.has(species) ? { editing: true } : null }));

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
  // Read-only until Edit. Editing changes this species' photos only, and nothing is stored until Save.
  // Expand or Collapse mid-edit arrives with `editing` in the navigation state and keeps the draft.
  const location = useLocation();
  const [editing, setEditing] = useState(() => editDrafts.resume(species, location.state));
  const bodyRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setEditing(editDrafts.resume(species, location.state));
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
            <div className="row title-row">
              <Heading id="drawer-title">{title}</Heading>
              {data?.conservation && <StatusBadge c={data.conservation} />}
            </div>
            {common && <p className="sci"><i>{species}</i>{authority ? <span className="meta"> {authority}</span> : null}</p>}
            {!common && authority && <p className="meta">{authority}</p>}
            {data && <NameCheck data={data} />}
          </div>
          <div className="row drawer-actions">
            {data && !editing && <button className="btn" onClick={() => { editDrafts.start(species, data.images); setEditing(true); }} aria-label="Edit this species' photos">Edit</button>}
            {actions}
          </div>
        </header>

        <div className="tabs" role="tablist" aria-label="Species details" onKeyDown={onTabKey}>
          {TABS.map((t) => (
            <button
              key={t.key} id={`tab-${t.key}`} role="tab" className="tab"
              aria-selected={tab === t.key} aria-controls={`panel-${t.key}`} tabIndex={tab === t.key ? 0 : -1}
              onClick={() => onTab(t.key)}
            >
              {t.label}
            </button>
          ))}
        </div>

        <div className={`drawer-body${layout === "page" ? " species-page-body" : ""}`} ref={bodyRef} role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`}>
          {data && editing ? (
            <PhotoEditor key={species} data={data} onCancel={() => setEditing(false)} onSaved={(p) => { setData(p); setEditing(false); }} />
          ) : (
          <TabBoundary key={`${species}:${tab}`}>
          {error && <p className="meta">{error}</p>}
          {!data && !error && <p className="meta">Loading…</p>}

          {data && tab === "overview" && (
            <Overview data={data} row={row} title={title} media={media} commonOf={commonOf} listed={listed} onSelect={onSelect} onSources={() => onTab("details")} wide={layout === "page"} />
          )}

          {tab === "map" && (
            <Suspense fallback={<p className="meta">Loading the map…</p>}>
              <OccurrenceMap species={species} names={data?.names ?? null} />
            </Suspense>
          )}

          {data && tab === "details" && <Details data={data} row={row} />}
          </TabBoundary>
          )}
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
            ? "The source may be offline. The credits are still under Details & Sources."
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

/** A credit link, or plain text when there's no page to link to (an uploaded photo used with permission). */
function MaybeLink({ href, children }: { href?: string; children: ReactNode }) {
  return href ? <a href={href} target="_blank" rel="noreferrer noopener">{children}</a> : <span>{children}</span>;
}

function Credit({ img }: { img: SpeciesImage }) {
  return (
    <figcaption className="credit">
      {img.caption && <span>{img.caption}. </span>}
      <span>{img.view === "illustration" ? "Illustration" : "Photo"} by {img.creator}. </span>
      <MaybeLink href={img.license_url}>{img.license}</MaybeLink>
      {" · "}
      <MaybeLink href={img.source_url}>{img.source_url ? `Original on ${img.source}` : img.source}</MaybeLink>
      {img.place ? <span> · {img.place}</span> : null}
      <span className="verify"> {img.verification}</span>
    </figcaption>
  );
}

type OverviewProps = {
  data: SpeciesProfile;
  row?: SpeciesRow;
  title: string;
  media?: SpeciesMediaSummary;
  commonOf: (name: string) => string;
  listed: (name: string) => boolean;
  onSelect?: (species: string) => void;
  /** Opens Details & Sources, where every source is listed. */
  onSources: () => void;
  /** On the full page: folded sections start open. */
  wide: boolean;
};

const KIND_LABEL: Record<SpeciesConservation["kind"], string> = { at_risk: "Species at risk", invasive_ns: "Invasive in Nova Scotia" };

/** Only for a verified status: a fish without one shows no badge, which means unknown, not safe. */
function StatusBadge({ c }: { c: SpeciesConservation }) {
  return (
    <span
      className={`pill status-badge ${c.kind}`}
      title={`${KIND_LABEL[c.kind]}${c.scope === "populations" ? ": applies to some populations only, not the whole species" : ""}, verified ${c.verified_on}. Details on the Overview; sources in Details & Sources.`}
    >
      {badgeText(c)}
    </span>
  );
}

/**
 * A section that folds in the drawer, to keep it short, and is open on the full page, which has the
 * room. Everything stays in both: nothing is only on the page.
 */
function Fold({ title, wide, children, className = "" }: { title: ReactNode; wide: boolean; children: ReactNode; className?: string }) {
  return (
    <details className={`fold ${className}`} open={wide || undefined}>
      <summary>{title}</summary>
      <div className="fold-body">{children}</div>
    </details>
  );
}

/**
 * The encyclopedia entry: photos, a short description, at-a-glance facts, how to recognise it,
 * a compact conservation summary and the similar species. Longer material (assessment history,
 * threats, range, the detail of each comparison) folds in the drawer and is open on the full page.
 * Everything shown is from the curated files; nothing is fetched or guessed here.
 */
function Overview({ data, row, title, media, commonOf, listed, onSelect, onSources, wide }: OverviewProps) {
  const p = data.profile;
  const c = data.conservation;
  // Entries that compare themselves with this one, which this one doesn't already list.
  const backlinks = data.mentioned_by.filter((m) => !p?.similar.some((s) => s.species === m.species));
  const family = data.names?.family || data.taxon?.family || "";
  const env = environmentLabels(data.names);

  // No reference photo: a one-line placeholder instead of an empty gallery column, so the text gets the width.
  const noPhotos = data.images.length === 0;
  const range = c && (c.historical_range || c.current_range) ? c : null;

  return (
    <div className={`overview${noPhotos ? " no-media" : ""}`}>
      {noPhotos ? (
        <p className="gallery-empty compact overview-noimage">
          <span><b>No reference photos yet.</b> Photos are added only after the species match and the licence have been checked by a person.</span>
          <a href={`https://www.inaturalist.org/taxa/search?q=${encodeURIComponent(data.species)}`} target="_blank" rel="noreferrer noopener">Look it up on iNaturalist</a>
        </p>
      ) : (
        <div className="overview-media">
          <Photos key={data.species} data={data} title={title} />
        </div>
      )}

      <div className="overview-text stack" style={{ gap: 16 }}>
        <section>
          <h3>About</h3>
          {p?.summary ? <p className="overview-lede">{p.summary}</p> : <p className="meta">No description has been written for this fish yet.</p>}
        </section>

        <section>
          <h3>At a glance</h3>
          <dl className="facts glance">
            {row && <div><dt>Group</dt><dd>{GROUPS[row.group] ?? row.group}</dd></div>}
            <div><dt>Family</dt><dd>{family || "—"}</dd></div>
            <div>
              <dt>Environment</dt>
              {c?.environment_now ? (
                // A population whose habitat now differs from the species' range: say both, not a generic list.
                <dd>
                  {c.environment_now}
                  <span className="glance-sub">{[c.environment_now_note, c.environment_historical && `historically ${c.environment_historical.charAt(0).toLowerCase()}${c.environment_historical.slice(1)}`].filter(Boolean).join("; ")}</span>
                </dd>
              ) : (
                <dd>{env.length ? env.join(" · ") : <span className="meta">Not recorded</span>}{env.length > 0 && <span className="glance-sub">Where the species can occur (WoRMS)</span>}</dd>
              )}
            </div>
            <div>
              <dt>Status</dt>
              <dd>
                {c ? badgeText(c) : <span className="meta">No verified status</span>}
                {c && c.statuses.length > 0 && <span className="glance-sub">{statusSummary(c)}</span>}
              </dd>
            </div>
          </dl>
        </section>

        {p && p.features.length > 0 && (
          <section>
            <h3>How to recognise it</h3>
            <ul className="features">{p.features.map((f) => <li key={f}>{f}</li>)}</ul>
            {/* Only while unreviewed: the wording says so. */}
            {!p.expert_reviewed && (
              <p className="id-footnote">
                <svg className="id-footnote-icon" viewBox="0 0 16 16" width="13" height="13" aria-hidden="true" focusable="false">
                  <circle cx="8" cy="8" r="7" fill="none" stroke="currentColor" strokeWidth="1.4" />
                  <path d="M8 7v4.2" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                  <circle cx="8" cy="4.7" r=".9" fill="currentColor" />
                </svg>
                <span>
                  Identification notes are based on published descriptions and have not been reviewed by a fish biologist.{" "}
                  <button type="button" className="linklike id-footnote-link" onClick={onSources}>View sources</button>
                </span>
              </p>
            )}
          </section>
        )}
        {!p && (
          <section className="gallery-empty" style={{ minHeight: 100 }}>
            <p><b>No identification notes yet</b></p>
            <p className="meta">Notes are written from published descriptions and listed with their sources.</p>
          </section>
        )}

        <Conservation c={c} onSources={onSources} wide={wide} />

        {range && (
          <section>
            <h3>Range</h3>
            <Fold wide={wide} title="Historical and current range">
              <dl className="facts range-facts">
                {range.historical_range && <div><dt>Historically</dt><dd>{range.historical_range}</dd></div>}
                {range.current_range && <div><dt>Current known wild range</dt><dd>{range.current_range}</dd></div>}
              </dl>
              {range.range_note && <p className="meta" style={{ marginTop: 6 }}>{range.range_note}</p>}
            </Fold>
          </section>
        )}
      </div>

      {((p && p.similar.length > 0) || backlinks.length > 0) && (
        <div className="overview-wide stack" style={{ gap: 16 }}>
          {p && p.similar.length > 0 && (
            <section>
              <h3>Similar species</h3>
              <div className="compare">
                {p.similar.map((s) => (
                  <CompareCard
                    key={s.species} name={s.species} common={commonOf(s.species) || s.common || ""} note={s.note}
                    photo={media?.[s.species]?.compare ?? null}
                    onOpen={onSelect && listed(s.species) ? () => onSelect(s.species) : undefined}
                    unlisted={!listed(s.species)} wide={wide}
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
        </div>
      )}
    </div>
  );
}

/**
 * A verified status as one line and one chip per assessment, then what it applies to; the history,
 * why it matters and the threats fold in the drawer. A fish without a verified status says so plainly.
 */
function Conservation({ c, onSources, wide }: { c: SpeciesConservation | null; onSources: () => void; wide: boolean }) {
  if (!c) {
    return (
      <section>
        <h3>Conservation status</h3>
        <p className="meta">
          Tideflow has no verified conservation or invasive status for this fish. That means it hasn't been checked here,
          not that the fish is secure. See COSEWIC and the Nova Scotia species-at-risk list for official assessments.
        </p>
      </section>
    );
  }
  // Grouped by kind of statement (scientific assessment, legal listing, invasive classification),
  // each chip with its own result, so bodies that disagree are never shown as one status.
  const groups = STATUS_TYPE_ORDER.map((t) => ({ type: t, items: c.statuses.filter((s) => s.type === t) })).filter((g) => g.items.length);
  const who = (s: SpeciesConservation["statuses"][number]) => `${s.authority}${s.jurisdiction ? ` (${s.jurisdiction})` : ""}`;
  return (
    <section className={`conservation-card ${c.kind}`}>
      <h3>Conservation status</h3>
      <p className="cons-headline"><b>{badgeText(c)}</b> <span className="meta">· {KIND_LABEL[c.kind]}</span></p>
      {c.scope === "populations" && (
        <p className="cons-applies"><b>Population-specific:</b> each status below applies only to the population it names, not to the species as a whole.</p>
      )}
      {groups.map((g) => (
        <div key={g.type} className="cons-group">
          <p className="cons-group-label">{STATUS_TYPE_LABEL[g.type]}</p>
          <ul className="cons-chips" aria-label={STATUS_TYPE_LABEL[g.type]}>
            {g.items.map((s, i) => (
              <li key={`${s.authority}-${s.population}-${i}`} title={`${who(s)}: ${s.status}${s.date ? `, ${s.date}` : ""}${s.population ? `. Applies to: ${s.population}` : ""}`}>
                {s.population && <span className="cons-pop">{s.population}: </span>}
                <b>{shortAuthority(s.authority)}</b>{[s.status, s.date].filter(Boolean).map((t) => <span key={t}> · {t}</span>)}
              </li>
            ))}
          </ul>
        </div>
      ))}
      {c.population && <p className="cons-applies"><b>Applies to:</b> {c.population}</p>}
      {c.statuses.some((s) => s.note || s.source) && (
        <Fold wide={wide} title="Assessment history">
          <dl className="facts">
            {c.statuses.map((s, i) => (
              <div key={`${s.authority}-${s.population}-${i}`}>
                <dt>{who(s)}{s.population ? <span className="meta block">{s.population}</span> : null}</dt>
                <dd>
                  <b>{s.status}</b>{s.date ? <span className="meta"> · {s.date}</span> : null}
                  {s.note ? <span className="meta block">{s.note}</span> : null}
                  {s.source ? <a className="meta block" href={s.source} target="_blank" rel="noreferrer noopener">Source</a> : null}
                </dd>
              </div>
            ))}
          </dl>
        </Fold>
      )}
      {c.significance && <Fold wide={wide} title="Why it matters in Nova Scotia"><p>{c.significance}</p></Fold>}
      {c.threats.length > 0 && (
        <Fold wide={wide} title={`Threats (${c.threats.length})`}>
          <ul className="features">{c.threats.map((t) => <li key={t}>{t}</li>)}</ul>
        </Fold>
      )}
      <p className="meta">
        Checked against official sources on {c.verified_on}. <button className="linklike" onClick={onSources}>Sources in Details & Sources</button>
      </p>
    </section>
  );
}

function SpeciesLink({ name, common, onOpen }: { name: string; common: string; onOpen?: () => void }) {
  const label = <>{common ? `${common} ` : ""}(<i>{name}</i>)</>;
  return onOpen ? <button className="linklike" onClick={onOpen}>{label}</button> : <span>{label}</span>;
}

type CompareProps = {
  name: string; common: string; note: string; photo: CompareImage | null; onOpen?: () => void;
  /** A reference look-alike that isn't on species.csv, so the AI never suggests it. */
  unlisted?: boolean;
  /** On the full page the whole comparison shows; in the drawer the detail folds. */
  wide?: boolean;
};

const COMPARE_VIEW: Record<string, string> = { side: "Side profile", underwater: "Underwater", in_hand: "In hand", illustration: "Illustration", other: "Photo" };

/** A look-alike: its own reference photo, its name and the difference that tells it apart. */
function CompareCard({ name, common, note, photo, onOpen, unlisted, wide }: CompareProps) {
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
        {unlisted && <span className="pill muted photos" title="Shown for comparison only. It isn't on species.csv, so the AI never suggests it.">Reference only · not on the AI list</span>}
        {(() => {
          const [lead, rest] = splitFirstSentence(note);
          return (
            <>
              <p className="meta compare-note">{lead}</p>
              {rest && (wide ? <p className="meta compare-note">{rest}</p> : (
                <details className="fold compare-more"><summary>More</summary><p className="meta compare-note">{rest}</p></details>
              ))}
            </>
          );
        })()}
        {shown && (
          <p className="compare-credit">
            {COMPARE_VIEW[photo.view ?? "other"] ?? "Photo"} · {photo.creator} ·{" "}
            <MaybeLink href={photo.license_url}>{photo.license}</MaybeLink> ·{" "}
            <MaybeLink href={photo.source_url}>{photo.source}</MaybeLink>
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
            <div>
              <dt>Environments in WoRMS</dt>
              <dd>
                {n.source === "WoRMS" ? environmentLabels(n).join(", ") || "None set" : "—"}
                {n.source === "WoRMS" && <span className="meta block">WoRMS's species-level flags: where the species can occur, not the current habitat of a particular population.</span>}
              </dd>
            </div>
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
        <h3>Sources for the identification notes</h3>
        {data.profile && data.profile.sources.length > 0 ? (
          <ul className="features">
            {data.profile.sources.map((s) => <li key={s.url}><a href={s.url} target="_blank" rel="noreferrer noopener">{s.label}</a></li>)}
          </ul>
        ) : <p className="meta">{data.profile ? "No sources listed." : "No identification notes yet."}</p>}
        {data.profile && !data.profile.expert_reviewed && (
          <p className="meta" style={{ marginTop: 6 }}>The notes are a first draft from these sources and have not been reviewed by a fish biologist.</p>
        )}
      </section>

      <section>
        <h3>Conservation sources</h3>
        {data.conservation ? (
          <>
            <ul className="features">
              {data.conservation.sources.map((s) => <li key={s.url}><a href={s.url} target="_blank" rel="noreferrer noopener">{s.label}</a></li>)}
            </ul>
            <p className="meta" style={{ marginTop: 6 }}>Entered by hand from these sources and checked on {data.conservation.verified_on}. Statuses change: confirm with the source before relying on it.</p>
          </>
        ) : <p className="meta">No verified status recorded for this fish, so there is nothing to cite. Unknown is not the same as not at risk.</p>}
      </section>

      <section>
        <h3>Photo credits</h3>
        {data.images.length ? (
          <ul className="features">
            {data.images.map((img) => (
              <li key={img.id}>
                {img.creator} · <MaybeLink href={img.license_url}>{img.license}</MaybeLink> · <MaybeLink href={img.source_url}>{img.source}</MaybeLink>
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
