import { KeyboardEvent, useEffect, useMemo, useState } from "react";
import type { SpeciesMediaSummary, SpeciesRow } from "./api";
import { speciesMedia } from "./speciesData";
import { searchSpecies } from "./speciesSearch";

type Props = {
  /** Every species on the list, sorted by common name. */
  rows: SpeciesRow[];
  /** The species the reference last showed, marked in the list. */
  current: string | null;
  /** Scientific names BioCLIP suggested for the selected track, marked "Suggested". */
  suggested: string[];
  /** Open a species' reference. This only looks; it never names the track. */
  onOpen: (species: string) => void;
  onClose: () => void;
};

/**
 * Every species on the list, browsable and searchable by common or scientific name, for looking
 * one up without a BioCLIP suggestion or a search first. It's the same list as the "Name it"
 * picker and the Species wiki. Thumbnails come from the wiki's cached photo summary.
 */
export function SpeciesList({ rows, current, suggested, onOpen, onClose }: Props) {
  const [query, setQuery] = useState("");
  const [media, setMedia] = useState<SpeciesMediaSummary>(() => speciesMedia.peek() ?? {});

  useEffect(() => {
    let live = true;
    speciesMedia.get().then((m) => live && setMedia(m));
    return () => { live = false; };
  }, []);

  const shown = useMemo(() => (query.trim() ? searchSpecies(rows, query) : rows), [rows, query]);
  const hint = useMemo(() => new Set(suggested), [suggested]);

  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key !== "Escape") return;
    e.preventDefault();
    if (query) setQuery("");
    else e.currentTarget.blur();  // so the review shortcuts work again
  };

  return (
    <section className="panel panel-pad species-ref dock species-all" aria-label="All species">
      <header className="species-ref-head">
        <div style={{ minWidth: 0 }}>
          <h2>All species</h2>
          <p className="meta num">{query.trim() ? `${shown.length} of ${rows.length}` : `${rows.length}`} species</p>
        </div>
        <div className="row species-ref-actions">
          <button type="button" className="btn" onClick={onClose} aria-label="Close reference and show the picture menu" title="Close (Esc)">Close</button>
        </div>
      </header>
      <input
        className="name-species"
        type="search"
        autoComplete="off"
        spellCheck={false}
        aria-label="Filter the species list by common or scientific name"
        placeholder="Filter by common or scientific name"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        onKeyDown={onKey}
      />
      {shown.length === 0 ? (
        <p className="meta" role="status">No species on the list matches “{query.trim()}”. If this fish isn't on the list, don't force a name. Mark it as an unidentified fish.</p>
      ) : (
        <ul className="species-all-list" aria-label="Species">
          {shown.map((r) => {
            const thumb = media[r.species]?.thumb;
            return (
              <li key={r.species}>
                <button type="button" className="species-all-row" aria-current={r.species === current} onClick={() => onOpen(r.species)}>
                  <span className="species-all-thumb" aria-hidden="true">
                    {thumb && <img src={thumb} alt="" loading="lazy" onError={(e) => { e.currentTarget.style.display = "none"; }} />}
                  </span>
                  <span className="species-name">
                    <b>{r.common}</b>
                    {r.common !== r.species && <i className="meta">{r.species}</i>}
                  </span>
                  {hint.has(r.species) && <span className="pill accent species-all-tag">Suggested</span>}
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
