/**
 * Searching the species list by common or scientific name, for the Identify workspace's picker.
 * Kept free of runtime imports so `pnpm test` can run it under plain Node.
 */
import type { SpeciesRow } from "./api";

/** Lower case, accents and punctuation folded away, so "Atlantic  cod" and "atlantic-cod" match alike. */
export const fold = (s: string) =>
  s.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();

/** How well one name matches the query: lower is better, null is no match. */
function rank(name: string, q: string): number | null {
  const n = fold(name);
  if (!n) return null;
  if (n === q) return 0;
  if (n.startsWith(q)) return 1;
  if (n.split(" ").some((w) => w.startsWith(q))) return 2;
  if (n.includes(q)) return 3;
  return null;
}

/**
 * Every row whose common or scientific name contains all the words typed, best matches first, then
 * by common name. A row with no common name carries its scientific name as `common`, as the server does.
 */
export function searchSpecies(rows: SpeciesRow[], query: string, limit = Infinity): SpeciesRow[] {
  const q = fold(query);
  if (!q) return [];
  const words = q.split(" ");
  const scored: { row: SpeciesRow; score: number }[] = [];
  for (const row of rows) {
    // Whole phrase first, so "atlantic cod" puts Atlantic cod above names that merely contain both words.
    const whole = [rank(row.common, q), rank(row.species, q)].filter((s): s is number => s !== null);
    let score = whole.length ? Math.min(...whole) : null;
    if (score === null) {
      const each = words.map((w) => {
        const hits = [rank(row.common, w), rank(row.species, w)].filter((s): s is number => s !== null);
        return hits.length ? Math.min(...hits) : null;
      });
      if (each.every((s) => s !== null)) score = 4 + Math.max(...(each as number[]));
    }
    if (score !== null) scored.push({ row, score });
  }
  scored.sort((a, b) => a.score - b.score || a.row.common.localeCompare(b.row.common));
  return scored.slice(0, limit).map((s) => s.row);
}

/** The row a decision's species name refers to. Decisions store the common name, as the review has always done. */
export const rowForName = (rows: SpeciesRow[], name: string | null | undefined) =>
  (name ? rows.find((r) => r.common === name) ?? null : null);

/** The row for a scientific name, which is how candidates and the wiki identify a species. */
export const rowForScientific = (rows: SpeciesRow[], scientific: string) => rows.find((r) => r.species === scientific) ?? null;
