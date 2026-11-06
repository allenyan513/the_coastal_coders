import { Candidate, Track } from "./api";

export const UNIDENTIFIED = "Fish, unidentified";
export const nameOf = (c: Candidate) => c.common;

/** Taking the top suggestion confirms it. Anything else is a person's correction. */
export const stateFor = (t: Track, species: string): "Confirmed" | "Corrected" =>
  t.candidates[0] && nameOf(t.candidates[0]) === species ? "Confirmed" : "Corrected";

/** The species model is often wrong on new footage, so a name is only put forward above this score. */
export const SURE = 0.9;

/** The species name shown on a track nobody has decided, or null when the model isn't sure. */
export const guess = (t: Track) => (t.candidates[0] && t.candidates[0].score >= SURE ? nameOf(t.candidates[0]) : null);

/** The name Confirm gives a track: its suggestion if the model is sure, else unidentified. */
export const topName = (t: Track) => guess(t) ?? UNIDENTIFIED;

/** Where a track's box is at time t, interpolated between samples. Null if it isn't on screen. */
export function pos(track: Track, t: number) {
  const p = track.points;
  if (!p.length || t < p[0][0] - 0.4 || t > p[p.length - 1][0] + 0.4) return null;
  const i = p.findIndex((row) => row[0] >= t);
  if (i <= 0) return i === 0 ? p[0] : p[p.length - 1];
  const [a, b] = [p[i - 1], p[i]];
  const k = (t - a[0]) / (b[0] - a[0] || 1);
  return a.map((v, n) => v + (b[n] - v) * k) as Track["points"][number];
}
