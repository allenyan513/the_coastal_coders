import type { YearRange } from "./yearRange";

/** `&since=…&until=…` for the ends of a year range that are set. */
const yearParams = (y: YearRange) => `${y.from !== null ? `&since=${y.from}` : ""}${y.to !== null ? `&until=${y.to}` : ""}`;

/**
 * Which OBIS datasets the map counts: one observation method, one dataset, or both (null = any).
 * The server turns them into dataset ids from the region's dataset list, so the region goes too.
 */
export type RecordFilter = { method: RecordMethodFilter | null; dataset: string | null };
export type RecordMethod = "survey" | "telemetry" | "edna" | "other";
export type RecordMethodFilter = RecordMethod | "no_telemetry";
export const NO_FILTER: RecordFilter = { method: null, dataset: null };
export const isFiltered = (f: RecordFilter) => f.method !== null || f.dataset !== null;
const methodParams = (f: RecordFilter) => `${f.method ? `&method=${f.method}` : ""}${f.dataset ? `&dataset=${encodeURIComponent(f.dataset)}` : ""}`;
const filterParams = (region: string, f: RecordFilter) => (isFiltered(f) ? `&region=${region}${methodParams(f)}` : "");
/** What an answer says it was filtered by, to tell a stale answer from the current one. */
type FilterEcho = { method: string | null; dataset: string | null; datasets: number | null };
export const matchesFilter = (echo: FilterEcho | undefined, f: RecordFilter) => (echo?.method ?? null) === f.method && (echo?.dataset ?? null) === f.dataset;

/** False on the public demo, where uploads go to the server and not to this computer. */
export const isLocal = ["localhost", "127.0.0.1", "[::1]"].includes(window.location.hostname);

export type Video = {
  id: string;
  name: string;
  site: string;
  station_id: string;
  filmed_on: string;
  duration: number;
  width: number;
  height: number;
  status: string;
  stage: string;
  progress: number;
  error: string;
  notes: string;
  detector: string;
  source_id: string;
  to_review?: number;
};

export type ModelOption = { key: string; label: string; available: boolean; note: string; default: boolean };

export type Run = {
  id: string;
  detector: string;
  label: string;
  status: string;
  stage: string;
  progress: number;
  error: string;
  tracks: number;
  boxes: number;
  seconds: { second: number; detections: number }[];
  seconds_with_fish: number;
  to_review: number;
  ms_per_frame: number;
};

export type Comparison = { name: string; duration: number; width: number; height: number; runs: Run[] };

export type Segment = {
  id: number;
  idx: number;
  start: number;
  end: number;
  kind: "active" | "quiet";
  is_audit: number;
  is_dense: number;
  low_vis: number;
  score: number;
  status: "needs_review" | "reviewed" | "could_not_see" | "skipped";
};

export type SecondRow = { second: number; detections: number; clarity: number };
export type VideoDetail = Video & { segments: Segment[]; seconds: SecondRow[] };
export type Candidate = { species: string; common: string; score: number };

export type Track = {
  id: number;
  ext_id: number;
  manual: number;
  static: number;
  first_t: number;
  last_t: number;
  conf: number;
  has_crop: boolean;
  state: "Confirmed" | "Corrected" | "Rejected" | null;
  decided_species: string | null;
  points: [number, number, number, number, number][];
  candidates: Candidate[];
};

export type SpeciesRow = { species: string; common: string; group: string; inat_obs: number; obis_nearshore_records: number; seine_records: number; confirmed: number };

