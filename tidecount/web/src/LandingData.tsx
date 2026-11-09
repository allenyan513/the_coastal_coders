import { Link } from "react-router-dom";
import { SpeciesMediaSummary, SpeciesRow } from "./api";
import { badgeText } from "./speciesProfile";

const LICENCE = (l: string) => (/^public domain/i.test(l) ? "public domain" : l);
const list = (xs: string[]) => (xs.length < 2 ? xs.join("") : `${xs.slice(0, -1).join(", ")} and ${xs[xs.length - 1]}`);

/**
 * The species wiki at a glance: the most-seen fish that have reference photos, each opening its
 * own entry. Photos are CC BY or public domain, so every tile carries its credit in a tooltip and
 * the card names the photographers.
 */
export function SpeciesShowcase({ rows, media, count = 12 }: { rows: SpeciesRow[]; media: SpeciesMediaSummary; count?: number }) {
  const withPhoto = rows
    .filter((r) => media[r.species]?.compare?.thumb)
    .sort((a, b) => b.inat_obs - a.inat_obs)
    .slice(0, count);
  const photos = rows.filter((r) => media[r.species]?.image_count > 0).length;
  const notes = rows.filter((r) => media[r.species]?.has_profile).length;
  const status = rows.filter((r) => media[r.species]?.conservation).length;
  const shown = withPhoto.map((r) => media[r.species].compare!);
  const creators = [...new Set(shown.map((i) => i.creator).filter(Boolean))];
  const sources = [...new Set(shown.map((i) => i.source).filter(Boolean))];
  const licences = [...new Set(shown.map((i) => LICENCE(i.license)).filter(Boolean))].sort();

  return (
    <div className="ln-card">
      <div className="ln-figs">
        <div><b className="num">{rows.length || "…"}</b><span>fish recorded in Nova Scotia</span></div>
        <div><b className="num">{photos || "…"}</b><span>with reference photos</span></div>
        <div><b className="num">{notes || "…"}</b><span>with identification notes</span></div>
        <div><b className="num">{status || "…"}</b><span>with a verified at-risk or introduced status</span></div>
      </div>
      <ul className="ln-fish">
        {withPhoto.map((r) => {
          const m = media[r.species];
          const img = m.compare!;
          const c = m.conservation;
          return (
            <li key={r.species}>
              <Link to={`/species?species=${encodeURIComponent(r.species)}`} title={`Photo: ${img.creator || img.source}, ${LICENCE(img.license)}`}>
                <span className="ln-fish-img">
                  <img src={img.thumb} alt={`${r.common}, ${r.species}`} loading="lazy" />
                  {c && <span className={`pill status-badge ${c.kind}`}>{badgeText(c)}</span>}
                </span>
                <b>{r.common === r.species ? r.species : r.common}</b>
                <i className="meta">{r.species}</i>
              </Link>
            </li>
          );
        })}
        {!withPhoto.length && Array.from({ length: count }, (_, i) => <li key={i} className="ln-fish-empty" aria-hidden><span className="ln-fish-img" /></li>)}
      </ul>
      {creators.length > 0 && (
        <p className="ln-card-note">Photos by {list(creators)}, from {list(sources)} ({licences.join(", ")}). Hover a photo for its credit, or open the fish for the full one.</p>
      )}
      <Link className="ln-more" to="/species">Open the species wiki <span aria-hidden>→</span></Link>
    </div>
  );
}
