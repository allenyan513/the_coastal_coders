/**
 * Year ranges for the map filters, in single years, with no knowledge of any data source.
 *
 * A range is `{ from, to }` in whole years; `null` means open on that side, so it has no limit at
 * all. The slider has one position per year from `scale.first` to `scale.last`, plus one more at the
 * left end that stands for "earlier": a start handle resting there takes every older record, even
 * one from before the first year shown, and an end handle resting on the last year takes every
 * newer one. So "All years" really is all of them. Any source (OBIS now, GBIF later) can send these
 * as a start and end year.
 */
export type YearRange = { from: number | null; to: number | null };
/** The years the slider shows, `first` to `last`. Position 0 is "earlier", position n is year first + n - 1. */
export type YearScale = { first: number; last: number };
export type YearPreset = { label: string; range: YearRange };

export const ALL_YEARS: YearRange = { from: null, to: null };

export function makeScale(first: number, last: number): YearScale {
  return { first, last: Math.max(first + 1, last) };
}

/** The last slider position: the scale's last year, which also means "and later". */
export const lastPosition = (scale: YearScale) => scale.last - scale.first + 1;

/** The year a position stands for (position 0 is the year before the scale: "earlier"). */
export const yearAt = (n: number, scale: YearScale) => scale.first + n - 1;

/** The range for two slider positions. A start at "earlier" or an end at the last year means no limit. */
export function fromPositions(i: number, j: number, scale: YearScale): YearRange {
  const [a, b] = i <= j ? [i, j] : [j, i];
  return {
    from: a <= 0 ? null : yearAt(a, scale),
    to: b >= lastPosition(scale) ? null : yearAt(b, scale),
  };
}

/** Slider positions for a range; years outside the scale are clamped to its ends. */
export function toPositions(range: YearRange, scale: YearScale): [number, number] {
  const max = lastPosition(scale);
  const clamp = (n: number) => Math.min(max, Math.max(0, n));
  const i = range.from === null ? 0 : clamp(range.from - scale.first + 1);
  const j = range.to === null ? max : clamp(range.to - scale.first + 1);
  return [Math.min(i, j), j];
}

/** A range as the slider can show it, so equal ranges compare equal however they were made. */
export function normalize(range: YearRange, scale: YearScale): YearRange {
  const [i, j] = toPositions(range, scale);
  return fromPositions(i, j, scale);
}

export const sameRange = (a: YearRange, b: YearRange) => a.from === b.from && a.to === b.to;
export const isAllYears = (r: YearRange) => r.from === null && r.to === null;

/** The year range in words: "All years", "2018–2022", "2020", "2020–present", "up to 2009". */
export function describeRange(r: YearRange): string {
  if (r.from === null && r.to === null) return "All years";
  if (r.from === null) return `up to ${r.to}`;
  if (r.to === null) return `${r.from}–present`;
  return r.from === r.to ? String(r.from) : `${r.from}–${r.to}`;
}

/** Whether a calendar year is inside a range. */
export const yearInRange = (year: number, r: YearRange) => (r.from === null || year >= r.from) && (r.to === null || year <= r.to);

/** All years, then the decades from the newest on back: 2020s, 2010s, 2000s. */
export function decadePresets(scale: YearScale, lastYear: number, decades = 3): YearPreset[] {
  const out: YearPreset[] = [{ label: "All years", range: ALL_YEARS }];
  const newest = Math.floor(lastYear / 10) * 10;
  for (let d = newest; out.length <= decades && d >= scale.first; d -= 10) {
    out.push({ label: `${d}s`, range: normalize({ from: d, to: d + 9 }, scale) });
  }
  return out;
}

/** Tick years under the slider: every `every` years, leaving room at the left for the "earlier" label. */
export function tickYears(scale: YearScale, every = 25): number[] {
  const out: number[] = [];
  for (let y = Math.ceil((scale.first + every / 2) / every) * every; y <= scale.last; y += every) out.push(y);
  return out;
}
