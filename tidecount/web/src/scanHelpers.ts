/**
 * Fish Scan's checks and arithmetic, kept free of runtime imports so `pnpm test` can run them under plain Node.
 */
import type { LibraryPhoto, ScanCrop, SpeciesRow } from "./api";

/** The same limit and kinds the Media Library and the scan endpoint accept. */
export const MAX_BYTES = 15 * 1024 * 1024;
export const TYPES = ["image/jpeg", "image/png", "image/webp"];
/** The server refuses a crop narrower than this many pixels of the original picture. */
export const MIN_CROP_PX = 16;

/** Why a picture can't be scanned, or null when it can. The server checks again from the file's own bytes. */
export function fileProblem(file: { size: number; type: string }): string | null {
  if (!file.size) return "That file is empty.";
  if (!TYPES.includes(file.type)) return "Only JPEG, PNG and WebP pictures can be scanned.";
  if (file.size > MAX_BYTES) return `That picture is larger than ${MAX_BYTES / (1024 * 1024)} MB.`;
  return null;
}

const clamp = (v: number) => Math.min(1, Math.max(0, v));

/** The box between two points, as fractions of the picture, kept inside it. */
export function boxBetween(a: { x: number; y: number }, b: { x: number; y: number }): ScanCrop {
  const x1 = clamp(Math.min(a.x, b.x)), y1 = clamp(Math.min(a.y, b.y));
  const x2 = clamp(Math.max(a.x, b.x)), y2 = clamp(Math.max(a.y, b.y));
  return { x: x1, y: y1, w: x2 - x1, h: y2 - y1 };
}

/** A crop's size in pixels of the picture as filmed or photographed. */
export const cropPixels = (crop: ScanCrop, width: number, height: number) =>
  ({ w: Math.round(crop.w * width), h: Math.round(crop.h * height) });

/** True when the box is too small to scan, so a click without a drag doesn't count as a crop. */
export function tooSmall(crop: ScanCrop, width: number, height: number): boolean {
  const px = cropPixels(crop, width, height);
  return px.w < MIN_CROP_PX || px.h < MIN_CROP_PX;
}

/** A model score as a percentage. Small scores keep one decimal, so they don't all read 0%. */
export function scorePercent(score: number): string {
  const pct = Math.max(0, score) * 100;
  return `${pct < 10 ? pct.toFixed(1) : Math.round(pct)}%`;
}

/** A scientific name's common name, or the scientific name when the list has none. */
export function commonOf(rows: SpeciesRow[], species: string): string {
  return rows.find((r) => r.species === species)?.common ?? species;
}

/** The Media Library photos worth offering: not rejected, and matching every word typed against the
 *  species shown on, their common names, the caption, the photographer or the source. */
export function filterLibrary(photos: LibraryPhoto[], rows: SpeciesRow[], query: string): LibraryPhoto[] {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  return photos.filter((p) => {
    if (p.review === "rejected") return false;
    if (!words.length) return true;
    const text = [...p.species, ...p.species.map((s) => commonOf(rows, s)), p.caption, p.creator, p.source].join(" ").toLowerCase();
    return words.every((w) => text.includes(w));
  });
}
