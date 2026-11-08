import type { ConservationStatus, SpeciesConservation, SpeciesProfile } from "./api";

const STATUS_TYPES = ["assessment", "legal", "introduced", "other"] as const;
/** Headings for each kind of statement, in the order the card shows them. */
export const STATUS_TYPE_LABEL: Record<ConservationStatus["type"], string> = {
  assessment: "Scientific assessment",
  legal: "Legal listing",
  introduced: "Introduced or invasive classification",
  other: "Other classification",
};
export const STATUS_TYPE_ORDER = STATUS_TYPES;

/** The curated type, or one inferred from the authority (matches the server) for older entries. */
function statusType(s: Partial<ConservationStatus>, kind: SpeciesConservation["kind"]): ConservationStatus["type"] {
  if (s.type && (STATUS_TYPES as readonly string[]).includes(s.type)) return s.type;
  const a = String(s.authority ?? "").toLowerCase();
  if (a.startsWith("cosewic")) return "assessment";
  if (a.includes("species at risk act") || a.includes("endangered species act")) return "legal";
  return kind === "invasive_ns" ? "introduced" : "other";
}

/**
 * The badge as the list and header show it. A status that covers some populations only is never
 * shown as the whole species' status.
 */
export function badgeText(c: { badge: string; scope?: SpeciesConservation["scope"] }): string {
  return c.scope === "populations" ? `${c.badge} · some populations` : c.badge;
}

/**
 * One line naming each body's own result ("COSEWIC: Threatened · SARA: Not listed"), so bodies
 * that disagree are never run together as if they agreed. Population-specific entries just say so.
 */
export function statusSummary(c: SpeciesConservation): string {
  if (c.scope === "populations") return "Differs by population: see Conservation status";
  return c.statuses.map((s) => `${shortAuthority(s.authority)}: ${s.status}`).join(" · ");
}

/**
 * A status is shown only with its kind, badge, verification date and at least one https source.
 * Anything less becomes null, which the page shows as "no verified status", never as safe.
 */
export function normalizeConservation(c: Partial<SpeciesConservation> | null | undefined): SpeciesConservation | null {
  if (!c || (c.kind !== "at_risk" && c.kind !== "invasive_ns") || typeof c.badge !== "string" || !c.badge || !c.verified_on) return null;
  const list = <T>(v: T[] | null | undefined): T[] => (Array.isArray(v) ? v : []);
  const sources = list(c.sources).filter((s) => s && typeof s.url === "string" && s.url.startsWith("https://"));
  if (!sources.length) return null;
  const kind = c.kind;
  const str = (v: unknown) => (typeof v === "string" ? v : "");
  const statuses: ConservationStatus[] = list(c.statuses as Partial<ConservationStatus>[] | undefined)
    .filter((s) => s && typeof s.authority === "string" && s.authority && typeof s.status === "string" && s.status)
    .map((s) => ({
      authority: s.authority!, status: s.status!, date: str(s.date), note: str(s.note),
      type: statusType(s, kind), population: str(s.population), jurisdiction: str(s.jurisdiction),
      source: str(s.source).startsWith("https://") ? str(s.source) : "",
    }));
  return {
    kind: c.kind, badge: c.badge, verified_on: String(c.verified_on),
    population: typeof c.population === "string" ? c.population : "",
    historical_range: typeof c.historical_range === "string" ? c.historical_range : "",
    current_range: typeof c.current_range === "string" ? c.current_range : "",
    range_note: typeof c.range_note === "string" ? c.range_note : "",
    environment_now: typeof c.environment_now === "string" ? c.environment_now : "",
    environment_now_note: typeof c.environment_now_note === "string" ? c.environment_now_note : "",
    environment_historical: typeof c.environment_historical === "string" ? c.environment_historical : "",
    statuses,
    // Derived here too, so a "species" scope can never sit on top of a population-specific status.
    scope: statuses.some((s) => s.population) ? "populations" : "species",
    significance: typeof c.significance === "string" ? c.significance : "",
    threats: list(c.threats).filter((t) => typeof t === "string" && t !== ""),
    sources: sources.map((s) => ({ label: typeof s.label === "string" && s.label ? s.label : s.url, url: s.url })),
  };
}

/**
 * Plain environment labels ("Saltwater", "Brackish", "Freshwater") from the WoRMS flags of a
 * checked name. Only WoRMS's own flags count; GBIF matches and unchecked names give none.
 */
export function environmentLabels(n: { source?: string | null; is_marine?: boolean; is_brackish?: boolean; is_freshwater?: boolean } | null | undefined): string[] {
  if (!n || n.source !== "WoRMS") return [];
  return [n.is_marine && "Saltwater", n.is_brackish && "Brackish", n.is_freshwater && "Freshwater"].filter(Boolean) as string[];
}

/** A short name for an assessing body, for compact chips. */
export function shortAuthority(a: string): string {
  if (/^species at risk act/i.test(a)) return "SARA";
  if (/^nova scotia/i.test(a)) return "Nova Scotia";
  return a;
}

/** The first sentence of a note, and the rest, so a comparison can show the key difference and fold the detail. */
export function splitFirstSentence(text: string): [string, string] {
  const m = /^(.+?[.!?])\s+(?=[A-Z0-9])(.*)$/s.exec(text.trim());
  return m ? [m[1], m[2]] : [text.trim(), ""];
}

/** The tabs, and where the old Photos and Identify links now go. */
export const SPECIES_TABS = ["overview", "map", "details"] as const;
export type SpeciesTabKey = (typeof SPECIES_TABS)[number];
const OLD_TABS: Record<string, SpeciesTabKey> = { photos: "overview", identify: "overview" };
/** A tab from an address: the current names, the old ones redirected, anything else the Overview. */
export function tabFromParam(t: string | null): SpeciesTabKey {
  if (t && (SPECIES_TABS as readonly string[]).includes(t)) return t as SpeciesTabKey;
  return (t && OLD_TABS[t]) || "overview";
}

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
    conservation: normalizeConservation(d.conservation),
    profile: p
      ? {
          summary: typeof p.summary === "string" ? p.summary : "",
          features: list(p.features).filter((f) => typeof f === "string" && f !== ""),
          // A look-alike needs a name to link to, and a fish can't be confused with itself.
          similar: list(p.similar)
            .filter((s) => s && typeof s.species === "string" && s.species !== "" && s.species !== species)
            .map((s) => ({
              species: s.species, note: typeof s.note === "string" ? s.note : "",
              ...(typeof s.common === "string" && s.common ? { common: s.common } : {}),
            })),
          sources: list(p.sources).filter((s) => s && typeof s.url === "string" && s.url !== ""),
          expert_reviewed: Boolean(p.expert_reviewed),
        }
      : null,
  };
}