export type SpeciesImage = {
  id: string;
  url: string;
  thumb_url?: string;
  view: "side" | "underwater" | "in_hand" | "illustration" | "other";
  caption: string;
  creator: string;
  license: string;
  license_url: string;
  source: string;
  source_url: string;
  place?: string;
  verification: string;
};
export type SpeciesProfile = {
  species: string;
  curated: boolean;
  taxon: {
    scientific_name: string; authority: string; family: string; inat_taxon_id: number; inat_common_name?: string;
    gbif_key: number; aphia_id?: number | null; resolved_on: string;
  } | null;
  profile: {
    summary: string;
    features: string[];
    /** `common` names a look-alike that isn't on the species list (so there's no row to take it from). */
    similar: { species: string; note: string; common?: string }[];
    sources: { label: string; url: string }[];
    expert_reviewed: boolean;
  } | null;
  images: SpeciesImage[];
  /** The name checked against WoRMS, or GBIF when WoRMS doesn't know it. Null when unchecked. */
  names: SpeciesNames | null;
  /** Other entries that list this species as easily confused with them. */
  mentioned_by: { species: string; note: string }[];
  /** Verified conservation or invasive status, hand-curated from official sources. Null means unknown, never "safe". */
  conservation: SpeciesConservation | null;
};
export type SpeciesConservation = {
  /** at_risk: a conservation listing. invasive_ns: introduced and invasive in Nova Scotia. */
  kind: "at_risk" | "invasive_ns";
  badge: string;
  verified_on: string;
  /** Which population or area the status applies to. */
  population: string;
  /** Where the species lived before, and where wild fish are known now; "" when not recorded. */
  historical_range: string;
  current_range: string;
  /** Why older sources may disagree with the current range. */
  range_note: string;
  /** The known wild population's environment now ("Freshwater"), and before; "" when WoRMS's list is enough. */
  environment_now: string;
  environment_now_note: string;
  environment_historical: string;
  /** "populations" when any status names a population: the badge then covers some populations only. */
  scope: "species" | "populations";
  statuses: ConservationStatus[];
  significance: string;
  threats: string[];
  sources: { label: string; url: string }[];
};
/**
 * One assessment, listing or classification. assessment: a scientific status (COSEWIC). legal: a
 * listing under an act (SARA, the Nova Scotia Endangered Species Act). introduced: an introduced or
 * invasive classification. An empty population means the whole species as far as the entry covers it.
 */
export type ConservationStatus = {
  authority: string;
  status: string;
  date?: string;
  note?: string;
  type: "assessment" | "legal" | "introduced" | "other";
  population: string;
  jurisdiction: string;
  source: string;
};
export type SpeciesNames = {
  source: "WoRMS" | "GBIF" | null;
  status: string;
  aphia_id: number | null;
  accepted_name: string | null;
  accepted_aphia_id?: number | null;
  authority?: string;
  family?: string;
  url?: string;
  synonyms: string[];
  is_marine?: boolean;
  is_brackish?: boolean;
  is_freshwater?: boolean;
};
/** The photo a look-alike card shows (a side profile when there is one), with the credit its licence needs. */
export type CompareImage = {
  thumb: string; view: SpeciesImage["view"] | null;
  creator: string; license: string; license_url: string; source: string; source_url: string;
};
export type SpeciesMediaSummary = Record<string, {
  image_count: number; thumb: string | null; compare?: CompareImage | null; has_profile: boolean;
  conservation?: Pick<SpeciesConservation, "kind" | "badge"> & { scope?: SpeciesConservation["scope"] } | null;
}>;

