import "leaflet/dist/leaflet.css";

import L from "leaflet";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  api, EdnaEvidence, EdnaPoint, isFiltered, matchesFilter, NO_FILTER, ObisCatalog, ObisCell, ObisGrid, ObisNonDetections,
  ObisRecords, ObisSummary, RecordFilter, RecordMethodFilter, SpeciesNames,
} from "./api";
import YearRangeSlider from "./YearRangeSlider";
import { ALL_YEARS, decadePresets, describeRange, isAllYears, makeScale, sameRange, yearInRange, type YearRange } from "./yearRange";

/** Starting views. The map still pans and zooms anywhere, and refetches for what's on screen. */
type RegionKey = "nova-scotia" | "atlantic-canada" | "north-atlantic" | "world";
const REGIONS: { key: RegionKey; label: string; bounds: L.LatLngBoundsLiteral }[] = [
  { key: "nova-scotia", label: "Nova Scotia", bounds: [[43.2, -66.6], [47.2, -59.6]] },
  { key: "atlantic-canada", label: "Atlantic Canada", bounds: [[40.5, -70], [53, -50]] },
  { key: "north-atlantic", label: "North Atlantic", bounds: [[24, -82], [75, 20]] },
  { key: "world", label: "World", bounds: [[-60, -180], [80, 180]] },
];
// The year range moves one year at a time from 1950; the left end is "earlier" and takes every older record.
const THIS_YEAR = new Date().getFullYear();
const YEARS = makeScale(1950, THIS_YEAR);
const YEAR_PRESETS = decadePresets(YEARS, THIS_YEAR);
// The map opens on recent records. Whatever period is chosen then stays for the session, for every
// fish and tab, until changed (All years is one click away).
const DEFAULT_YEARS: YearRange = { from: 2023, to: null };
let sessionYears: YearRange = DEFAULT_YEARS;

// OBIS grid precision for a zoom level, and how far to round a view out so nearby views share a cache entry.
const precisionFor = (zoom: number) => (zoom <= 2 ? 2 : zoom <= 4 ? 3 : zoom <= 6 ? 4 : zoom <= 8 ? 5 : 6);
const SNAP: Record<number, number> = { 2: 180, 3: 20, 4: 5, 5: 1, 6: 0.25 };
const MAX_AREA: Record<number, number> = { 2: Infinity, 3: Infinity, 4: 1500, 5: 60, 6: 6 };

// Record counts run from 1 to hundreds of thousands, so colour by order of magnitude: five steps,
// light to dark, in whichever palette is chosen.
const BINS = [
  { min: 1, label: "1–9" },
  { min: 10, label: "10–99" },
  { min: 100, label: "100–999" },
  { min: 1000, label: "1k–10k" },
  { min: 10000, label: "10k+" },
];
// Grid palettes. Each runs from a light step that still stands out from the pale sea of the basemap
// to a dark one. Blue is the original. A palette that would look like the eDNA dots (teal) or the
// net-survey rings (orange) moves those markers to another colour, so the three never blur together.
const DEFAULT_EDNA = "#0e7c6b";
const DEFAULT_ND = "#c4560a";
type Palette = { label: string; colors: string[]; edna?: string; nd?: string };
const PALETTES = {
  blue: { label: "Blue", colors: ["#bfd3ff", "#7fa6ff", "#3f78ff", "#1f4fd1", "#13308a"] },
  orange: { label: "Orange", colors: ["#fdc58a", "#fb9a4b", "#f06a12", "#c74a02", "#7f2704"], nd: "#1e3a8a" },
  teal: { label: "Teal", colors: ["#9fe3dc", "#4cc5bb", "#13a094", "#0b736b", "#05433f"], edna: "#7b2d8e" },
  purple: { label: "Purple", colors: ["#d6c2ff", "#ad86f2", "#8550dc", "#5f25b3", "#360a72"] },
  magenta: { label: "Magenta", colors: ["#ffc1e3", "#ff7cc4", "#e8329b", "#b3106d", "#6b0441"] },
} satisfies Record<string, Palette>;
type PaletteKey = keyof typeof PALETTES;
const PALETTE_STORE = "tideflow.speciesMap.gridPalette";
// Kept in this browser, so it holds for every fish and every visit.
function storedPalette(): PaletteKey {
  try {
    const v = window.localStorage.getItem(PALETTE_STORE);
    return v && v in PALETTES ? (v as PaletteKey) : "blue";
  } catch {
    return "blue"; // storage can be blocked; the original colours still work
  }
}
const markerColors = (p: PaletteKey) => {
  const pal: Palette = PALETTES[p];
  return { edna: pal.edna ?? DEFAULT_EDNA, nd: pal.nd ?? DEFAULT_ND };
};
// Non-detection sites, by sampling method. Rings, so they never read as record shading. Their
// colour comes from markerColors, through the --nd variable on the map.
const ND_STYLE: Record<string, { label: string }> = {
  capture: { label: "Net or trawl: not caught" },
};
// eDNA water-sample sites, apart from both the record cells and the net rings: a solid dot where DNA
// of the fish was found on at least one date, a dashed ring where it never was. Colour: --edna.
const EDNA_COLOR = "var(--edna)";
const colorFor = (n: number, colors: string[]) => colors[BINS.reduce((at, b, i) => (n >= b.min ? i : at), 0)];
const key = (c: ObisCell) => c.slice(0, 4).join(",");
const fmt = (n: number) => n.toLocaleString("en-CA");
const coord = (lat: number, lon: number) => `${Math.abs(lat).toFixed(2)}°${lat >= 0 ? "N" : "S"} ${Math.abs(lon).toFixed(2)}°${lon >= 0 ? "E" : "W"}`;

function snappedView(map: L.Map): { bbox: number[]; precision: number } {
  let precision = precisionFor(map.getZoom());
  const b = map.getBounds();
  for (;;) {
    const step = SNAP[precision];
    const w = Math.max(-180, Math.floor(b.getWest() / step) * step);
    const e = Math.min(180, Math.ceil(b.getEast() / step) * step);
    const s = Math.max(-90, Math.floor(b.getSouth() / step) * step);
    const n = Math.min(90, Math.ceil(b.getNorth() / step) * step);
    if ((e - w) * (n - s) <= MAX_AREA[precision] || precision === 2) return { bbox: [w, s, e, n], precision };
    precision -= 1; // the view is too large for this detail, so ask for coarser cells
  }
}

type Props = { species: string; names: SpeciesNames | null };

/** Each fish's map as it was last left, for this session: the choices, and where the map was. */
// (The year range is not per fish: it is kept for the session, see sessionYears.)
type Remembered = { region: RegionKey; filter: RecordFilter; view?: { center: [number, number]; zoom: number } };
const remembered = new Map<string, Remembered>();

