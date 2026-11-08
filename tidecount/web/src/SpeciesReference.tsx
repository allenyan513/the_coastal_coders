import { useEffect, useMemo, useRef, useState } from "react";
import type { SpeciesProfile, SpeciesRow } from "./api";
import { speciesPagePath, speciesProfile } from "./speciesData";
import { environmentLabels, splitFirstSentence } from "./speciesProfile";
import { rowForScientific } from "./speciesSearch";
import { Photos, StatusBadge } from "./SpeciesDrawer";

type Props = {
  /** Scientific name of the species to show. */
  species: string;
  rows: SpeciesRow[];
  /** Look at another species, e.g. a look-alike. */
  onOpen: (species: string) => void;
  /** Go back to the list of all species. */
  onList: () => void;
  onClose: () => void;
};

const FEATURES_SHOWN = 5;

/**
 * A short Species wiki entry in a drawer under the video, where the timeline normally is: reference
 * photos from the Media Library on the left, habitat, how to recognise the fish and its look-alikes
 * on the right. The video, its position and the selected track stay as they are. Everything comes
 * from the same profile the wiki loads (and caches); nothing here is written or guessed.
 */
export function SpeciesReference({ species, rows, onOpen, onList, onClose }: Props) {
  const [data, setData] = useState<SpeciesProfile | null>(() => speciesProfile(species).peek() ?? null);
  const [error, setError] = useState("");
  const panel = useRef<HTMLElement>(null);

  useEffect(() => {
    let live = true;
    const profile = speciesProfile(species);
    setData(profile.peek() ?? null);
    setError("");
    profile.get().then((d) => live && setData(d)).catch((e: Error) => live && setError(e.message));
    return () => { live = false; };
  }, [species]);

  // On a phone the drawer sits below the video, so bring it into view without moving the video.
  useEffect(() => { panel.current?.scrollIntoView({ block: "nearest" }); }, [species]);

  const row = rowForScientific(rows, species);
  const common = row && row.common !== row.species ? row.common : data?.taxon?.inat_common_name || "";
  const title = common || species;
  // Only photos a person has checked count as identification references. Uploads still pending
  // review stay out of this comparison (they're still visible in the Media Library).
  const verified = useMemo(() => data?.images.filter((i) => (i.review ?? "verified") === "verified") ?? [], [data]);
  const held = (data?.images.length ?? 0) - verified.length;
  const shown = useMemo(() => (data ? { ...data, images: verified } : null), [data, verified]);

  const p = data?.profile;
  const habitat = [
    data?.conservation?.environment_now,
    ...(data?.conservation?.environment_now ? [] : environmentLabels(data?.names)),
  ].filter(Boolean) as string[];
  const headFeatures = p?.features.slice(0, FEATURES_SHOWN) ?? [];
  const moreFeatures = p?.features.slice(FEATURES_SHOWN) ?? [];
  // The species' own iNaturalist page when the wiki has resolved it, else a search for the scientific name.
  const inatUrl = data?.taxon?.inat_taxon_id
    ? `https://www.inaturalist.org/taxa/${data.taxon.inat_taxon_id}`
    : `https://www.inaturalist.org/taxa/search?q=${encodeURIComponent(species)}`;
  const commonOf = (name: string) => {
    const r = rowForScientific(rows, name);
    return r && r.common !== r.species ? r.common : "";
  };

  return (
    <section className="panel panel-pad species-ref dock" aria-label={`Reference for ${title}`} ref={panel}>
      <header className="species-ref-head">
        <div style={{ minWidth: 0 }}>
          <h2>{title}</h2>
          {common && <p className="sci"><i>{species}</i></p>}
          {data?.conservation && <StatusBadge c={data.conservation} />}
        </div>
        <div className="row species-ref-actions">
          <button type="button" className="btn" onClick={onList} title="Browse and search every species on the list">‹ All species</button>
          <button type="button" className="btn" onClick={onClose} aria-label="Close reference and show the timeline" title="Close (Esc)">Close</button>
        </div>
      </header>

      {error && <p className="meta" role="alert">Couldn't load this reference: {error}</p>}
      {!data && !error && <p className="meta">Loading…</p>}

      {shown && data && (
        <div className="species-ref-body">
          <div className="species-ref-media">
            {verified.length > 0
              ? <Photos key={species} data={shown} title={title} />
              : (
                <div className="gallery-empty compact">
                  <p><b>No verified reference photos yet</b></p>
                  <p className="meta">Photos are added to the Media Library only once the species and licence have been checked.</p>
                </div>
              )}
            {held > 0 && <p className="meta">{held} uploaded {held === 1 ? "photo is" : "photos are"} still pending review in the Media Library, so {held === 1 ? "it isn't" : "they aren't"} shown as {held === 1 ? "a reference" : "references"}.</p>}
          </div>

          <div className="species-ref-text">
            {p?.summary && <p className="species-ref-lede">{p.summary}</p>}

            <dl className="species-ref-facts">
              <div><dt>Scientific name</dt><dd><i>{species}</i></dd></div>
              <div>
                <dt>Habitat</dt>
                <dd>{habitat.length ? habitat.join(" · ") : <span className="meta">Not recorded</span>}</dd>
              </div>
            </dl>

            <section>
              <h3>How to recognise it</h3>
              {p && p.features.length > 0 ? (
                <>
                  <ul className="features">{headFeatures.map((f) => <li key={f}>{f}</li>)}</ul>
                  {moreFeatures.length > 0 && (
                    <details className="fold">
                      <summary>{moreFeatures.length} more</summary>
                      <ul className="features">{moreFeatures.map((f) => <li key={f}>{f}</li>)}</ul>
                    </details>
                  )}
                  {!p.expert_reviewed && <p className="meta">These notes come from published descriptions and haven't been reviewed by a fish biologist.</p>}
                </>
              ) : <p className="meta">No identification notes have been written for this fish yet. Use the photos, and check the similar species.</p>}
            </section>

            {p && p.similar.length > 0 && (
              <section>
                <h3>Often confused with</h3>
                <ul className="species-ref-similar">
                  {p.similar.map((s) => {
                    const listed = !!rowForScientific(rows, s.species);
                    const label = commonOf(s.species) || s.common || "";
                    return (
                      <li key={s.species}>
                        {listed
                          ? <button type="button" className="linklike" onClick={() => onOpen(s.species)}>{label ? `${label} ` : ""}(<i>{s.species}</i>)</button>
                          : <span>{label ? `${label} ` : ""}(<i>{s.species}</i>) <span className="pill muted">Not on the AI list</span></span>}
                        <span className="meta"> {splitFirstSentence(s.note)[0]}</span>
                      </li>
                    );
                  })}
                </ul>
              </section>
            )}

            <p className="species-ref-links">
              <a href={inatUrl} target="_blank" rel="noreferrer noopener">View on iNaturalist</a>
              <a href={speciesPagePath(species)} target="_blank" rel="noreferrer noopener">Full Species Wiki entry</a>
            </p>
          </div>
        </div>
      )}
    </section>
  );
}
