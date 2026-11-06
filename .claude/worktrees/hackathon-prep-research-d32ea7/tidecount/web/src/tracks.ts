import { Track } from "./api";

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
