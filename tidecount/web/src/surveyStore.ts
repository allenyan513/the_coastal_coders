import { useSyncExternalStore } from "react";

/**
 * The survey structure: Site → Transect → Station, and which station each video belongs to.
 * It lives in this browser for now, because the server has no tables for it yet.
 * Reports and the workflow board build on these shapes.
 */
export type Flag = "" | "treatment" | "reference";
export type Site = { id: string; name: string; coordinates: string; flag: Flag; archived: boolean };
export type Transect = { id: string; siteId: string; name: string; archived: boolean };
export type Station = { id: string; transectId: string; name: string; coordinates: string; depth: string; archived: boolean };

export type SurveyData = {
  sites: Site[];
  transects: Transect[];
  stations: Station[];
  /** Station by video, keyed by the first import of it, so re-runs with another model share a station. */
  places: Record<string, string>;
};

type Kind = "sites" | "transects" | "stations";
type Item<K extends Kind> = SurveyData[K][number];

const KEY = "tideflow-structure";

/** Sample names only. Coastal Action's real sites are still an open question in the PRD, so nothing here is a fact about them. */
function seed(): SurveyData {
  const station = (transectId: string, n: number): Station => ({ id: `${transectId}-s${n}`, transectId, name: `STAT${n}`, coordinates: "", depth: "", archived: false });
  return {
    sites: [{ id: "sample-site", name: "Sample site", coordinates: "", flag: "treatment", archived: false }],
    transects: [
      { id: "t1", siteId: "sample-site", name: "T1", archived: false },
      { id: "t2", siteId: "sample-site", name: "T2", archived: false },
    ],
    stations: [1, 2, 3].flatMap((n) => [station("t1", n), station("t2", n)]).sort((a, b) => a.id.localeCompare(b.id)),
    places: {},
  };
}

function read(): SurveyData {
  try {
    const stored = localStorage.getItem(KEY);
    return stored ? { ...seed(), ...JSON.parse(stored) } : seed();
  } catch {
    return seed();
  }
}

let data = read();
const listeners = new Set<() => void>();

function commit(next: SurveyData) {
  data = next;
  try {
    localStorage.setItem(KEY, JSON.stringify(next));
  } catch {
    // Private windows can refuse storage. Changes then last until the page reloads.
  }
  listeners.forEach((listen) => listen());
}

export function useSurveys() {
  return useSyncExternalStore((listen) => {
    listeners.add(listen);
    return () => listeners.delete(listen);
  }, () => data);
}

export const newId = () => Math.random().toString(36).slice(2, 10);

export function saveItem<K extends Kind>(kind: K, item: Item<K>) {
  const list = data[kind] as Item<K>[];
  const next = list.some((x) => x.id === item.id) ? list.map((x) => (x.id === item.id ? item : x)) : [...list, item];
  commit({ ...data, [kind]: next });
}

export function setArchived(kind: Kind, id: string, archived: boolean) {
  commit({ ...data, [kind]: (data[kind] as Item<Kind>[]).map((x) => (x.id === id ? { ...x, archived } : x)) });
}

export function setPlace(videoRoot: string, stationId: string) {
  commit({ ...data, places: { ...data.places, [videoRoot]: stationId } });
}

export function setPlaces(next: Record<string, string>) {
  commit({ ...data, places: { ...data.places, ...next } });
}

export const resetSurveys = () => commit(seed());

const transectIdsOf = (d: SurveyData, siteId: string) => d.transects.filter((t) => t.siteId === siteId).map((t) => t.id);
const stationIdsOf = (d: SurveyData, transectIds: string[]) => d.stations.filter((s) => transectIds.includes(s.transectId)).map((s) => s.id);

/** How many videos hang off an item, directly or through what sits under it. */
export function videoCount(d: SurveyData, kind: Kind, id: string) {
  const transects = kind === "sites" ? transectIdsOf(d, id) : [id];
  const stations = kind === "stations" ? [id] : stationIdsOf(d, transects);
  return Object.values(d.places).filter((stationId) => stations.includes(stationId)).length;
}

/** Removes an item and what sits under it. Callers offer this only when no video refers to it. */
export function removeItem(kind: Kind, id: string) {
  if (videoCount(data, kind, id) > 0) return;
  const transects = kind === "sites" ? transectIdsOf(data, id) : kind === "transects" ? [id] : [];
  const stations = kind === "stations" ? [id] : stationIdsOf(data, transects);
  commit({
    ...data,
    sites: kind === "sites" ? data.sites.filter((s) => s.id !== id) : data.sites,
    transects: data.transects.filter((t) => !transects.includes(t.id)),
    stations: data.stations.filter((s) => !stations.includes(s.id)),
  });
}

/** Stations that can take new footage, labelled with their transect, grouped by site. */
export function activeTree(d: SurveyData) {
  return d.sites.filter((s) => !s.archived).map((site) => ({
    site,
    stations: d.transects
      .filter((t) => t.siteId === site.id && !t.archived)
      .flatMap((t) => d.stations.filter((s) => s.transectId === t.id && !s.archived).map((station) => ({ station, transect: t, label: `${t.name} · ${station.name}` }))),
  }));
}

/** Where a video belongs, in words. Archived items still read correctly on old records. */
export function placeLabel(d: SurveyData, stationId?: string) {
  const station = d.stations.find((s) => s.id === stationId);
  const transect = d.transects.find((t) => t.id === station?.transectId);
  const site = d.sites.find((s) => s.id === transect?.siteId);
  return station && transect && site ? `${site.name} · ${transect.name} · ${station.name}` : "";
}

const digits = (name: string) => name.match(/\d+/)?.[0] ?? "";

/** A station from Coastal Action's file names, for a person to confirm: T1-STAT2 411.MP4 is transect 1, station 2. */
export function suggestStation(d: SurveyData, fileName: string) {
  const transect = fileName.match(/(?<![A-Za-z0-9])T(\d+)/i)?.[1];
  const stat = fileName.match(/STAT\s*(\d+)/i)?.[1];
  if (!transect || !stat) return "";
  const match = activeTree(d).flatMap((x) => x.stations).find((s) => digits(s.transect.name) === transect && digits(s.station.name) === stat);
  return match?.station.id ?? "";
}
