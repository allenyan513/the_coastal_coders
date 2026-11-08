import { Summary, Video } from "./api";
import { NO_DATE, season, Site, Station, SurveyData, Transect } from "./surveyStore";

/** One video's results, for the run with the most points counted. */
export type VideoResult = { video: Video; summary: Summary; maxn: number | null };

/** What one station shows for one season. MeanCount and MaxN only come from fully counted videos. */
export type Cell = {
  stationId: string;
  season: string;
  videos: number;
  finished: number;
  mean: number | null;
  maxn: number | null;
  species: string[];
  links: { id: string; name: string }[];
};

const SEASON_ORDER = ["Spring", "Summer", "Fall", "Winter"];
const seasonKey = (name: string) => {
  const [word, year] = name.split(" ");
  return name === NO_DATE ? Infinity : Number(year) * 10 + SEASON_ORDER.indexOf(word);
};
export const bySeason = (a: string, b: string) => seasonKey(a) - seasonKey(b);

/**
 * One cell per station and season. How Coastal Action combines several videos of a station in a season
 * is still an open question, so this averages their MeanCounts and takes the highest MaxN.
 */
export function buildCells(results: VideoResult[], data: SurveyData): Cell[] {
  const cells = new Map<string, Cell>();
  results.forEach(({ video, summary, maxn }) => {
    const root = video.source_id || video.id;
    const stationId = data.places[root];
    if (!stationId) return;
    const name = data.filmedOn[root] ? season(data.filmedOn[root]) : NO_DATE;
    const key = `${stationId}|${name}`;
    const cell = cells.get(key) ?? { stationId, season: name, videos: 0, finished: 0, mean: null, maxn: null, species: [], links: [] };
    const { frames_done: done, frames_total: total, mean_count: mean } = summary.snapshots;
    cell.videos += 1;
    cell.links.push({ id: video.id, name: video.name });
    if (total > 0 && done >= total && mean !== null) {
      cell.mean = ((cell.mean ?? 0) * cell.finished + mean) / (cell.finished + 1);
      cell.finished += 1;
      cell.maxn = maxn === null ? cell.maxn : Math.max(cell.maxn ?? 0, maxn);
      cell.species = [...new Set([...cell.species, ...summary.species_observed])];
    }
    cells.set(key, cell);
  });
  return [...cells.values()];
}

const FISH = ["Cunner", "Pollock", "Mummichog", "Atlantic silverside", "Winter flounder", "Green crab", "Rock gunnel"];

/** A site with its stations, shaped like activeTree() in surveyStore.ts. */
export type SampleSite = { site: Site; stations: { station: Station; transect: Transect; label: string }[] };

/**
 * The sample structure the Station report shows before any station is counted. The place names are real,
 * but these transects, stations, coordinates and depths are made up. Each transect starts at a point and
 * runs out from the shore in even steps, four stations long. One station has no coordinates, to show how
 * the map lists stations it can't place.
 */
const SAMPLE_LAYOUT = [
  {
    site: { id: "mahone-bay", name: "Mahone Bay Living Shoreline", flag: "treatment" as const },
    step: [0.000605, 0.000257],
    transects: [["t1", 44.44553, -64.36564], ["t2", 44.44482, -64.36235], ["t3", 44.44415, -64.35907]] as const,
  },
  {
    site: { id: "lahave", name: "LaHave River Estuary", flag: "reference" as const },
    step: [-0.0001, -0.00228],
    transects: [["l1", 44.3552, -64.43837], ["l2", 44.35277, -64.43837], ["l3", 44.35034, -64.43894]] as const,
  },
];
const UNPLACED = "l3-s4";

export const SAMPLE_TREE: SampleSite[] = SAMPLE_LAYOUT.map(({ site, step, transects }) => ({
  site: { ...site, coordinates: "", archived: false },
  stations: transects.flatMap(([id, lat, lon], t) => {
    const transect: Transect = { id, siteId: site.id, name: `T${t + 1}`, archived: false };
    return [1, 2, 3, 4].map((n) => {
      const stationId = `${id}-s${n}`;
      const at = [lat + step[0] * (n - 1), lon + step[1] * (n - 1)];
      const station: Station = {
        id: stationId, transectId: id, name: `STAT${n}`, archived: false,
        coordinates: stationId === UNPLACED ? "" : `${at[0].toFixed(5)}, ${at[1].toFixed(5)}`,
        depth: (1.2 + n * 0.9 + t * 0.3).toFixed(1),
      };
      return { station, transect, label: `${transect.name} · ${station.name}` };
    });
  }),
}));

/** Made-up numbers for the sample structure. They show the page's shape and say nothing about these places. */
function sampleCell(stationId: string, name: string, mean: number, maxn: number, kinds: number): Cell {
  return { stationId, season: name, videos: 1, finished: 1, mean, maxn, species: FISH.slice(0, kinds), links: [] };
}

// The same made-up numbers on every visit: a fixed pseudo-random sequence rather than Math.random.
const wobble = (k: number) => { const v = Math.sin(k * 12.9898 + 4.1) * 43758.5453; return v - Math.floor(v); };

export const SAMPLE_CELLS: Cell[] = SAMPLE_TREE.flatMap((s) => s.stations).flatMap(({ station }, k) => {
  const fall = 1.5 + wobble(k) * 5;
  const spring = Math.max(0.8, fall * (0.7 + wobble(k + 50) * 0.75));
  const kinds = (mean: number) => Math.min(FISH.length, 2 + Math.round(mean / 2));
  return [
    sampleCell(station.id, "Fall 2025", Number(fall.toFixed(1)), Math.round(fall * 2.2 + wobble(k + 90) * 3), kinds(fall)),
    sampleCell(station.id, "Spring 2026", Number(spring.toFixed(1)), Math.round(spring * 2.2 + wobble(k + 130) * 3), kinds(spring)),
  ];
});