/**
 * Real OBIS occurrence records for one species, counted in grid cells. Shaded cells hold records,
 * and unshaded water has no records shared with OBIS, which is not evidence of absence. Surveys
 * that didn't detect the fish are summarised separately, by site and date, on request.
 */
export default function OccurrenceMap({ species, names }: Props) {
  const box = useRef<HTMLDivElement>(null);
  const mapRef = useRef<L.Map | null>(null);
  const layerRef = useRef<L.LayerGroup | null>(null);
  const ndLayerRef = useRef<L.LayerGroup | null>(null);
  const ednaLayerRef = useRef<L.LayerGroup | null>(null);
  const selectedRef = useRef<L.Rectangle | null>(null);
  const reqRef = useRef(0);
  const shownRef = useRef(""); // the request whose grid is on screen
  const pendingRef = useRef(""); // and the one on its way, if any
  const loadingRef = useRef(false);
  // Opening this fish's map again (Expand from the drawer, or back from another tab) picks up where it was left.
  const [saved] = useState(() => remembered.get(species));
  const [region, setRegion] = useState<RegionKey>(saved?.region ?? "atlantic-canada");
  const [years, setYears] = useState<YearRange>(sessionYears);
  useEffect(() => { sessionYears = years; }, [years.from, years.to]);
  const [palette, setPaletteState] = useState<PaletteKey>(storedPalette);
  const setPalette = (p: PaletteKey) => {
    setPaletteState(p);
    try { window.localStorage.setItem(PALETTE_STORE, p); } catch { /* not saved; still applies now */ }
  };
  const colors = PALETTES[palette].colors;
  const marks = markerColors(palette);
  // The method and dataset filter belongs to one species, and a dataset to one region's list, so it
  // is kept with them: another fish starts unfiltered, and another region keeps only the method.
  const [chosen, setChosen] = useState({ species, region, filter: saved?.filter ?? NO_FILTER });
  const filter: RecordFilter = chosen.species !== species ? NO_FILTER
    : chosen.region !== region ? { method: chosen.filter.method, dataset: null } : chosen.filter;
  const setFilter = (f: RecordFilter) => setChosen({ species, region, filter: f });
  const filtered = isFiltered(filter);
  // The region's dataset list, loaded only once the filter section is opened (see RecordFilters).
  const [loadedCatalog, setCatalog] = useState<ObisCatalog | null>(null);
  const catalog = loadedCatalog && loadedCatalog.species === species && loadedCatalog.region === region ? loadedCatalog : null;
  const [grid, setGrid] = useState<ObisGrid | null>(null);
  const [gridError, setGridError] = useState("");
  const [loading, setLoading] = useState(false);
  const [summary, setSummary] = useState<ObisSummary | null>(null);
  const [summaryError, setSummaryError] = useState("");
  const [cell, setCell] = useState<{ bbox: number[]; present: number } | null>(null);
  const [recs, setRecs] = useState<ObisRecords | null>(null);
  const [recsError, setRecsError] = useState("");
  const [shown, setShown] = useState(15);
  const [ndPoints, setNdPoints] = useState<ObisNonDetections["points"] | null>(null);
  const [ednaPoints, setEdnaPoints] = useState<EdnaPoint[] | null>(null);

  // The map, made once. Canvas draws thousands of cells far faster than one SVG element each.
  useEffect(() => {
    if (!box.current) return;
    const map = L.map(box.current, { preferCanvas: true, worldCopyJump: true, minZoom: 1, maxZoom: 11, zoomSnap: 0.5 });
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      className: "basemap",
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors · Records: <a href="https://obis.org">OBIS</a>',
    }).addTo(map);
    layerRef.current = L.layerGroup().addTo(map);
    ndLayerRef.current = L.layerGroup().addTo(map);
    ednaLayerRef.current = L.layerGroup().addTo(map);
    if (saved?.view) map.setView(saved.view.center, saved.view.zoom, { animate: false });
    else map.fitBounds(REGIONS.find((r) => r.key === (saved?.region ?? "atlantic-canada"))!.bounds);
    mapRef.current = map;
    const ro = new ResizeObserver(() => map.invalidateSize());
    ro.observe(box.current);
    return () => {
      ro.disconnect();
      mapRef.current = null;
      // Leaving the tab mid-zoom (say, right after picking a region) used to throw
      // "Cannot read properties of undefined (reading '_leaflet_pos')": Leaflet finishes a zoom on a
      // timer, and that timer ran after remove() had deleted the panes. So let the zoom end first.
      map.stop();
      let removed = false;
      const remove = () => { if (!removed) { removed = true; map.off(); map.remove(); } };
      if ((map as unknown as { _animatingZoom?: boolean })._animatingZoom) {
        map.once("zoomend", remove);
        window.setTimeout(remove, 600); // a zoom animation lasts 250 ms; don't wait forever
      } else {
        remove();
      }
    };
  }, []);

  const load = useCallback(() => {
    const map = mapRef.current;
    if (!map) return;
    const { bbox, precision } = snappedView(map);
    // Resizing the map (expanding the drawer, turning a phone) fires moveend; when the rounded view
    // is the one already on screen there is nothing new to ask for.
    const ask = `${species}|${bbox.join(",")}|${precision}|${years.from}|${years.to}|${filtered ? region : ""}|${filter.method}|${filter.dataset}`;
    if (ask === shownRef.current || (ask === pendingRef.current && loadingRef.current)) return;
    pendingRef.current = ask;
    loadingRef.current = true;
    const id = ++reqRef.current;
    setLoading(true); setGridError("");
    api.obisGrid(species, bbox, precision, years, region, filter)
      .then((g) => { if (id === reqRef.current) { setGrid(g); shownRef.current = ask; } })
      .catch((e) => { if (id === reqRef.current) { setGridError(e.message); shownRef.current = ""; } })
      .finally(() => { if (id === reqRef.current) { setLoading(false); loadingRef.current = false; } });
    // The region only matters to a filtered map, so an unfiltered one doesn't refetch when it changes.
  }, [species, years, filter.method, filter.dataset, filtered ? region : ""]);

  // Remember the choices and where the map is, for the next time this fish's map opens.
  useEffect(() => {
    remembered.set(species, { ...remembered.get(species), region, filter });
  }, [species, region, filter.method, filter.dataset]);
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const save = () => {
      const c = map.getCenter();
      const was = remembered.get(species);
      if (was) remembered.set(species, { ...was, view: { center: [c.lat, c.lng], zoom: map.getZoom() } });
    };
    map.on("moveend", save);
    return () => { map.off("moveend", save); };
  }, [species]);

  // Refetch when the view settles, with a short wait so a drag doesn't send a request per frame.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    let timer = 0;
    const onMove = () => { window.clearTimeout(timer); timer = window.setTimeout(load, 350); };
    map.on("moveend", onMove);
    load();
    return () => { map.off("moveend", onMove); window.clearTimeout(timer); };
  }, [load]);

  // A new species, year range or filter starts over: no cell picked, same view.
  useEffect(() => { setCell(null); setRecs(null); }, [species, years, filter.method, filter.dataset]);
  // Non-detections belong to one species and region, so a change hides them.
  useEffect(() => { setNdPoints(null); setEdnaPoints(null); }, [species, region]);

  useEffect(() => {
    let live = true;
    setSummary(null); setSummaryError("");
    api.obisSummary(species, region, filter).then((s) => live && setSummary(s)).catch((e) => live && setSummaryError(e.message));
    return () => { live = false; };
  }, [species, region, filter.method, filter.dataset]);

  const pick = useCallback((c: ObisCell) => {
    setCell({ bbox: c.slice(0, 4), present: c[4] });
    setShown(15);
  }, []);

  // Draw the record cells.
  useEffect(() => {
    const layer = layerRef.current;
    if (!layer) return;
    layer.clearLayers();
    selectedRef.current = null;
    if (!grid) return;
    for (const c of grid.present) {
      L.rectangle([[c[1], c[0]], [c[3], c[2]]], { color: colorFor(c[4], colors), weight: 0.6, fillColor: colorFor(c[4], colors), fillOpacity: 0.72 })
        .bindTooltip(`${fmt(c[4])} occurrence record${c[4] === 1 ? "" : "s"}`, { sticky: true })
        .on("click", () => pick(c))
        .addTo(layer);
    }
    // Canvas draws in the order layers were added, so cells redrawn after a pan would cover the survey markers.
    for (const g of [ndLayerRef.current, ednaLayerRef.current]) g?.eachLayer((l) => (l as L.Path).bringToFront());
  }, [grid, pick, palette]); // a new palette repaints the cells already here; it never asks OBIS

  // eDNA sites on their own layer: solid where the fish's DNA was found at least once, a dashed ring where it never was.
  useEffect(() => {
    const layer = ednaLayerRef.current;
    if (!layer) return;
    layer.clearLayers();
    for (const p of ednaPoints ?? []) {
      const hit = p.detected > 0;
      const when = p.first && p.last && p.first !== p.last ? `${p.first} to ${p.last}` : p.first ?? "date not given";
      const text = `eDNA sample site · ${p.detected} date${p.detected === 1 ? "" : "s"} with DNA found, ${p.not_detected} not detected · ${when}`;
      L.circleMarker([p.lat, p.lon], hit
        ? { radius: 6, color: "#fff", weight: 1.5, fillColor: marks.edna, fillOpacity: 0.95 }
        : { radius: 6, color: marks.edna, weight: 2, dashArray: "3 3", fillColor: "#fff", fillOpacity: 0.6 })
        .bindTooltip(text, { sticky: true })
        .bindPopup(text)
        .addTo(layer);
    }
  }, [ednaPoints, marks.edna]);

  // Draw non-detection sites on their own layer, above the cells, only when asked for.
  useEffect(() => {
    const layer = ndLayerRef.current;
    if (!layer) return;
    layer.clearLayers();
    for (const p of ndPoints ?? []) {
      const style = ND_STYLE[p.method];
      if (!style) continue;
      const when = p.first && p.last && p.first !== p.last ? `${p.first} to ${p.last}` : p.first ?? "date not given";
      L.circleMarker([p.lat, p.lon], { radius: 5, color: marks.nd, weight: 2, fillColor: "#fff", fillOpacity: 0.7 })
        .bindTooltip(`${style.label} · ${p.dates} date${p.dates === 1 ? "" : "s"} · ${when}`, { sticky: true })
        .addTo(layer);
    }
  }, [ndPoints, marks.nd]);

  // Outline the picked cell. Redrawn after the cells are, since a pan clears the layer.
  useEffect(() => {
    selectedRef.current?.remove();
    selectedRef.current = null;
    if (!cell || !layerRef.current) return;
    const [w, s, e, n] = cell.bbox;
    selectedRef.current = L.rectangle([[s, w], [n, e]], { color: "#101828", weight: 2.5, fill: false, interactive: false }).addTo(layerRef.current);
  }, [cell, grid]);

  // List the picked cell's records. Panning doesn't change the cell, so it doesn't refetch.
  useEffect(() => {
    if (!cell) return;
    const [w, s, e, n] = cell.bbox;
    if ((e - w) * (n - s) > 30) { setRecs(null); setRecsError("This cell is too large to list. Zoom in and pick a smaller one."); return; }
    let live = true;
    setRecs(null); setRecsError("");
    api.obisRecords(species, cell.bbox, years, region, filter).then((r) => live && setRecs(r)).catch((err) => live && setRecsError(err.message));
    return () => { live = false; };
  }, [cell, species, years]); // a new filter clears the cell above, so it isn't listed here

  const goTo = (k: RegionKey) => {
    setRegion(k);
    mapRef.current?.fitBounds(REGIONS.find((r) => r.key === k)!.bounds);
  };

  const busiest = (grid?.present ?? []).slice(0, 5);
  const inView = grid ? grid.present.reduce((t, c) => t + c[4], 0) : 0;
  const freshwater = names && names.is_freshwater && !names.is_marine && !names.is_brackish;
  const regionLabel = REGIONS.find((r) => r.key === region)!.label;

  return (
    <div className="stack omap" style={{ gap: 12, "--edna": marks.edna, "--nd": marks.nd } as React.CSSProperties}>
      {/* Two groups that are invisible to the layout in the normal drawer (display: contents) and
          become the map column and the evidence column in the expanded one. Nothing moves in the
          React tree, so expanding never remounts the map. */}
      <div className="omap-main">
      <div className="row map-controls">
        <div className="row" role="group" aria-label="Region">
          {REGIONS.map((r) => (
            <button key={r.key} className="chip" aria-pressed={region === r.key} onClick={() => goTo(r.key)}>{r.label}</button>
          ))}
        </div>
      </div>
      <div className="map-controls map-filters">
        <YearRangeSlider
          scale={YEARS} value={years} presets={YEAR_PRESETS} label="Years shown on the map"
          onCommit={(r) => setYears((old) => (sameRange(old, r) ? old : r))}
        />
        <RecordFilters species={species} region={region} regionLabel={regionLabel} filter={filter} onChange={setFilter} catalog={catalog} onCatalog={setCatalog} />
      </div>

      <ObisTotals summary={summary && matchesFilter(summary.filter, filter) ? summary : null} error={summaryError} years={years} filterLabel={filtered ? describeFilter(filter, catalog) : ""} onAllYears={() => setYears(ALL_YEARS)} />

      <div className="map-wrap">
        <div ref={box} className="map" role="region" aria-label={`Map of OBIS occurrence records for ${species}`} />
        {loading && <span className="map-badge">Loading records…</span>}
        {!loading && grid && !grid.present.length && !gridError && (
          <div className="map-empty">
            <b>No OBIS occurrence records in this view{isAllYears(years) ? "" : `, ${describeRange(years)}`}{filtered ? `, ${describeFilter(filter, catalog)}` : ""}</b>
            {isAllYears(years) ? (
              <span>That means no record has been shared with OBIS here. It does not mean the fish is absent.</span>
            ) : (
              <span>Older records may still be available: this only covers {describeRange(years)}. No shared record is not evidence that the fish is absent.</span>
            )}
            <div className="row">
              {!isAllYears(years) && <button className="btn" onClick={() => setYears(ALL_YEARS)}>Show all years</button>}
              {region !== "world" && <button className="btn" onClick={() => goTo("world")}>Show the world</button>}
            </div>
          </div>
        )}
        {gridError && (
          <div className="map-empty">
            <b>Couldn't load OBIS records</b>
            <span>{gridError}</span>
            <button className="btn" onClick={load}>Try again</button>
          </div>
        )}
      </div>

      <div className="legend" aria-label="Map legend">
        <span className="meta">Occurrence records per cell:</span>
        {BINS.map((b, i) => <span key={b.min}><i style={{ background: colors[i] }} />{b.label}</span>)}
        {ndPoints && Object.entries(ND_STYLE).map(([k, s]) => (
          <span key={k}><i className="ring" style={{ borderColor: "var(--nd)" }} />{s.label}</span>
        ))}
        {ednaPoints && (
          <>
            <span><i className="site-dot" style={{ background: EDNA_COLOR }} />eDNA: DNA found</span>
            <span><i className="ring dashed" style={{ borderColor: EDNA_COLOR }} />eDNA: never found here</span>
          </>
        )}
        <span className="grid-palette" role="group" aria-label="Grid colours">
          <span className="meta">Colours:</span>
          {(Object.keys(PALETTES) as PaletteKey[]).map((k) => (
            <button
              key={k} type="button" className="swatch" aria-pressed={palette === k} title={PALETTES[k].label}
              aria-label={`${PALETTES[k].label} grid colours`} onClick={() => setPalette(k)}
              style={{ background: `linear-gradient(90deg, ${PALETTES[k].colors[1]}, ${PALETTES[k].colors[4]})` }}
            />
          ))}
        </span>
      </div>
      <p className="meta">
        Shading counts OBIS occurrence records per grid cell{isAllYears(years) ? "" : ` for ${describeRange(years)}`}{filtered ? ` from ${describeFilter(filter, catalog)}` : ""}{grid ? ` (${fmt(inView)} on screen${grid.present_truncated ? ", busiest cells only" : ""})` : ""}.
        A record is not a fish: one trawl haul, one photo or one acoustic tag ping counts once each. Unshaded water has no shared records, which is not the same as absence.
      </p>
      {/* The map and its totals are separate saved answers; the older of the two is what's on screen. */}
      <FetchedNote
        at={Math.min(grid?.fetched_at ?? Infinity, summary?.fetched_at ?? Infinity)}
        stale={!!(grid?.stale || summary?.stale)} what="these map records and totals" keep="up to a week"
      />
      {names && names.status !== "accepted" && names.accepted_name && (
        <p className="note warn">
          OBIS files these records under the accepted name <i>{names.accepted_name}</i>, so the map includes every population WoRMS now counts as that species, not only the one this list name described.
        </p>
      )}
      {freshwater && (
        <p className="note warn">OBIS collects marine and coastal data, so this mostly freshwater fish is poorly covered here. <a href={`https://www.gbif.org/species/search?q=${encodeURIComponent(species)}`} target="_blank" rel="noreferrer noopener">GBIF</a> holds more freshwater records.</p>
      )}
      </div>

      <div className="omap-side">

      {busiest.length > 0 && !cell && (
        <div>
          <h3>Busiest cells on screen</h3>
          <div className="cell-list">
            {busiest.map((c) => (
              <button key={key(c)} className="linklike" onClick={() => pick(c)}>
                {coord((c[1] + c[3]) / 2, (c[0] + c[2]) / 2)} · {fmt(c[4])} records
              </button>
            ))}
          </div>
          <p className="meta">Pick a cell on the map or here to see its records.</p>
        </div>
      )}

      {cell && (
        <CellRecords
          cell={cell} recs={recs} error={recsError} shown={shown}
          onMore={() => setShown((s) => s + 25)}
          onClose={() => setCell(null)}
        />
      )}

      <EdnaEvidencePanel key={`edna:${species}:${region}`} species={species} region={region} regionLabel={regionLabel} years={years} onSites={setEdnaPoints} />

      <NonDetections key={`${species}:${region}`} species={species} region={region} regionLabel={regionLabel} years={years} onShow={setNdPoints} showing={!!ndPoints} />
      </div>
    </div>
  );
}