/** Shared by every OBIS answer: where it came from and how fresh it is. */
type ObisMeta = { source: "OBIS"; fetched_at: number | null; cached: boolean; stale: boolean; citation: string };
/** [west, south, east, north, record count] */
export type ObisCell = [number, number, number, number, number];
export type ObisGrid = ObisMeta & {
  species: string; precision: number; since: number | null; until: number | null;
  filter?: FilterEcho;
  present: ObisCell[]; present_truncated: boolean;
};
export type ObisDataset = { id: string; title: string; records: number | null; institution: string; url: string; telemetry: boolean };
/** Every dataset with records of the species in a region, with its method as its OBIS metadata states it. */
export type ObisCatalog = ObisMeta & {
  species: string; region: string; label: string;
  /** False when OBIS lists more datasets than the server reads; filters are then refused. */
  total: number; complete: boolean;
  methods: { key: RecordMethod; label: string; datasets: number; records: number }[];
  datasets: (ObisDataset & { method: RecordMethod })[];
};
export type ObisRecord = {
  id: string; date: string; year: number | null; lat: number; lon: number;
  uncertainty_m: number | null; depth_m: number | null; dataset: string; dataset_url: string;
  institution: string; basis: string; recorded_by: string; count: string | number | null;
  absent: boolean; name_as_recorded: string; license: string;
};
export type ObisRecords = ObisMeta & { species: string; total: number; records: ObisRecord[] };
/** One sampling method's non-detections, as site-dates (one place, one day) rather than raw rows. */
export type ObisNdMethod = {
  method: string; label: string; site_dates: number; sites: number; detected_site_dates: number; absence_rows: number;
  first_date: string | null; last_date: string | null;
  datasets: { id: string; title: string; url: string; absence_rows: number; site_dates: number; sites: number }[];
};
export type ObisNonDetections = ObisMeta & {
  species: string; region: string; label: string;
  /** "queued" and "computing" mean a background job is working: ask again. */
  status: "ok" | "none" | "too_many" | "computing" | "queued"; absence_rows: number;
  /** Calculations ahead of this one while it waits. */
  ahead?: number;
  methods: ObisNdMethod[];
  withheld: (ObisNdMethod & { reason: string })[];
  points: { lat: number; lon: number; method: string; dates: number; first: string | null; last: string | null }[];
  points_truncated?: boolean;
};
/**
 * eDNA water-sample evidence, as sampling site-dates (one place, one day), never as sequence rows.
 * A detection is DNA of the fish found in a sample. A non-detection is a sample from a dataset that
 * reports its zeros in which none was found: not proof the fish was absent.
 */
export type EdnaDataset = {
  id: string; title: string; url: string; marker: string;
  detected_site_dates: number; nondetected_site_dates: number; withheld_site_dates: number; reports_nondetections: boolean;
};
export type EdnaPoint = { lat: number; lon: number; detected: number; not_detected: number; first: string | null; last: string | null };
export type EdnaEvidence = ObisMeta & {
  species: string; region: string; label: string;
  /** "computing" with nothing else means the server is still fetching the detections. */
  status: "ok" | "none" | "computing";
  detections: { site_dates: number; sites: number; first_date: string | null; last_date: string | null } | null;
  nondetections: {
    state: "queued" | "computing" | "ready" | "none" | "too_many";
    progress: { done: number; total: number } | null;
    ahead?: number;
    site_dates: number; sites: number; first_date: string | null; last_date: string | null;
    withheld: { method: string; label: string; site_dates: number; reason: string }[];
  };
  datasets: EdnaDataset[];
  by_year: { year: number; detected: number; not_detected: number }[];
  points: EdnaPoint[];
  points_truncated?: boolean;
  notes: string[];
  refreshing?: boolean;
  /** The year range these counts are for (null = open), and every year the samples span, so a range with nothing in it can say where the samples are. */
  range?: { since: number | null; until: number | null };
  available?: { first_date: string | null; last_date: string | null };
};
export type ObisSummary = ObisMeta & {
  species: string; region: string; label: string;
  /** Occurrence records, not fish. There is deliberately no absence total: see ObisNonDetections. */
  present: number; first_year: number | null; last_year: number | null; since_2010: number;
  /** At least this share of records are tag detections from tracking studies, which repeat one fish many times. */
  telemetry_share: number;
  dataset_count: number;
  /** Records for each year that has any (all years in the region), so any year range can be totalled here. */
  by_year: { year: number; records: number }[];
  datasets: ObisDataset[];
  filter?: FilterEcho;
};

