import { useEffect, useState } from "react";
import { api, WqiTable as WqiTableData } from "./api";

/** Coastal Action's report card colors for each rating, taken from their 2023 LaHave report card. */
const RATINGS = [
  { name: "Poor", range: "0 - 44", color: "#d13518", ink: "#ffffff" },
  { name: "Marginal", range: "45 - 64", color: "#f47321", ink: "#101828" },
  { name: "Fair", range: "65 - 79", color: "#ffdc29", ink: "#101828" },
  { name: "Good", range: "80 - 94", color: "#b3f118", ink: "#101828" },
  { name: "Excellent", range: "95 - 100", color: "#40b411", ink: "#101828" },
];
const RIVER_BLUE = "#14b4ec";

const cell = { border: "1px solid #5b6472", padding: "6px 10px", textAlign: "center" as const };
const head = { ...cell, fontWeight: 500, fontFamily: "inherit", fontSize: 15, textTransform: "none" as const, letterSpacing: "normal", color: "#101828" };

/**
 * The Water Quality Index table, laid out like Coastal Action's report card: sites from the headwaters
 * down to the estuary, one colored cell per year, and what the fish surveys found. Clicking a site
 * shows its charts below. The scores come from server/tidecount/wqi.py.
 */
export function WqiTable({ onPickSite }: { onPickSite: (siteId: string) => void }) {
  const [data, setData] = useState<WqiTableData | null>(null);
  useEffect(() => { api.wqiTable().then(setData); }, []);

  if (!data) return <p className="meta">Loading the report card…</p>;
  if (data.sites.length === 0) return <p className="meta">Not enough water data for a report card yet.</p>;

  const fishYear = data.years[data.years.length - 1];
  const anyDemo = data.sites.some((s) => s.fish.some((f) => f.demo));

  return (
    <div className="stack" style={{ gap: 10 }}>
      <div style={{ display: "flex", gap: 8, overflowX: "auto" }}>
        {/* The "direction of river flow" arrow down the left, as on the report card. */}
        <div style={{ display: "flex", gap: 4, paddingTop: 40 }} aria-hidden>
          <span style={{ writingMode: "vertical-rl", transform: "rotate(180deg)", fontSize: 12, whiteSpace: "nowrap", alignSelf: "center" }}>
            direction of river flow
          </span>
          <div style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
            <div style={{ flex: 1, width: 10, background: RIVER_BLUE }} />
            <div style={{ width: 0, height: 0, borderLeft: "14px solid transparent", borderRight: "14px solid transparent", borderTop: `16px solid ${RIVER_BLUE}` }} />
          </div>
        </div>

        <table style={{ borderCollapse: "collapse", fontSize: 15 }}>
          <thead>
            <tr>
              <th style={{ ...head, color: "var(--accent-ink)" }}>Site</th>
              {data.years.map((y) => <th key={y} style={head}>{y}</th>)}
              <th style={head}>Fish in {fishYear}</th>
            </tr>
          </thead>
          <tbody>
            {data.sites.map((s) => {
              const fish = s.fish.find((f) => f.year === fishYear);
              return (
                <tr key={s.site_id}>
                  <td style={{ ...cell, background: "#ececee", whiteSpace: "nowrap" }}>
                    <button onClick={() => onPickSite(s.site_id)} title="Show this site's charts"
                      style={{ background: "none", border: 0, padding: 0, font: "inherit", color: "inherit", cursor: "pointer", textDecoration: "underline dotted" }}>
                      {s.site_name}
                    </button>
                    {s.salty && <span className="meta" title="Scored with estuary (marine) guidelines"> · estuary</span>}
                  </td>
                  {s.scores.map((c) => {
                    const r = RATINGS.find((x) => x.name === c.rating);
                    return (
                      <td key={c.year} className="num" title={`${s.site_name}, ${c.year}: ${c.rating}`}
                        style={{ ...cell, background: r?.color ?? "transparent", color: r?.ink ?? "var(--muted-2)", minWidth: 58 }}>
                        {c.wqi === null ? "–" : c.wqi.toFixed(1)}
                      </td>
                    );
                  })}
                  <td style={{ ...cell, fontSize: 13, textAlign: "left", whiteSpace: "nowrap" }}>
                    {fish ? (
                      <span title={`${fish.surveys} surveys, ${fish.fish} fish. Most common: ${fish.most_common}. Shannon diversity ${fish.shannon ?? "–"}.`}>
                        {fish.species} species · {fish.per_survey} per survey{fish.demo && <b style={{ color: "var(--down-ink)" }}> (demo)</b>}
                      </span>
                    ) : <span className="meta">No surveys</span>}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* The legend: a colored dot for each rating. */}
      <div className="row" style={{ gap: 18, flexWrap: "wrap", fontSize: 13, paddingLeft: 36 }}>
        {RATINGS.map((r) => (
          <span key={r.name} style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
            <span style={{ width: 14, height: 14, borderRadius: "50%", background: r.color, border: "1px solid #5b6472" }} />
            {r.name} ({r.range})
          </span>
        ))}
        <span className="meta">– Not enough data</span>
      </div>

      <p className="meta" style={{ lineHeight: 1.6 }}>
        The CCME Water Quality Index, worked out by TideCount from Coastal Action's readings. Freshwater and estuary
        sites use different guidelines, as in Coastal Action's report cards. These are not their official scores: on
        2017 to 2023 they come within about 5 points of the published ones. Click a site to see its charts.
        {anyDemo && " Fish numbers marked demo are made up, to show how the column will look."}
      </p>
    </div>
  );
}