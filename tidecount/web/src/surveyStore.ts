import { useSyncExternalStore } from "react";
import { surveyApi, SurveyKind } from "./api";

/**
 * The survey structure: Site → Transect → Station, and which station each video belongs to.
 * It lives on the server, so every browser and phone sees the same tree. This store keeps a copy,
 * refreshed every few seconds while a page uses it, and after every change.
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
  /** The day a video was filmed, as YYYY-MM-DD, keyed like places. It gives reports their seasons. */
  filmedOn: Record<string, string>;
};

type Kind = SurveyKind;
type Item<K extends Kind> = SurveyData[K][number];
export type SurveyStatus = { loaded: boolean; error: string };

let data: SurveyData = { sites: [], transects: [], stations: [], places: {}, filmedOn: {} };
let status: SurveyStatus = { loaded: false, error: "" };
let last = "";
const listeners = new Set<() => void>();
const emit = () => listeners.forEach((listen) => listen());

/** Fetches the tree. Pages only redraw when something changed. */
export async function refreshSurveys() {
  try {
    const next = await surveyApi.tree();
    const text = JSON.stringify(next);
    if (text !== last) {
      last = text;
      data = next;
    }
    if (!status.loaded || status.error) status = { loaded: true, error: "" };
  } catch (e) {
    status = { ...status, error: `Couldn't load the surveys. ${(e as Error).message}` };
  }
  emit();
}

let timer: ReturnType<typeof setInterval> | undefined;

/** The first page that listens starts the refreshing, and the last one to leave stops it. */
function subscribe(listen: () => void) {
  listeners.add(listen);
  if (listeners.size === 1) {
    refreshSurveys();
    timer = setInterval(refreshSurveys, 5000);
    window.addEventListener("focus", refreshSurveys);
  }
  return () => {
    listeners.delete(listen);
    if (listeners.size === 0) {
      clearInterval(timer);
      window.removeEventListener("focus", refreshSurveys);
    }
  };
}

export function useSurveys() {
  return useSyncExternalStore(subscribe, () => data);
}

export function useSurveyStatus() {
  return useSyncExternalStore(subscribe, () => status);
}

export const newId = () => Math.random().toString(36).slice(2, 10);

/** Runs a change on the server, then reloads. Answers the server's reason when it refused, or "" when it worked. */
async function change(run: () => Promise<unknown>): Promise<string> {
  try {
    await run();
    return "";
  } catch (e) {
    return (e as Error).message;
  } finally {
    await refreshSurveys();
  }
}

/** Adds the item, or saves the fields a person can change if it's already there. */
export function saveItem<K extends Kind>(kind: K, item: Item<K>) {
  const { id, siteId, transectId, ...values } = item as Item<K> & { siteId?: string; transectId?: string };
  const exists = (data[kind] as Item<K>[]).some((x) => x.id === id);
  return change(() => exists ? surveyApi.change(kind, id, values) : surveyApi.add(kind, { id, ...values, parent_id: siteId ?? transectId ?? null }));
}

export const setArchived = (kind: Kind, id: string, archived: boolean) => change(() => surveyApi.change(kind, id, { archived }));

/** Removes an item and what sits under it. The server refuses while any video is filed there. */
export const removeItem = (kind: Kind, id: string) => change(() => surveyApi.remove(kind, id));

/** Files a video, and every run of it, under a station. A date left out stays as it is. */
export const setPlace = (videoRoot: string, stationId: string, filmedOn?: string) =>
  change(() => surveyApi.place(videoRoot, { station_id: stationId, ...(filmedOn === undefined ? {} : { filmed_on: filmedOn }) }));

export const setPlaces = (next: Record<string, string>) => change(() => surveyApi.placeMany(next));

const transectIdsOf = (d: SurveyData, siteId: string) => d.transects.filter((t) => t.siteId === siteId).map((t) => t.id);
const stationIdsOf = (d: SurveyData, transectIds: string[]) => d.stations.filter((s) => transectIds.includes(s.transectId)).map((s) => s.id);

/** How many videos hang off an item, directly or through what sits under it. */
export function videoCount(d: SurveyData, kind: Kind, id: string) {
  const transects = kind === "sites" ? transectIdsOf(d, id) : [id];
  const stations = kind === "stations" ? [id] : stationIdsOf(d, transects);
  return Object.values(d.places).filter((stationId) => stations.includes(stationId)).length;
}

export const NO_DATE = "No date";

/** The season of a YYYY-MM-DD date. December to February is the winter of the December's year. */
export function season(date: string) {
  const [year, month] = date.split("-").map(Number);
  if (!year || !month) return NO_DATE;
  if (month <= 2) return `Winter ${year - 1}`;
  return `${month <= 5 ? "Spring" : month <= 8 ? "Summer" : month <= 11 ? "Fall" : "Winter"} ${year}`;
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

/** The site a station sits under, if it still exists. */
export function siteOf(d: SurveyData, stationId?: string) {
  const transect = d.transects.find((t) => t.id === d.stations.find((s) => s.id === stationId)?.transectId);
  return d.sites.find((s) => s.id === transect?.siteId);
}

/** Where a video belongs, in words. Archived items still read correctly on old records. */
export function placeLabel(d: SurveyData, stationId?: string) {
  const station = d.stations.find((s) => s.id === stationId);
  const transect = d.transects.find((t) => t.id === station?.transectId);
  const site = d.sites.find((s) => s.id === transect?.siteId);
  return station && transect && site ? `${site.name} · ${transect.name} · ${station.name}` : "";
}

const digits = (name: string) => name.match(/\d+/)?.[0] ?? "";

/** The transect and station numbers in one of Coastal Action's file names, if it has both. */
function namedIn(fileName: string) {
  const transect = fileName.match(/(?<![A-Za-z0-9])T(\d+)/i)?.[1];
  const stat = fileName.match(/STAT\s*(\d+)/i)?.[1];
  return transect && stat ? { transect, stat } : null;
}

/** "T1 · STAT2" when a video's file name points to another station than the one it's filed under, else "". */
export function nameMismatch(d: SurveyData, fileName: string, stationId: string) {
  const named = namedIn(fileName);
  const station = d.stations.find((s) => s.id === stationId);
  const transect = d.transects.find((t) => t.id === station?.transectId);
  if (!named || !station || !transect) return "";
  return digits(transect.name) === named.transect && digits(station.name) === named.stat ? "" : `T${named.transect} · STAT${named.stat}`;
}

/** A station from Coastal Action's file names, for a person to confirm: T1-STAT2 411.MP4 is transect 1, station 2. */
export function suggestStation(d: SurveyData, fileName: string) {
  const named = namedIn(fileName);
  if (!named) return "";
  const { transect, stat } = named;
  const match = activeTree(d).flatMap((x) => x.stations).find((s) => digits(s.transect.name) === transect && digits(s.station.name) === stat);
  return match?.station.id ?? "";
}