export type AccuracyRow = {
  id: string; name: string; site: string; detector: string; model: string;
  frames_total: number; frames_blind: number; frames_assisted: number; frames_could_not_see: number;
  fish: number; found: number; missed: number; extra_boxes: number;
};

export type Dot = { x: number; y: number; source: "ai" | "user" };
/** A box AI drew on one analysed frame, below the confidence that starts a track. */
export type FrameBox = { x: number; y: number; w: number; h: number; conf: number };
export type SchoolCount = { id: number; t: number; dots: Dot[]; model: string };

export type ReportPoint = {
  id: number; t: number; status: SnapshotStatus; total: number | null; invertebrates: number | null;
  species: SpeciesCount[]; visibility: string; comment: string;
};
export type ReportPeak = { id: number; t: number; status: SnapshotStatus; total: number | null; ai_count: number; in_window: boolean };

export type Summary = {
  video: { id: string; name: string; site: string; duration: number; notes: string };
  entries: number;
  entries_added: number;
  species_count: number;
  species: { name: string; entries: number }[];
  schools: { t: number; total: number; proposed: number; removed: number; added: number }[];
  snapshots: SnapshotStats;
  protocol: Protocol;
  points: ReportPoint[];
  species_observed: string[];
  peaks: ReportPeak[];
  reviewed: number;
  could_not_see: number;
  skipped: number;
  pending: number;
  open_suggestions: number;
  audit_segments: number;
  audit_total: number;
  audit_fish: number;
  partial: boolean;
  review_seconds: number;
};

/** MaxN from tracks a person confirmed. Worked out in server/tidecount/stats.py. */
export type MaxnStats = {
  maxn: number;
  maxn_t: number | null;
  species: { species: string; maxn: number; t: number | null; tracks: number }[];
  confirmed_tracks: number;
  undecided_tracks: number;
  partial: boolean;
  snapshot_maxn: number | null;
  snapshot_complete: boolean;
};

/** Shannon and Simpson diversity from each species' MaxN. Worked out in server/tidecount/stats.py. */
export type DiversityStats = {
  shannon: number | null;
  evenness: number | null;
  simpson_diversity: number | null;
  inverse_simpson: number | null;
  richness: number;
  species: { species: string; maxn: number; share: number }[];
  unidentified_maxn: number;
  undecided_tracks: number;
  partial: boolean;
};

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init);
  // A web page where data was expected means the server doesn't know this endpoint, usually
  // because it's older than this page. Say so, instead of "Unexpected token '<'".
  if ((res.headers.get("content-type") ?? "").startsWith("text/html")) {
    throw new Error("The server doesn't know this request. It may be running older code than this page: restart TideCount and reload.");
  }
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail ?? `Request failed (${res.status})`);
  }
  return res.json();
}

