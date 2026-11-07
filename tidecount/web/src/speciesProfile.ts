import type { SpeciesProfile } from "./api";

/**
 * Fill in every field the species drawer reads, so a profile from an older server, or a
 * hand-edited entry with a missing list, renders as "nothing yet" instead of throwing.
 *
 * Kept free of runtime imports so `pnpm test` can run it under plain Node.
 */
export function normalizeProfile(raw: Partial<SpeciesProfile> | null | undefined, species: string): SpeciesProfile {
  const d = raw ?? {};
  const p = d.profile;
  const list = <T>(v: T[] | null | undefined): T[] => (Array.isArray(v) ? v : []);
  return {
    species: d.species ?? species,
    curated: Boolean(d.curated),
    taxon: d.taxon ?? null,
    images: list(d.images).filter((i) => i && typeof i.url === "string" && i.url !== ""),
    names: d.names ? { ...d.names, synonyms: list(d.names.synonyms) } : null,
    mentioned_by: list(d.mentioned_by).filter((m) => m && typeof m.species === "string"),
    profile: p
      ? {
          summary: typeof p.summary === "string" ? p.summary : "",
          features: list(p.features).filter((f) => typeof f === "string" && f !== ""),
          // A look-alike needs a name to link to, and a fish can't be confused with itself.
          similar: list(p.similar)
            .filter((s) => s && typeof s.species === "string" && s.species !== "" && s.species !== species)
            .map((s) => ({ species: s.species, note: typeof s.note === "string" ? s.note : "" })),
          sources: list(p.sources).filter((s) => s && typeof s.url === "string" && s.url !== ""),
          expert_reviewed: Boolean(p.expert_reviewed),
        }
      : null,
  };
}
