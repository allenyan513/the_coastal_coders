import { KeyboardEvent, useEffect, useId, useMemo, useRef, useState } from "react";
import type { SpeciesRow } from "./api";
import { searchSpecies } from "./speciesSearch";

const SHOWN = 40;

type Props = {
  /** Every species on the list (the same rows the Species wiki shows). */
  rows: SpeciesRow[];
  /** Name this species. Called on Enter or a click. */
  onPick: (row: SpeciesRow) => void;
  /** Show this species' reference information without naming it. */
  onPreview: (row: SpeciesRow) => void;
  /** The fish isn't on the list: leave it unidentified rather than guess. */
  onUnidentified: () => void;
};

/**
 * Search the whole species list by common or scientific name and name the selected track with it.
 * It only reports a choice; the caller saves it through the usual track decision. Typing here never
 * triggers the review shortcuts, which ignore text fields.
 */
export function SpeciesPicker({ rows, onPick, onPreview, onUnidentified }: Props) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const listId = useId();

  const found = useMemo(() => searchSpecies(rows, query, SHOWN), [rows, query]);
  const total = useMemo(() => (query.trim() ? searchSpecies(rows, query).length : 0), [rows, query]);
  const typed = query.trim().length > 0;
  const expanded = open && typed && found.length > 0;
  useEffect(() => setActive(0), [query]);
  // Keep the highlighted option in view as the arrow keys move through a long list.
  useEffect(() => {
    if (expanded) document.getElementById(`${listId}-${active}`)?.scrollIntoView({ block: "nearest" });
  }, [active, expanded, listId]);

  const finish = () => {
    setQuery("");
    setOpen(false);
    input.current?.blur();  // so the review shortcuts work again
  };
  const pick = (row: SpeciesRow) => { finish(); onPick(row); };

  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      if (!found.length) return;
      e.preventDefault();
      setOpen(true);
      setActive((i) => (i + (e.key === "ArrowDown" ? 1 : -1) + found.length) % found.length);
    } else if (e.key === "Enter") {
      const row = found[active];
      if (!row) return;
      e.preventDefault();
      pick(row);
    } else if (e.key === "Escape") {
      e.preventDefault();
      if (typed || open) { setQuery(""); setOpen(false); } else input.current?.blur();
    }
  };

  return (
    <div className="picker">
      <input
        ref={input}
        className="name-species"
        type="text"
        role="combobox"
        autoComplete="off"
        spellCheck={false}
        aria-label="Search all species by common or scientific name"
        aria-autocomplete="list"
        aria-expanded={expanded}
        aria-controls={listId}
        aria-activedescendant={expanded ? `${listId}-${active}` : undefined}
        placeholder={`Search all ${rows.length || ""} species by common or scientific name`.replace("  ", " ")}
        value={query}
        onChange={(e) => { setQuery(e.target.value); setOpen(true); }}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        onKeyDown={onKey}
      />
      <ul id={listId} role="listbox" aria-label="Matching species" className="picker-list" hidden={!expanded}>
        {found.map((row, i) => (
          // Mouse down is cancelled so the input keeps focus until the click lands.
          <li
            key={row.species}
            id={`${listId}-${i}`}
            role="option"
            aria-selected={i === active}
            className={i === active ? "on" : ""}
            onMouseDown={(e) => e.preventDefault()}
            onMouseEnter={() => setActive(i)}
            onClick={() => pick(row)}
          >
            <span className="picker-name">
              <b>{row.common}</b>
              {row.common !== row.species && <i className="meta">{row.species}</i>}
            </span>
            <button
              type="button"
              className="linklike picker-ref"
              tabIndex={-1}
              aria-label={`Show reference photos and notes for ${row.common}`}
              onMouseDown={(e) => e.preventDefault()}
              onClick={(e) => { e.stopPropagation(); onPreview(row); }}
            >
              Reference
            </button>
          </li>
        ))}
        {total > found.length && <li role="presentation" className="meta picker-more">{total - found.length} more. Type more to narrow the list.</li>}
      </ul>
      {typed && found.length === 0 && (
        <div className="picker-none" role="status">
          <p className="meta">No species on the list matches “{query.trim()}”. If this fish isn't on the list, don't force a name.</p>
          <button type="button" className="btn" onClick={() => { finish(); onUnidentified(); }}>Mark as unidentified fish</button>
        </div>
      )}
      {!typed && <p className="meta">Not on the list? Use Unidentified fish.</p>}
    </div>
  );
}