const json = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const api = {
  videos: () => call<Video[]>("/api/videos"),
  models: () => call<ModelOption[]>("/api/models"),
  species: () => call<SpeciesRow[]>("/api/species"),
  speciesMedia: () => call<SpeciesMediaSummary>("/api/species/media"),
  speciesProfile: (name: string) => call<SpeciesProfile>(`/api/species/${encodeURIComponent(name)}/profile`),
  obisSummary: (name: string, region: string, filter: RecordFilter = NO_FILTER) =>
    call<ObisSummary>(`/api/species/${encodeURIComponent(name)}/occurrences/summary?region=${region}${methodParams(filter)}`),
  obisCatalog: (name: string, region: string) =>
    call<ObisCatalog>(`/api/species/${encodeURIComponent(name)}/occurrences/datasets?region=${region}`),
  obisGrid: (name: string, bbox: number[], precision: number, years: YearRange, region: string, filter: RecordFilter = NO_FILTER) =>
    call<ObisGrid>(`/api/species/${encodeURIComponent(name)}/occurrences/grid?bbox=${bbox.join(",")}&precision=${precision}${yearParams(years)}${filterParams(region, filter)}`),
  obisRecords: (name: string, bbox: number[], years: YearRange, region: string, filter: RecordFilter = NO_FILTER) =>
    call<ObisRecords>(`/api/species/${encodeURIComponent(name)}/occurrences/records?bbox=${bbox.join(",")}${yearParams(years)}${filterParams(region, filter)}`),
  obisEdna: (name: string, region: string, years: YearRange) =>
    call<EdnaEvidence>(`/api/species/${encodeURIComponent(name)}/occurrences/edna?region=${region}${yearParams(years)}`),
  obisNonDetections: (name: string, region: string) =>
    call<ObisNonDetections>(`/api/species/${encodeURIComponent(name)}/occurrences/nondetections?region=${region}`),
  accuracy: () => call<{ videos: AccuracyRow[] }>("/api/accuracy"),
  compare: (id: string) => call<Comparison>(`/api/videos/${id}/compare`),
  reanalyze: (id: string, detector: string) => call<{ id: string }>(`/api/videos/${id}/reanalyze`, json("POST", { detector })),
  video: (id: string) => call<VideoDetail>(`/api/videos/${id}`),
  tracks: (id: string) => call<Track[]>(`/api/videos/${id}/tracks`),
  summary: (id: string) => call<Summary>(`/api/videos/${id}/summary`),
  maxn: (id: string) => call<MaxnStats>(`/api/videos/${id}/stats/maxn`),
  waterSites: () => call<WaterSite[]>(`/api/water/sites`),
  waterSeries: (siteId: string, measurement: string, deseason = false) =>
    call<WaterSeries>(`/api/water/sites/${siteId}/series?measurement=${encodeURIComponent(measurement)}&deseason=${deseason}`),
  fishOptions: (siteId: string) => call<FishOptions>(`/api/fish/sites/${siteId}/options`),
  fishWater: (siteId: string, metric: string, measurement: string, deseason = false) =>
    call<FishWaterComparison>(`/api/compare/sites/${siteId}?metric=${encodeURIComponent(metric)}&measurement=${encodeURIComponent(measurement)}&deseason=${deseason}`),
  fishSeries: (siteId: string, metric: string, deseason = false) =>
    call<FishSeries>(`/api/fish/sites/${siteId}/series?metric=${encodeURIComponent(metric)}&deseason=${deseason}`),
  wqiTable: (last = 7) => call<WqiTable>(`/api/wqi/table?last=${last}`),
  diversity: (id: string) => call<DiversityStats>(`/api/videos/${id}/stats/diversity`),
  /**
   * Over XHR rather than fetch, so a large file can show how much has gone. `onProgress` gets 0 to 1.
   * The station and filmed date go in the same request, so the video is filed wherever it was uploaded from.
   */
  upload: (file: File, place: Placement, detector: string, onProgress?: (share: number) => void) =>
    new Promise<{ id: string }>((resolve, reject) => {
      const form = new FormData();
      form.append("file", file);
      form.append("detector", detector);
      form.append("station_id", place.station_id);
      form.append("filmed_on", place.filmed_on);
      const xhr = new XMLHttpRequest();
      xhr.open("POST", "/api/videos");
      xhr.responseType = "json";
      xhr.upload.onprogress = (e) => { if (e.lengthComputable) onProgress?.(e.loaded / e.total); };
      xhr.onload = () => xhr.status < 300
        ? resolve(xhr.response)
        : reject(new Error(xhr.response?.detail ?? `Request failed (${xhr.status})`));
      xhr.onerror = () => reject(new Error("The upload stopped. Check the connection and try again."));
      xhr.send(form);
    }),
  importPath: (path: string, place: Placement, detector: string) => call<{ id: string }>("/api/videos/import-path", json("POST", { path, detector, ...place })),
  retry: (id: string) => call(`/api/videos/${id}/retry`, { method: "POST" }),
  decide: (trackId: number, state: string, species: string | null) => call(`/api/tracks/${trackId}/decision`, json("PUT", { state, species })),
  undo: (trackId: number) => call(`/api/tracks/${trackId}/decision`, { method: "DELETE" }),
  decideMany: (items: { track_id: number; state: Track["state"]; species: string | null }[]) => call("/api/tracks/decisions", json("PUT", { items })),
  merge: (ids: number[]) => call<{ id: number }>("/api/tracks/merge", json("POST", { ids })),
  unmerge: (trackId: number) => call<{ ids: number[] }>(`/api/tracks/${trackId}/unmerge`, { method: "POST" }),
  addFish: (id: string, t: number, box: { x: number; y: number; w: number; h: number }) =>
    call<{ id: number; points: number; seconds: number }>(`/api/videos/${id}/tracks`, json("POST", { t, ...box })),
  frameBoxes: (id: string, t: number) => call<{ t: number; threshold: number; boxes: FrameBox[] }>(`/api/videos/${id}/frame-boxes?t=${t}`),
  removeFish: (trackId: number) => call(`/api/tracks/${trackId}`, { method: "DELETE" }),
  segmentStatus: (segmentId: number, status: string) => call(`/api/segments/${segmentId}/status`, json("POST", { status })),
  event: (id: string, type: string, payload = {}) => call(`/api/videos/${id}/events`, json("POST", { type, payload })),
  startSchool: (id: string, t: number) => call<SchoolCount>(`/api/videos/${id}/school-counts`, json("POST", { t })),
  saveSchool: (countId: number, dots: Dot[], removed: number) => call(`/api/school-counts/${countId}`, json("PUT", { dots, removed })),
};