const METHOD_LABEL: Record<RecordMethodFilter, string> = {
  survey: "Research surveys",
  telemetry: "Acoustic telemetry",
  edna: "eDNA",
  other: "Other or not stated",
  no_telemetry: "All except acoustic telemetry",
};
const capitalize = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);
const shortTitle = (t: string) => (t.length > 64 ? `${t.slice(0, 62).trimEnd()}…` : t);

/** The filter in words, for labels: "research surveys only", "all except acoustic telemetry". */
function describeFilter(f: RecordFilter, catalog: ObisCatalog | null): string {
  const parts: string[] = [];
  if (f.method) parts.push(f.method === "no_telemetry" ? "all except acoustic telemetry" : `${METHOD_LABEL[f.method].toLowerCase()} only`);
  if (f.dataset) {
    const d = catalog?.datasets.find((x) => x.id === f.dataset);
    parts.push(d ? `the dataset “${shortTitle(d.title)}”` : "one dataset");
  }
  return parts.join(", ");
}

type FilterProps = {
  species: string; region: RegionKey; regionLabel: string;
  filter: RecordFilter; onChange: (f: RecordFilter) => void;
  catalog: ObisCatalog | null; onCatalog: (c: ObisCatalog) => void;
};

/**
 * Which datasets the map and totals count: hide acoustic tag detections in one click, or pick an
 * observation method or a single dataset. The region's dataset list is only fetched once the
 * section is opened. Methods are what each dataset's own OBIS metadata says; the server checks
 * and resolves every choice, so nothing here is trusted as a dataset id.
 */
