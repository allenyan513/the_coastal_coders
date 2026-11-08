import "leaflet/dist/leaflet.css";

import L from "leaflet";
import { useEffect, useRef } from "react";

/** One station the map can place: where it is, its latest MeanCount and the change since the season before. */
export type MapStation = {
  id: string;
  label: string;
  transectId: string;
  transect: string;
  at: [number, number];
  now: number | null;
  change: number | null;
  /** The circle's width in pixels, from its MeanCount. */
  size: number;
};
export type MapWaterSite = { id: string; name: string; at: [number, number] };

/** (latitude, longitude) from text like "44.1, -64.7", the way Surveys stores it. Null when it isn't that. */
export function parseCoordinates(text: string): [number, number] | null {
  const pieces = (text || "").split(",");
  if (pieces.length !== 2) return null;
  const [lat, lon] = pieces.map((p) => Number(p.trim()));
  if (!pieces[0].trim() || !pieces[1].trim() || !Number.isFinite(lat) || !Number.isFinite(lon)) return null;
  return Math.abs(lat) <= 90 && Math.abs(lon) <= 180 ? [lat, lon] : null;
}

/** The distance between two points along the earth's surface, in km (the haversine formula). */
export function distanceKm(a: [number, number], b: [number, number]) {
  const rad = Math.PI / 180;
  const dLat = (b[0] - a[0]) * rad;
  const dLon = (b[1] - a[1]) * rad;
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(a[0] * rad) * Math.cos(b[0] * rad) * Math.sin(dLon / 2) ** 2;
  return 2 * 6371 * Math.asin(Math.sqrt(h));
}

// Names come from what people typed in Surveys, so they go in as text, never as HTML.
function text(value: string) {
  const span = document.createElement("span");
  span.textContent = value;
  return span;
}

const signed = (n: number) => `${n > 0 ? "+" : n < 0 ? "−" : "±"}${Math.abs(n).toFixed(1)}`;

/**
 * The stations of one survey site on a street map. Each circle's size is its latest MeanCount and its
 * color says whether it counted higher or lower than the season before, with an arrow so the colors
 * aren't the only cue. Dashed lines join each transect's stations in order. Yellow dots are Coastal
 * Action's water sampling sites, which open Fish and water.
 */
export function StationMap({ stations, water, picked, onPick, onWater, fitKey, base }: {
  stations: MapStation[];
  water: MapWaterSite[];
  picked: string;
  onPick: (id: string) => void;
  onWater: (id: string) => void;
  /** The map fits to the stations again whenever this changes, such as on another site. */
  fitKey: string;
  /** The earlier season, for the tooltips. */
  base?: string;
}) {
  const box = useRef<HTMLDivElement>(null);
  const map = useRef<L.Map | null>(null);
  const layer = useRef<L.LayerGroup | null>(null);
  // The latest handlers, so redrawing doesn't depend on them.
  const handlers = useRef({ onPick, onWater });
  handlers.current = { onPick, onWater };
  // On a phone the map is narrow, so it fits tighter and the circles shrink a little to stay apart.
  const narrow = () => (box.current?.clientWidth ?? 600) < 520;

  useEffect(() => {
    if (!box.current) return;
    const m = L.map(box.current, { zoomSnap: 0.25, scrollWheelZoom: false, maxZoom: 19 });
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    }).addTo(m);
    L.control.scale({ imperial: false }).addTo(m);
    layer.current = L.layerGroup().addTo(m);
    map.current = m;
    return () => {
      m.remove();
      map.current = null;
      layer.current = null;
    };
  }, []);

  useEffect(() => {
    const m = map.current;
    if (!m || stations.length === 0) return;
    const pad = narrow() ? 36 : 56;
    m.fitBounds(L.latLngBounds(stations.map((s) => s.at)), { padding: [pad, pad], maxZoom: 17 });
    // Only a new site moves the map: picking a station leaves the view where the person put it.
  }, [fitKey]);

  useEffect(() => {
    const group = layer.current;
    if (!group) return;
    group.clearLayers();

    water.forEach((w) => {
      L.circleMarker(w.at, { radius: 7, color: "#98a2b3", weight: 2, fillColor: "#ffdc29", fillOpacity: 1 })
        .bindTooltip(text(`Water site: ${w.name} · open Fish and water`), { direction: "top" })
        .on("click", () => handlers.current.onWater(w.id))
        .addTo(group);
    });

    const scale = narrow() ? 0.8 : 1;
    const placed = stations.map((s) => ({ ...s, size: Math.max(20, Math.round(s.size * scale)) }));
    const transects = [...new Set(placed.map((s) => s.transectId))];
    transects.forEach((id) => {
      const along = placed.filter((s) => s.transectId === id);
      if (along.length > 1) {
        L.polyline(along.map((s) => s.at), { color: "#475467", weight: 2, dashArray: "5 4", interactive: false }).addTo(group);
      }
      L.marker(along[0].at, {
        interactive: false,
        keyboard: false,
        icon: L.divIcon({ className: "stransect", html: text(along[0].transect).outerHTML, iconSize: [0, 0], iconAnchor: [along[0].size / 2 + 34, along[0].size / 2 + 14] }),
      }).addTo(group);
    });

    placed.forEach((s) => {
      const on = s.id === picked;
      const tone = s.change === null ? "" : s.change >= 0 ? "up" : "down";
      const arrow = s.change === null ? "" : s.change >= 0 ? "▲" : "▼";
      const value = s.now === null ? "–" : s.now.toFixed(1);
      const html = `<span class="smark ${tone}${on ? " on" : ""}" style="width:${s.size}px;height:${s.size}px">${value}${arrow ? `<b>${arrow}</b>` : ""}</span>`;
      const change = s.change === null ? "no earlier season" : `${signed(s.change)} since ${base ?? "last season"}`;
      L.marker(s.at, {
        icon: L.divIcon({ className: "smark-wrap", html, iconSize: [s.size, s.size] }),
        title: `${s.label}, MeanCount ${value}, ${change}`,
        zIndexOffset: on ? 1000 : 0,
        riseOnHover: true,
      })
        .bindTooltip(text(`${s.label} · ${change}`), { direction: "top", offset: [0, -s.size / 2 - 2] })
        .on("click", () => handlers.current.onPick(s.id))
        .addTo(group);
    });
  }, [stations, water, picked, base]);

  return <div ref={box} className="smap" />;
}