/** Where and when a video was filmed. Blank strings mean not set. */
export type Placement = { station_id: string; filmed_on: string };
export type SurveyKind = "sites" | "transects" | "stations";

/** The survey structure. The rules, like unique names and no deleting filed footage, are checked on the server. */
export const surveyApi = {
  /** Shaped like the web's SurveyData, so it can be used as it comes. */
  tree: () => call<SurveyTree>("/api/surveys"),
  add: (kind: SurveyKind, item: Record<string, unknown>) => call<{ id: string }>(`/api/surveys/${kind}`, json("POST", item)),
  change: (kind: SurveyKind, id: string, patch: Record<string, unknown>) => call(`/api/surveys/${kind}/${id}`, json("PATCH", patch)),
  remove: (kind: SurveyKind, id: string) => call(`/api/surveys/${kind}/${id}`, { method: "DELETE" }),
  /** A field left out stays as it is. */
  place: (videoId: string, place: Partial<Placement>) => call(`/api/videos/${videoId}/place`, json("PUT", place)),
  placeMany: (stationByVideo: Record<string, string>) => call("/api/videos/places", json("PUT", { items: stationByVideo })),
};

export type SurveyTree = {
  sites: { id: string; name: string; coordinates: string; flag: "" | "treatment" | "reference"; archived: boolean }[];
  transects: { id: string; siteId: string; name: string; archived: boolean }[];
  stations: { id: string; transectId: string; name: string; coordinates: string; depth: string; archived: boolean }[];
  places: Record<string, string>;
  filmedOn: Record<string, string>;
};

