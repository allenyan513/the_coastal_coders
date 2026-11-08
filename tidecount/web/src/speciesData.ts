/**
 * The Species wiki's data, loaded once per session and shared by the list, the drawer and the
 * full-page view, so moving between them shows what is already loaded instead of asking again.
 * A failed request is forgotten, so the next attempt tries again.
 */
import { api, SpeciesMediaSummary, SpeciesProfile, SpeciesRow } from "./api";
import { normalizeProfile } from "./speciesProfile";

type Once<T> = { get: () => Promise<T>; reload: () => Promise<T>; peek: () => T | undefined };

const once = <T>(load: () => Promise<T>): Once<T> => {
  let pending: Promise<T> | null = null;
  let value: T | undefined;
  const get = () => {
    pending ??= load().then((v) => (value = v), (e) => { pending = null; throw e; });
    return pending;
  };
  return {
    get,
    /** Asks again, keeping the old value to show meanwhile. */
    reload: () => { pending = null; return get(); },
    /** What has arrived already, to render without waiting. */
    peek: () => value,
  };
};

export const speciesRows = once<SpeciesRow[]>(() => api.species());
export const speciesMedia = once<SpeciesMediaSummary>(() => api.speciesMedia().catch(() => ({})));

const profiles = new Map<string, Once<SpeciesProfile>>();
export function speciesProfile(name: string) {
  let p = profiles.get(name);
  if (!p) profiles.set(name, (p = once(() => api.speciesProfile(name).then((d) => normalizeProfile(d, name)))));
  return p;
}

/** The fish last opened in the drawer or as a full page, so the list can mark it when you come back. Session only. */
export const lastViewed = { species: "" };

/** The address of a species' full page, with the tab to open. */
export const speciesPagePath = (name: string, tab?: string) =>
  `/species/${encodeURIComponent(name)}${tab && tab !== "overview" ? `?tab=${tab}` : ""}`;