function RecordFilters({ species, region, regionLabel, filter, onChange, catalog, onCatalog }: FilterProps) {
  const [open, setOpen] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!open || catalog) return;
    let live = true;
    setError("");
    api.obisCatalog(species, region).then((c) => live && onCatalog(c)).catch((e) => live && setError(e.message));
    return () => { live = false; };
  }, [open, species, region, !!catalog]);

  const ofMethod = (m: RecordMethodFilter | null) => (catalog?.datasets ?? []).filter((d) =>
    !m || (m === "no_telemetry" ? d.method !== "telemetry" : d.method === m));
  // A dataset the new method doesn't include is dropped rather than left to empty the map.
  const pickMethod = (m: RecordMethodFilter | null) =>
    onChange({ method: m, dataset: filter.dataset && ofMethod(m).some((d) => d.id === filter.dataset) ? filter.dataset : null });
  const hideTags = filter.method === "no_telemetry";
  const count = (k: string) => catalog?.methods.find((m) => m.key === k);
  const fmtMethod = (k: RecordMethodFilter) => {
    const m = k === "no_telemetry" ? null : count(k);
    return m ? `${METHOD_LABEL[k]} · ${fmt(m.records)} records, ${m.datasets} dataset${m.datasets === 1 ? "" : "s"}` : METHOD_LABEL[k];
  };

  return (
    <div className="record-filters">
      <label className="row" style={{ gap: 6 }}>
        <input
          type="checkbox" checked={hideTags} disabled={filter.method !== null && !hideTags}
          onChange={(e) => pickMethod(e.target.checked ? "no_telemetry" : null)}
        />
        Hide acoustic-tag detections
      </label>
      <details className="datasets" onToggle={(e) => setOpen((e.currentTarget as HTMLDetailsElement).open)}>
        <summary>{isFiltered(filter) ? `Showing ${describeFilter(filter, catalog)}` : "Filter by method or dataset"}</summary>
        <div className="stack" style={{ gap: 8, marginTop: 8 }}>
          {error && <p className="meta">Couldn't load the dataset list: {error}</p>}
          {open && !catalog && !error && <p className="meta" role="status">Reading the dataset list from OBIS…</p>}
          {catalog && !catalog.complete && (
            <p className="note warn">OBIS lists {fmt(catalog.total)} datasets for this fish in {regionLabel}, too many to filter here. Pick a smaller region.</p>
          )}
          {catalog && catalog.complete && (
            <div className="row record-filter-fields">
              <label className="field">Observation method
                <select value={filter.method ?? ""} onChange={(e) => pickMethod((e.target.value || null) as RecordMethodFilter | null)}>
                  <option value="">All methods · {fmt(catalog.datasets.length)} datasets</option>
                  {(["survey", "telemetry", "edna", "other", "no_telemetry"] as RecordMethodFilter[]).map((k) => (
                    <option key={k} value={k} disabled={k !== "no_telemetry" && !count(k)?.datasets}>{fmtMethod(k)}</option>
                  ))}
                </select>
              </label>
              <label className="field">Dataset
                <select value={filter.dataset ?? ""} onChange={(e) => onChange({ method: filter.method, dataset: e.target.value || null })}>
                  <option value="">{filter.method ? "Every dataset of this method" : "Every dataset"}</option>
                  {ofMethod(filter.method).map((d) => (
                    <option key={d.id} value={d.id}>{shortTitle(d.title)} · {fmt(d.records ?? 0)}</option>
                  ))}
                </select>
              </label>
            </div>
          )}
          <p className="meta">
            Applies to the map, the record lists and the totals above it, within the datasets OBIS lists for this fish in {regionLabel}.
            The eDNA and net-survey sections below are not filtered. A method is what each dataset's own OBIS title, description or institute says;
            museum collections, FishBase, iNaturalist and compilations don't say how each record was made, so they are under “Other or not stated”.
            Every number counts occurrence records, not fish: one tagged fish can pass a receiver thousands of times.
          </p>
          {isFiltered(filter) && <button className="linklike" style={{ alignSelf: "flex-start" }} onClick={() => onChange(NO_FILTER)}>Clear the filter</button>}
        </div>
      </details>
    </div>
  );
}

