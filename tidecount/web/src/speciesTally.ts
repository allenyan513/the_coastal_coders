/**
 * Species on the Count tab, a front-end trial. Each dot can carry a species, and the counts per
 * species are kept in this browser only (localStorage), per video. The server still gets the plain
 * dots, so MeanCount and every saved count are unchanged.
 */
import { Dot } from "./api";

/** A dot with the species it was counted as. No species means an unidentified fish. */
export type SpeciesDot = Dot & { species?: string };
export type Tag = { x: number; y: number; species: string };
export type SpeciesStore = { palette: string[]; frames: Record<string, Tag[]> };

/** Colours for named species, in palette order. Blue and green stay for unidentified AI and person dots. */
export const SPECIES_COLORS = ["#f97316", "#d946ef", "#eab308", "#ef4444", "#8b5cf6", "#14b8a6", "#a16207", "#ec4899", "#64748b"];
export const UNIDENTIFIED_COLOR = "#1f5eff";
export const UNIDENTIFIED_LABEL = "Unidentified";

/** Things a counter may tag that aren't fish. They stay out of the fish total and MeanCount. */
export const NON_FISH = ["Crab", "Lobster", "Shrimp", "Jellyfish", "Comb jelly", "Sea star", "Sea urchin", "Snail", "Squid", "Seal"];
export const isNonFish = (species?: string) => !!species && NON_FISH.some((n) => n.toLowerCase() === species.trim().toLowerCase());

const key = (videoId: string) => `tidecount.count-species.${videoId}`;

export function loadSpecies(videoId: string): SpeciesStore {
  try {
    const raw = localStorage.getItem(key(videoId));
    if (raw) {
      const s = JSON.parse(raw);
      return { palette: Array.isArray(s.palette) ? s.palette : [], frames: s.frames ?? {} };
    }
  } catch {
    // Private windows and blocked storage just start empty.
  }
  return { palette: [], frames: {} };
}

export function saveSpecies(videoId: string, store: SpeciesStore) {
  try {
    localStorage.setItem(key(videoId), JSON.stringify(store));
  } catch {
    // Not saved, but counting still works for this visit.
  }
}

export const colorOf = (palette: string[], species?: string) =>
  species ? SPECIES_COLORS[Math.max(0, palette.indexOf(species)) % SPECIES_COLORS.length] : UNIDENTIFIED_COLOR;

/** The saved species of a dot the server sent back, found by its position. */
export const withSpecies = (dots: Dot[], tags: Tag[] = []): SpeciesDot[] =>
  dots.map((d) => {
    const tag = tags.find((t) => Math.abs(t.x - d.x) < 1e-4 && Math.abs(t.y - d.y) < 1e-4);
    return tag ? { ...d, species: tag.species } : d;
  });

/** How many of each species, unidentified first, then in palette order. */
export function tally(dots: SpeciesDot[], palette: string[]) {
  const n = new Map<string, number>();
  dots.forEach((d) => n.set(d.species ?? "", (n.get(d.species ?? "") ?? 0) + 1));
  const order = ["", ...palette, ...[...n.keys()].filter((k) => k && !palette.includes(k))];
  return order.filter((k) => n.get(k)).map((k) => ({ species: k, n: n.get(k)! }));
}