export function clock(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = String(s % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${sec}` : `${m}:${sec}`;
}

export type SnapshotStats = {
  frames_total: number;
  frames_checked: number;
  frames_done: number;
  could_not_see: number;
  peak_total: number;
  peak_checked: number;
  peak_could_not_see: number;
  mean_count: number | null;
  invertebrate_mean: number | null;
  species_seen: string[];
  largest_count: number | null;
  largest_label: string;
  complete: boolean;
};

export type SnapshotStatus = "" | "checked" | "could_not_see";
/** `rank` is the order frames are offered in when a person counts on their own. */
export type SnapshotRow = { id: number; kind: "snapshot" | "peak"; t: number; status: SnapshotStatus; total: number | null; blind?: number; rank: number };
export type SpeciesCount = { name: string; n: number };
/** What the procedure records at each sub-sample point, beyond the fish dots. */
export type FrameRecord = { invertebrates: number; species: SpeciesCount[]; visibility: string; comment: string };
export type SnapshotFrame = Omit<FrameRecord, "invertebrates"> & {
  id: number; kind: "snapshot" | "peak"; t: number; status: SnapshotStatus; dots: Dot[]; model: string; ai_shown: boolean;
  invertebrates: number | null;
};
/** The analysis window and the procedure's values. `juveniles` is 1, 0 or null when nobody has said. */
export type Protocol = {
  start: number; end: number; suggested: number; chosen: boolean; every_s: number; context_s: number;
  visibility: string; juveniles: number | null; visibility_options: string[];
};
export type SnapshotList = {
  video: { id: string; name: string; duration: number; width: number; height: number };
  frames: SnapshotRow[];
  stats: SnapshotStats;
  protocol: Protocol;
};

export const snapshotApi = {
  list: (id: string) => call<SnapshotList>(`/api/videos/${id}/snapshots`),
  frame: (frameId: number, blind = false) => call<SnapshotFrame>(`/api/snapshot-frames/${frameId}${blind ? "?blind=true" : ""}`),
  image: (frameId: number) => `/api/snapshot-frames/${frameId}/image`,
  clip: (frameId: number) => `/api/snapshot-frames/${frameId}/clip`,
  save: (frameId: number, status: SnapshotStatus, dots: Dot[], aiHidden: boolean, blind: boolean, record: FrameRecord) =>
    call<{ stats: SnapshotStats }>(`/api/snapshot-frames/${frameId}`, json("PUT", { status, dots, ai_hidden: aiHidden, blind, ...record })),
};

/** A water sampling site. From server/tidecount/water.py. */
export type WaterSite = {
  site_id: string;
  site_name: string;
  lat: number;
  lon: number;
  first_date: string;
  last_date: string;
  visits: number;
};

/** One measurement at one site over time. */
export type WaterSeries = {
  site_id: string;
  measurement: string;
  unit: string;
  points: { date: string; value: number }[];
};

/** What a fish chart at a site can show: overall measures, then each species. From server/tidecount/trends.py. */
export type FishOptions = { metrics: { key: string; label: string }[]; species: string[]; videos: VideoLinks };

/** Which videos give fish counts at a water site, and why the others don't. From server/tidecount/link.py. */
export type VideoLinks = {
  match_km: number;
  linked: { video: string; site_id: string; site_name: string; date: string; km: number }[];
  not_linked: { video: string; reason: string }[];
};

/** A standardized line: `z` is how many standard deviations each point is from the line's own average. */
export type ZLine = { label: string; unit: string; points: { date: string; value: number; z: number }[] };

/** A fish measure and a water measurement on one shared scale, with their Spearman correlation. */
export type FishWaterComparison = {
  fish: ZLine;
  water: ZLine;
  pairs: number;
  max_gap_days: number;
  spearman: number | null;
  p_value: number | null;
  strength: string;
  demo: boolean;
};

/** One fish measure over time at a site. `demo` is true when any of it is made-up demo data. */
export type FishSeries = {
  site_id: string;
  metric: string;
  label: string;
  unit: string;
  points: { date: string; value: number }[];
  demo: boolean;
  from_videos: boolean;
};



/** The Water Quality Index table, like Coastal Action's report card. From server/tidecount/wqi.py. */
export type WqiTable = {
  years: number[];
  sites: {
    site_id: string;
    site_name: string;
    salty: boolean;
    scores: { year: number; wqi: number | null; rating: string }[];
    fish: {
      year: number; surveys: number; fish: number; per_survey: number; species: number;
      shannon: number | null; most_common: string; demo: boolean;
    }[];
  }[];
};