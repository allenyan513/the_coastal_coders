/** False on the public demo, where uploads go to the server and not to this computer. */
export const isLocal = ["localhost", "127.0.0.1", "[::1]"].includes(window.location.hostname);

export type Video = {
  id: string;
  name: string;
  site: string;
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

export type AccuracyRow = {
  id: string; name: string; site: string; detector: string; model: string;
  frames_total: number; frames_blind: number; frames_assisted: number; frames_could_not_see: number;
  fish: number; found: number; missed: number; extra_boxes: number;
};

export type Dot = { x: number; y: number; source: "ai" | "user" };
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
  accuracy: () => call<{ videos: AccuracyRow[] }>("/api/accuracy"),
  compare: (id: string) => call<Comparison>(`/api/videos/${id}/compare`),
  reanalyze: (id: string, detector: string) => call<{ id: string }>(`/api/videos/${id}/reanalyze`, json("POST", { detector })),
  video: (id: string) => call<VideoDetail>(`/api/videos/${id}`),
  tracks: (id: string) => call<Track[]>(`/api/videos/${id}/tracks`),
  summary: (id: string) => call<Summary>(`/api/videos/${id}/summary`),
  maxn: (id: string) => call<MaxnStats>(`/api/videos/${id}/stats/maxn`),
  diversity: (id: string) => call<DiversityStats>(`/api/videos/${id}/stats/diversity`),
  upload: (file: File, site: string, detector: string) => {
    const form = new FormData();
    form.append("file", file);
    form.append("site", site);
    form.append("detector", detector);
    return call<{ id: string }>("/api/videos", { method: "POST", body: form });
  },
  importPath: (path: string, site: string, detector: string) => call<{ id: string }>("/api/videos/import-path", json("POST", { path, site, detector })),
  retry: (id: string) => call(`/api/videos/${id}/retry`, { method: "POST" }),
  decide: (trackId: number, state: string, species: string | null) => call(`/api/tracks/${trackId}/decision`, json("PUT", { state, species })),
  undo: (trackId: number) => call(`/api/tracks/${trackId}/decision`, { method: "DELETE" }),
  decideMany: (items: { track_id: number; state: Track["state"]; species: string | null }[]) => call("/api/tracks/decisions", json("PUT", { items })),
  merge: (ids: number[]) => call<{ id: number }>("/api/tracks/merge", json("POST", { ids })),
  unmerge: (trackId: number) => call<{ ids: number[] }>(`/api/tracks/${trackId}/unmerge`, { method: "POST" }),
  addFish: (id: string, t: number, box: { x: number; y: number; w: number; h: number }) =>
    call<{ id: number; points: number; seconds: number }>(`/api/videos/${id}/tracks`, json("POST", { t, ...box })),
  removeFish: (trackId: number) => call(`/api/tracks/${trackId}`, { method: "DELETE" }),
  segmentStatus: (segmentId: number, status: string) => call(`/api/segments/${segmentId}/status`, json("POST", { status })),
  event: (id: string, type: string, payload = {}) => call(`/api/videos/${id}/events`, json("POST", { type, payload })),
  startSchool: (id: string, t: number) => call<SchoolCount>(`/api/videos/${id}/school-counts`, json("POST", { t })),
  saveSchool: (countId: number, dots: Dot[], removed: number) => call(`/api/school-counts/${countId}`, json("PUT", { dots, removed })),
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
