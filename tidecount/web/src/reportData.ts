import { Summary, Video } from "./api";
import { NO_DATE, season, SurveyData } from "./surveyStore";

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

/** Made-up numbers for the sample structure. They show the page's shape and say nothing about these places. */
function sampleCell(stationId: string, name: string, mean: number, maxn: number, kinds: number): Cell {
  return { stationId, season: name, videos: 1, finished: 1, mean, maxn, species: FISH.slice(0, kinds), links: [] };
}

export const SAMPLE_CELLS: Cell[] = [
  ["t1-s1", 3.0, 7, 3, 3.7, 9, 4],
  ["t1-s2", 4.0, 9, 4, 3.5, 8, 4],
  ["t1-s3", 2.0, 5, 3, 2.8, 7, 4],
  ["t2-s1", 5.0, 12, 5, 6.0, 14, 6],
  ["t2-s2", 1.5, 4, 2, 2.2, 6, 3],
  ["t2-s3", 3.5, 8, 4, 4.3, 10, 5],
  ["l1-s1", 2.5, 6, 3, 2.6, 6, 3],
  ["l1-s2", 3.0, 7, 3, 2.9, 7, 3],
  ["l1-s3", 1.8, 4, 2, 1.9, 5, 3],
  ["l2-s1", 2.2, 5, 3, 2.4, 6, 3],
  ["l2-s2", 3.4, 8, 4, 3.3, 8, 4],
  ["l2-s3", 2.0, 5, 2, 2.2, 5, 3],
].flatMap(([id, fallMean, fallMax, fallKinds, springMean, springMax, springKinds]) => [
  sampleCell(id as string, "Fall 2025", fallMean as number, fallMax as number, fallKinds as number),
  sampleCell(id as string, "Spring 2026", springMean as number, springMax as number, springKinds as number),
]);