type TotalsProps = { summary: ObisSummary | null; error: string; years: YearRange; filterLabel: string; onAllYears: () => void };

function ObisTotals({ summary, error, years, filterLabel, onAllYears }: TotalsProps) {
  if (error) return <p className="meta">Totals unavailable: {error}</p>;
  if (!summary) return <div className="obis-totals"><span className="meta">Counting records…</span></div>;
  // The server sends records per year once; any year range is totalled here.
  const all = isAllYears(years);
  const inRange = summary.by_year.filter((y) => yearInRange(y.year, years));
  const total = all ? summary.present : inRange.reduce((n, y) => n + y.records, 0);
  const span = all ? (summary.first_year ? `${summary.first_year}–${summary.last_year}` : "—")
    : inRange.length ? `${inRange[0].year}${inRange.length > 1 ? `–${inRange[inRange.length - 1].year}` : ""}` : "—";
  // Unfiltered, only the largest datasets are known, so the share is a lower bound; filtered, every dataset is.
  const exact = summary.filter?.datasets != null;
  const share = Math.round(summary.telemetry_share * 100);
  return (
    <div className="obis-totals" aria-live="polite">
      <div><span className="meta">Occurrence records in {summary.label}{all ? "" : `, ${describeRange(years)}`}{filterLabel ? `, ${filterLabel}` : ""}</span><b className="num">{fmt(total)}</b></div>
      {all
        ? <div><span className="meta">Since 2010</span><b className="num">{fmt(summary.since_2010)}</b></div>
        : <div><span className="meta">All years</span><b className="num">{fmt(summary.present)}</b></div>}
      <div><span className="meta">{all ? "Years" : "Years with records"}</span><b className="num">{span}</b></div>
      <div><span className="meta">Datasets{all ? "" : " (all years)"}</span><b className="num">{fmt(summary.dataset_count)}</b></div>
      {!all && total === 0 && summary.present > 0 && (
        <p className="note totals-note">
          No records in {summary.label} for {describeRange(years)}, but OBIS holds {fmt(summary.present)} from other years
          {summary.first_year ? ` (${summary.first_year}–${summary.last_year})` : ""}.{" "}
          <button className="linklike" onClick={onAllYears}>Show all years</button>
        </p>
      )}
      {summary.telemetry_share >= 0.2 && (
        <p className="note warn totals-note">
          {capitalize(`${all ? "" : "across all years, "}${exact ? (share >= 100 ? "all" : `${share}%`) : `at least ${share}%`}`)} of the records are acoustic tag detections, which log one tagged fish
          every time it passes a receiver. Read the shading as where records are, not how many fish.
        </p>
      )}
      {summary.datasets.length > 0 && (
        <details className="datasets">
          <summary>Largest contributing datasets{all ? "" : " (all years)"}</summary>
          <ul className="features">
            {summary.datasets.map((d) => (
              <li key={d.id}>
                <a href={d.url} target="_blank" rel="noreferrer noopener">{d.title}</a>
                {d.records ? <span className="meta num"> · {fmt(d.records)} records</span> : null}
                {d.telemetry && <span className="pill muted photos">Tag detections</span>}
                {d.institution ? <span className="meta"> · {d.institution}</span> : null}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

const fmtWhen = (d: Date) => d.toLocaleString("en-CA", { dateStyle: "medium", timeStyle: "short" });

type FetchedProps = {
  /** When Tideflow saved this answer from OBIS (seconds), from the server's cache. */
  at: number | null | undefined;
  /** OBIS couldn't be reached, or the update failed, so an older saved copy is shown. */
  stale: boolean;
  /** An expired copy is shown while a new one is prepared in the background. */
  refreshing?: boolean;
  what: string;
  keep: string;
};

/**
 * When Tideflow last retrieved this from OBIS, from the cache's own record of it. Not when OBIS
 * last updated its data, which Tideflow doesn't know. A saved copy shown because OBIS couldn't be
 * reached says so.
 */
function FetchedNote({ at, stale, refreshing, what, keep }: FetchedProps) {
  if (!at || !Number.isFinite(at)) return null;
  const d = new Date(at * 1000);
  const time = <time dateTime={d.toISOString()}>{fmtWhen(d)}</time>;
  if (stale && !refreshing) {
    return <p className="note warn" role="status">Tideflow couldn't get an update from OBIS, so this is a saved copy (last fetched {time})</p>;
  }
  return (
    <p className="meta fetched-note" title={`When Tideflow last retrieved and saved ${what} from OBIS (kept ${keep}). This is not when OBIS last updated its records.`}>
      Last fetched from OBIS by Tideflow: {time}{refreshing ? " · a newer copy is being prepared" : ""}
    </p>
  );
}

type EdnaProps = { species: string; region: RegionKey; regionLabel: string; years: YearRange; onSites: (p: EdnaPoint[] | null) => void };

const span = (a: string | null, b: string | null) => (a && b ? (a === b ? a : `${a} to ${b}`) : "dates not given");

/**
 * eDNA water samples for this fish: DNA found (a detection) or not found (a non-detection) at a
 * sampling site on a day. Kept apart from occurrence records and net surveys because DNA in water is
 * not a sighting. Loaded only when the section is opened; the detections arrive first and the
 * non-detections follow while the server finishes, so the page polls until they are in.
 */
function EdnaEvidencePanel({ species, region, regionLabel, years, onSites }: EdnaProps) {
  const [open, setOpen] = useState(false);
  const [raw, setRaw] = useState<EdnaEvidence | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [sites, setSites] = useState(true);
  // Counts for another year range must not be shown as this one's while the right ones load.
  const data = raw && (raw.range ? raw.range.since === years.from && raw.range.until === years.to : isAllYears(years)) ? raw : null;

  useEffect(() => {
    if (!open) return;
    let live = true;
    let timer = 0;
    const poll = () => api.obisEdna(species, region, years)
      .then((d) => {
        if (!live) return;
        setRaw(d); setError("");
        if (d.status === "computing" || d.nondetections.state === "computing" || d.nondetections.state === "queued") timer = window.setTimeout(poll, 2500);
      })
      .catch((e) => { if (live) setError(e.message); });
    poll();
    return () => { live = false; window.clearTimeout(timer); };
  }, [open, attempt, years.from, years.to]); // a new species or region remounts this component; a new year range asks again

  // Sites are on the map only while the section is open and the box is ticked.
  const pointsKey = data ? `${describeRange(years)}:${data.nondetections.state}:${data.points.length}:${data.nondetections.site_dates}` : "";
  useEffect(() => {
    onSites(open && sites && data && data.points.length ? data.points : null);
  }, [open, sites, pointsKey]);
  useEffect(() => () => onSites(null), []);

  const nd = data?.nondetections;
  const det = data?.detections;
  const pct = nd?.progress && nd.progress.total ? Math.min(99, Math.round((100 * nd.progress.done) / nd.progress.total)) : 0;
  const peak = Math.max(1, ...(data?.by_year ?? []).map((y) => y.detected + y.not_detected));

  return (
    <details className="nondetections edna" onToggle={(e) => setOpen((e.currentTarget as HTMLDetailsElement).open)}>
      <summary>eDNA water samples in {regionLabel}</summary>
      <div className="stack" style={{ gap: 10, marginTop: 8 }}>
        <p className="meta">
          DNA left in the water by a fish, filtered from a sample and matched to species. A detection shows the fish's DNA was in the water there
          on that day. It is not a sighting, and it says nothing about how many fish. Counts below are sampling events, one place on one day,
          not DNA sequences.
        </p>
        <p className="meta year-scope">
          <b>{describeRange(years)}</b>
          {isAllYears(years) ? " · every year OBIS has samples for." : " · only samples collected in these years are counted. Change the years above the map."}
        </p>
        {error && <p className="meta">Couldn't load eDNA samples: {error} <button className="linklike" onClick={() => setAttempt((a) => a + 1)}>Try again</button></p>}
        {open && !data && !error && <p className="meta" role="status">{raw ? `Counting ${describeRange(years)}…` : "Reading eDNA samples from OBIS…"}</p>}
        {data?.status === "computing" && !error && (
          <p className="meta" role="status">
            {data.nondetections.state === "queued"
              ? `Waiting for ${data.nondetections.ahead ?? 0} other large calculation${data.nondetections.ahead === 1 ? "" : "s"} to finish…`
              : "Reading eDNA samples from OBIS…"}
          </p>
        )}
        {data?.status === "none" && (
          <p className="meta">
            {!isAllYears(years) && data.available?.first_date
              ? `OBIS has no eDNA samples for this fish in ${regionLabel} for ${describeRange(years)}. Its samples were collected from ${data.available.first_date} to ${data.available.last_date}.`
              : `OBIS holds no eDNA samples for this fish in ${regionLabel}. That does not mean it is absent: it may just not have been sampled this way.`}
          </p>
        )}
        {data && data.status === "ok" && det && nd && (
          <>
            <div className="edna-tiles">
              <div className="edna-tile">
                <span className="meta"><i className="site-dot" style={{ background: EDNA_COLOR }} /> eDNA detections</span>
                <b className="num">{fmt(det.site_dates)} site-date{det.site_dates === 1 ? "" : "s"}</b>
                <span className="meta">{fmt(det.sites)} site{det.sites === 1 ? "" : "s"} · {span(det.first_date, det.last_date)}</span>
                <span className="meta">The fish's DNA was found.</span>
              </div>
              <div className="edna-tile">
                <span className="meta"><i className="ring dashed" style={{ borderColor: EDNA_COLOR }} /> eDNA non-detections</span>
                {(nd.state === "computing" || nd.state === "queued") && (
                  <>
                    <b className="num" role="status">Counting… {pct ? `${pct}%` : ""}</b>
                    <span className="edna-progress" aria-hidden="true"><span style={{ width: `${pct}%` }} /></span>
                    <span className="meta">The first count for a fish can take a few seconds. Detections are already shown.</span>
                  </>
                )}
                {nd.state === "ready" && (
                  <>
                    <b className="num">{fmt(nd.site_dates)} site-date{nd.site_dates === 1 ? "" : "s"}</b>
                    <span className="meta">{fmt(nd.sites)} site{nd.sites === 1 ? "" : "s"} · {span(nd.first_date, nd.last_date)}</span>
                    <span className="meta">No DNA found. Not proof the fish was absent.</span>
                  </>
                )}
                {nd.state === "none" && <span className="meta">No dataset reports its non-detections for this fish.</span>}
                {nd.state === "too_many" && <span className="meta">Too many non-detection records here to reduce to sampling events, so none are shown.</span>}
              </div>
            </div>

            {nd.withheld.map((w) => (
              <p key={w.method} className="meta"><b>Not shown:</b> {w.label}, {fmt(w.site_dates)} site-date{w.site_dates === 1 ? "" : "s"}. {w.reason}</p>
            ))}

            {data.by_year.length > 0 && (
              <div className="edna-years" role="table" aria-label="eDNA sampling events by year">
                <div role="row" className="meta edna-years-head"><span role="columnheader">Year</span><span role="columnheader">Found</span><span role="columnheader">Not found</span></div>
                {data.by_year.map((y) => (
                  <div role="row" key={y.year} className="edna-years-row">
                    <span role="cell" className="num">{y.year}</span>
                    <span role="cell" className="edna-bar">{y.detected > 0 && <i style={{ width: `${(100 * y.detected) / peak}%`, background: EDNA_COLOR }} />}<span className="num">{y.detected}</span></span>
                    <span role="cell" className="edna-bar">{y.not_detected > 0 && <i className="hollow" style={{ width: `${(100 * y.not_detected) / peak}%`, borderColor: EDNA_COLOR }} />}<span className="num">{y.not_detected}</span></span>
                  </div>
                ))}
              </div>
            )}

            {data.datasets.length > 0 && (
              <details>
                <summary>{data.datasets.length} contributing dataset{data.datasets.length === 1 ? "" : "s"}</summary>
                <ul className="features">
                  {data.datasets.map((d) => (
                    <li key={d.id}>
                      <a href={d.url} target="_blank" rel="noreferrer noopener">{d.title}</a>{" "}
                      <span className="pill muted photos" title="Genetic marker named in the dataset's description">{d.marker}</span>
                      <span className="meta num"> · found at {fmt(d.detected_site_dates)}
                        {d.reports_nondetections
                          ? `, not found at ${fmt(d.nondetected_site_dates + d.withheld_site_dates)}${d.withheld_site_dates ? " (not shown)" : ""}`
                          : ", does not report non-detections"} site-dates</span>
                    </li>
                  ))}
                </ul>
              </details>
            )}

            {data.points.length > 0 && (
              <label className="row" style={{ gap: 6 }}>
                <input type="checkbox" checked={sites} onChange={(e) => setSites(e.target.checked)} />
                Show eDNA sampling sites on the map{data.points_truncated ? " (first 3,000)" : ""}
              </label>
            )}
            {data.notes.map((n) => <p key={n} className="meta">{n}</p>)}
            <p className="note warn">
              Not found is not absent. eDNA can miss a fish that is there, depending on the genetic marker, how much water was filtered and
              how the DNA drifts or breaks down; it can also carry DNA from far away. Samples from different datasets and markers are only
              merged where they share a place and day. Sampling effort differs between sites and years, so these counts are not abundance and
              should not be compared as if they were.
            </p>
          </>
        )}
        {/* Only a finished calculation has a time; one still running doesn't show one yet. */}
        {data && (data.status === "ok" || data.status === "none") && (
          <FetchedNote at={data.fetched_at} stale={!!data.stale} refreshing={!!data.refreshing} what="this eDNA evidence" keep="up to a month" />
        )}
      </div>
    </details>
  );
}

type NdProps = { species: string; region: RegionKey; regionLabel: string; years: YearRange; showing: boolean; onShow: (p: ObisNonDetections["points"] | null) => void };

/**
 * Surveys that reported this fish as not detected, counted by site and date per sampling method,
 * fetched only when someone opens the section, because the first summary can take a minute.
 */
function NonDetections({ species, region, regionLabel, years, showing, onShow }: NdProps) {
  const [open, setOpen] = useState(false);
  const [data, setData] = useState<ObisNonDetections | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);

  // The server works on this in the background, so ask again until it has an answer.
  useEffect(() => {
    if (!open) return;
    let live = true;
    let timer = 0;
    const poll = () => api.obisNonDetections(species, region)
      .then((d) => {
        if (!live) return;
        setData(d); setError("");
        if (d.status === "computing" || d.status === "queued") timer = window.setTimeout(poll, 2500);
      })
      .catch((e) => { if (live) setError(e.message); });
    if (!data || data.status === "computing" || data.status === "queued") poll();
    return () => { live = false; window.clearTimeout(timer); };
  }, [open, attempt]); // a new species or region remounts this component, so they aren't needed here

  return (
    <details className="nondetections" onToggle={(e) => setOpen((e.currentTarget as HTMLDetailsElement).open)}>
      <summary>Net or trawl surveys that didn't catch this fish in {regionLabel} (all years)</summary>
      <div className="stack" style={{ gap: 10, marginTop: 8 }}>
        {!isAllYears(years) && (
          <p className="note warn">This summary covers all years. It does not follow the {describeRange(years)} range chosen above the map.</p>
        )}
        {error && (
          <p className="meta">Couldn't summarise non-detections: {error} <button className="linklike" onClick={() => setAttempt((a) => a + 1)}>Try again</button></p>
        )}
        {open && (!data || data.status === "computing" || data.status === "queued") && !error && (
          <p className="meta" role="status">
            {data?.status === "queued"
              ? `Waiting for ${data.ahead ?? 0} other large calculation${data.ahead === 1 ? "" : "s"} to finish…`
              : "Summarising non-detection records from OBIS. The first time for a species can take a minute or two."}
          </p>
        )}
        {data?.status === "none" && <p className="meta">No survey in OBIS reported this fish as not detected here.</p>}
        {data?.status === "too_many" && (
          <p className="meta">OBIS holds {fmt(data.absence_rows)} non-detection records here, more than the app can reliably reduce to sites and dates, so none are shown.</p>
        )}
        {data?.status === "ok" && (
          <>
            <p className="meta">
              Each count is a <b>site-date</b>: one place on one day where a survey reported the fish as not detected,
              and no survey in these datasets found it there that day. {fmt(data.absence_rows)} raw OBIS absence rows reduce to these.
            </p>
            {data.methods.length === 0 && <p className="meta">None of these non-detections come from a method whose result can be interpreted here (see below). eDNA has its own section above.</p>}
            {data.methods.map((m) => (
              <div key={m.method} className="nd-method">
                <div className="row" style={{ justifyContent: "space-between" }}>
                  <b><i className="ring" style={{ borderColor: ND_STYLE[m.method] ? "var(--nd)" : undefined }} /> {m.label}</b>
                  <span className="num">{fmt(m.site_dates)} site-date{m.site_dates === 1 ? "" : "s"} · {fmt(m.sites)} site{m.sites === 1 ? "" : "s"}</span>
                </div>
                <p className="meta">
                  {m.first_date && m.last_date ? `${m.first_date} to ${m.last_date}. ` : ""}
                  The same datasets detected the fish at {fmt(m.detected_site_dates)} site-date{m.detected_site_dates === 1 ? "" : "s"}.{" "}
                  The net, trawl or seine didn't catch it. Gear catches some fish far better than others.
                </p>
                <details>
                  <summary>{m.datasets.length} dataset{m.datasets.length === 1 ? "" : "s"}</summary>
                  <ul className="features">
                    {m.datasets.map((d) => (
                      <li key={d.id}><a href={d.url} target="_blank" rel="noreferrer noopener">{d.title}</a><span className="meta num"> · {fmt(d.site_dates)} site-dates from {fmt(d.absence_rows)} rows</span></li>
                    ))}
                  </ul>
                </details>
              </div>
            ))}
            {data.withheld.length > 0 && (
              <div className="nd-withheld">
                <b>Not shown</b>
                <ul className="features">
                  {data.withheld.map((w) => (
                    <li key={w.method}>{w.label}: {fmt(w.site_dates)} site-dates. <span className="meta">{w.reason}</span></li>
                  ))}
                </ul>
              </div>
            )}
            {data.points.length > 0 && (
              <label className="row" style={{ gap: 6 }}>
                <input type="checkbox" checked={showing} onChange={(e) => onShow(e.target.checked ? data.points : null)} />
                Show these sites on the map{data.points_truncated ? " (first 3,000)" : ""}
              </label>
            )}
            <p className="note warn">Not detected is not the same as absent. A survey can miss a fish that was there.</p>
          </>
        )}
      </div>
    </details>
  );
}

type CellProps = {
  cell: { bbox: number[]; present: number };
  recs: ObisRecords | null; error: string; shown: number;
  onMore: () => void; onClose: () => void;
};

function CellRecords({ cell, recs, error, shown, onMore, onClose }: CellProps) {
  const [w, s, e, n] = cell.bbox;
  const rows = recs?.records ?? [];
  return (
    <section className="cell-records" aria-label="Records in the selected cell">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h3 style={{ margin: 0 }}>{coord((s + n) / 2, (w + e) / 2)} · occurrence records</h3>
        <button className="btn" onClick={onClose}>Back</button>
      </div>
      <p className="meta">{fmt(cell.present)} occurrence record{cell.present === 1 ? "" : "s"} of the fish here.</p>
      {error && <p className="meta">{error}</p>}
      {!recs && !error && <p className="meta">Loading records…</p>}
      {recs && recs.total > rows.length && (
        <p className="meta">Showing {rows.length} of {fmt(recs.total)}, newest first. With this many, OBIS picks which ones come back, so zoom in for a closer look.</p>
      )}
      <ul className="records">
        {rows.slice(0, shown).map((r) => (
          <li key={r.id}>
            <div className="row" style={{ justifyContent: "space-between", gap: 6 }}>
              <b className="num">{r.date || "No date"}</b>
              <span className="pill accent" title={r.basis}>{basisLabel(r.basis)}</span>
            </div>
            <div>{r.dataset_url ? <a href={r.dataset_url} target="_blank" rel="noreferrer noopener">{r.dataset || "Dataset"}</a> : r.dataset}</div>
            <div className="meta">
              {[
                r.institution,
                coord(r.lat, r.lon) + (r.uncertainty_m ? ` ±${fmt(Math.round(r.uncertainty_m))} m` : ""),
                r.depth_m != null ? `${r.depth_m} m deep` : "",
                r.count ? `${r.count} counted` : "",
                r.name_as_recorded && r.name_as_recorded !== recs?.species ? `recorded as ${r.name_as_recorded}` : "",
                r.license ? licenseLabel(r.license) : "",
              ].filter(Boolean).join(" · ")}
            </div>
          </li>
        ))}
      </ul>
      {rows.length > shown && <button className="btn" onClick={onMore}>Show more</button>}
    </section>
  );
}

/** Darwin Core basisOfRecord, in words. MachineObservation in these datasets is mostly acoustic tag detections. */
const BASIS: Record<string, string> = {
  HumanObservation: "Seen or caught",
  MachineObservation: "Instrument or tag",
  PreservedSpecimen: "Museum specimen",
  MaterialSample: "Sample, often eDNA",
  MaterialCitation: "Literature",
  LivingSpecimen: "Living specimen",
  Occurrence: "Record",
};

/** Datasets don't agree on case ("materialSample" as well as "MaterialSample"), so match without it. */
function basisLabel(basis: string): string {
  const hit = Object.entries(BASIS).find(([k]) => k.toLowerCase() === (basis ?? "").toLowerCase());
  return hit ? hit[1] : basis || "Record";
}

/** OBIS gives licences as URLs. Show the short name people know. */
function licenseLabel(url: string): string {
  const u = url.toLowerCase();
  if (u.includes("publicdomain/zero") || u.includes("cc0")) return "CC0";
  const m = u.match(/licenses\/(by(?:-nc)?(?:-sa)?(?:-nd)?)\/(\d\.\d)/);
  return m ? `CC ${m[1].toUpperCase()} ${m[2]}` : "See dataset licence";
}
