import { useEffect, useMemo, useState } from "react";
import { api, SpeciesRow } from "./api";

const GROUPS: Record<string, string> = { Actinopterygii: "Ray-finned fish", Elasmobranchii: "Sharks and rays", "": "From fish surveys" };
const SORTS = {
  inat_obs: "iNaturalist sightings",
  obis_nearshore_records: "OBIS nearshore records",
  seine_records: "Seine records",
  confirmed: "Named here",
} as const;
type SortKey = keyof typeof SORTS;

/** The fish AI may suggest. Read-only: the list lives in the server's species.csv. */
export function Species() {
  const [rows, setRows] = useState<SpeciesRow[] | null>(null);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<SortKey>("inat_obs");

  useEffect(() => { api.species().then(setRows).catch((e) => setError(e.message)); }, []);

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (rows ?? [])
      .filter((r) => !q || r.common.toLowerCase().includes(q) || r.species.toLowerCase().includes(q))
      .sort((a, b) => b[sort] - a[sort] || a.common.localeCompare(b.common));
  }, [rows, query, sort]);

  if (error) return <p className="meta">{error}</p>;
  if (!rows) return <p className="meta">Loading…</p>;
  const named = rows.filter((r) => r.confirmed > 0).length;

  return (
    <div className="stack" style={{ gap: 20 }}>
      <div>
        <h1>Species list</h1>
        <p className="lede">AI only suggests fish from this list, built from records of fish seen in Nova Scotia. A person always makes the final call.</p>
      </div>

      <div className="panel kpis">
        <div className="kpi"><span className="meta">Fish on the list</span><b>{rows.length}</b></div>
        <div className="kpi"><span className="meta">Sharks and rays</span><b>{rows.filter((r) => r.group === "Elasmobranchii").length}</b></div>
        <div className="kpi"><span className="meta">From fish surveys only</span><b>{rows.filter((r) => r.group === "").length}</b></div>
        <div className="kpi"><span className="meta">Named by a person here</span><b>{named}</b></div>
      </div>

      <div className="panel">
        <div className="panel-head row">
          <label className="field" style={{ flex: "1 1 240px" }}>Search
            <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Common or scientific name" />
          </label>
          <label className="field">Most first
            <select value={sort} onChange={(e) => setSort(e.target.value as SortKey)}>
              {Object.entries(SORTS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
            </select>
          </label>
          <span className="num meta" style={{ alignSelf: "flex-end", paddingBottom: 10 }}>{shown.length} of {rows.length}</span>
        </div>
        <div style={{ overflowX: "auto" }}>
          <table className="sticky-first">
            <thead>
              <tr>
                <th>Common name</th><th>Scientific name</th><th>Group</th>
                <th className="right" title="Sightings logged by the public on iNaturalist">iNaturalist sightings</th>
                <th className="right" title="Records near shore in OBIS, the Ocean Biodiversity Information System">OBIS nearshore</th>
                <th className="right" title="Records from beach seine net surveys">Seine surveys</th>
                <th className="right" title="Tracks a person gave this name on this PC">Named here</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((r) => (
                <tr key={r.species}>
                  <td style={{ fontWeight: 500 }}>{r.common === r.species ? "—" : r.common}</td>
                  <td><i>{r.species}</i></td>
                  <td className="meta">{GROUPS[r.group] ?? r.group}</td>
                  <td className="num right">{r.inat_obs || "—"}</td>
                  <td className="num right">{r.obis_nearshore_records || "—"}</td>
                  <td className="num right">{r.seine_records || "—"}</td>
                  <td className="num right">{r.confirmed ? <span className="pill up">{r.confirmed}</span> : "—"}</td>
                </tr>
              ))}
              {!shown.length && <tr><td colSpan={7} className="meta">No fish match that search.</td></tr>}
            </tbody>
          </table>
        </div>
      </div>
      <p className="meta">The numbers show why a fish is on the list, not how common it is on your sites. To change the list, edit species.csv on the server.</p>
    </div>
  );
}
