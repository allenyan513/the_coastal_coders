import { useEffect, useState } from "react";
import { api, FishOptions, FishSeries, FishWaterComparison, WaterSeries, WaterSite } from "./api";
import { CompareChart } from "./CompareChart";
import { WaterChart } from "./WaterChart";

/** The measurements Coastal Action takes on site, as named in their data. Matches KEEP in server/tidecount/water.py. */
const MEASUREMENTS = [
  "Dissolved oxygen (DO)",
  "Dissolved oxygen saturation",
  "Temperature, water",
  "pH",
  "Specific conductance",
  "Salinity",
];

type Point = { date: string; value: number };

/**
 * Fish and water trends. Ethan owns this page: the route and the sidebar entry already point here.
 * Fish counts come from the fish_counts table (server/tidecount/trends.py), which holds made-up demo
 * data for now. Water readings come from the water_readings table, imported by server/tidecount/water.py.
 */
export function River() {
  const [sites, setSites] = useState<WaterSite[]>([]);
  const [siteId, setSiteId] = useState("1");
  const [deseason, setDeseason] = useState(false);

  const [fishOptions, setFishOptions] = useState<FishOptions | null>(null);
  const [metric, setMetric] = useState("total");
  const [fish, setFish] = useState<FishSeries | null>(null);

  const [measurement, setMeasurement] = useState("Dissolved oxygen (DO)");
  const [data, setData] = useState<WaterSeries | null>(null);

  // Load the sites once, when the page opens.
  useEffect(() => { api.waterSites().then(setSites); }, []);

  // What the fish chart can show at this site, and the chosen fish measure.
  useEffect(() => { api.fishOptions(siteId).then(setFishOptions); }, [siteId]);
  useEffect(() => { api.fishSeries(siteId, metric, deseason).then(setFish); }, [siteId, metric, deseason]);

  // Load the water readings whenever the site, the measurement or the seasonal option changes.
  useEffect(() => { api.waterSeries(siteId, measurement, deseason).then(setData); }, [siteId, measurement, deseason]);

  // The two on one shared scale, with their correlation.
  const [comparison, setComparison] = useState<FishWaterComparison | null>(null);
  useEffect(() => { api.fishWater(siteId, metric, measurement, deseason).then(setComparison); }, [siteId, metric, measurement, deseason]);

  // With fish counts, the water chart covers the same years, so the two line up.
  const hasFish = !!fish && fish.points.length > 0;
  const from = hasFish ? fish.points[0].date : "";
  const to = hasFish ? fish.points[fish.points.length - 1].date : "";
  const waterPoints = data ? data.points.filter((p) => !hasFish || (p.date >= from && p.date <= to)) : [];
  const siteName = sites.find((s) => s.site_id === siteId)?.site_name ?? "";

  return (
    <div className="stack" style={{ gap: 20 }}>
      <div>
        <h1>Fish and water trends</h1>
        <p className="lede">How fish counts change over time, next to Coastal Action's water readings from the LaHave River.</p>
      </div>

      <div className="row" style={{ gap: 16, flexWrap: "wrap", alignItems: "center" }}>
        <label>
          Site{" "}
          <select value={siteId} onChange={(e) => setSiteId(e.target.value)}>
            {sites.map((s) => <option key={s.site_id} value={s.site_id}>{s.site_name}</option>)}
          </select>
        </label>
        <label title="Takes out the usual pattern for each month, so year-to-year change is easier to see">
          <input type="checkbox" checked={deseason} onChange={(e) => setDeseason(e.target.checked)} />{" "}
          Remove seasonal pattern
        </label>
      </div>
      {deseason && (
        <p className="meta" style={{ marginTop: -12, lineHeight: 1.6 }}>
          Each value has its calendar month's average over all years taken away, then the overall average added back.
          What's left is change from year to year and unusual months, not summer and winter. Months seen only once are left out.
        </p>
      )}

      {hasFish && comparison && (
        <section className="panel panel-pad">
          <h2>Compare: {comparison.fish.label} and {comparison.water.label}{deseason ? ", seasonal pattern removed" : ""}</h2>
          <p className="meta" style={{ lineHeight: 1.6 }}>
            Both lines on one scale: how far each is above or below its own usual level, in standard deviations.
            Change what's compared with the two "Show" and "Measurement" boxes below.
          </p>
          <CorrelationLine c={comparison} />
          <CompareChart fish={comparison.fish} water={comparison.water} />
          <p className="meta" style={{ lineHeight: 1.6 }}>
            Spearman correlation runs from −1 (one always falls as the other rises) to +1 (they always rise together); 0 means
            no relationship. It shows two things move together, not that one causes the other. Season drives many fish and
            water measures at once, so tick "Remove seasonal pattern" to see whether they still move together year to year.
            {comparison.demo && " With demo fish data, these numbers only show how the analysis will work."}
          </p>
        </section>
      )}

      <section className="panel panel-pad">
        <div className="row" style={{ justifyContent: "space-between", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
          <h2>Fish{fish?.label ? `: ${fish.label}` : ""}{deseason ? ", seasonal pattern removed" : ""}</h2>
          {fishOptions && (
            <label>
              Show{" "}
              <select value={metric} onChange={(e) => setMetric(e.target.value)}>
                <optgroup label="All fish">
                  {fishOptions.metrics.map((m) => <option key={m.key} value={m.key}>{m.label}</option>)}
                </optgroup>
                {fishOptions.species.length > 0 && (
                  <optgroup label="One species">
                    {fishOptions.species.map((s) => <option key={s} value={s}>{s}</option>)}
                  </optgroup>
                )}
              </select>
            </label>
          )}
        </div>
        {fish?.demo && (
          <p className="demo-flag" style={{ background: "var(--warn-soft)", color: "var(--down-ink)", padding: "6px 10px", borderRadius: 6, fontSize: 13 }}>
            <b>Demo data.</b> These fish counts are made up to show how trends will look. They are not real observations.
          </p>
        )}
        {fish && !hasFish && (
          <p className="meta">
            No fish counts at {siteName || "this site"} yet. Demo counts cover Upper LaHave, Dayspring and Bridgewater.
            Real counts will appear once videos are linked to a sampling site and date.
          </p>
        )}
        {hasFish && (
          <>
            <Summary points={fish.points} unit={fish.unit} what="surveys" />
            <WaterChart points={fish.points} label={fish.label} unit={fish.unit} />
          </>
        )}
      </section>

      <section className="panel panel-pad">
        <div className="row" style={{ justifyContent: "space-between", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
          <h2>Water: {measurement}{data?.unit ? ` (${data.unit})` : ""}{deseason ? ", seasonal pattern removed" : ""}</h2>
          <label>
            Measurement{" "}
            <select value={measurement} onChange={(e) => setMeasurement(e.target.value)}>
              {MEASUREMENTS.map((name) => <option key={name} value={name}>{name}</option>)}
            </select>
          </label>
        </div>
        {!data && <p className="meta">Loading…</p>}
        {data && hasFish && <p className="meta">Showing {from} to {to}, the same years as the fish counts.</p>}
        {data && <Summary points={waterPoints} unit={data.unit} what="readings" />}
        {data && <WaterChart points={waterPoints} label={measurement} unit={data.unit} />}
        {measurement === "Specific conductance" && (
          <p className="meta" style={{ lineHeight: 1.6 }}>
            Corrected: at the three salty estuary sites (Upper LaHave, Dayspring, Bridgewater), 739 conductance readings
            labelled uS/cm were really mS/cm, 1,000 times too small for the salinity measured on the same visit.
            They have been multiplied by 1,000.
          </p>
        )}
        <p className="meta" style={{ borderTop: "1px solid var(--border-2)", paddingTop: 8 }}>
          Data: Coastal Action,{" "}
          <a href="https://doi.org/10.25976/r245-z904" target="_blank" rel="noreferrer">LaHave River Water Quality Monitoring</a>
          {" "}(DataStream), licensed ODC-By. Readings outside sensible limits, such as dissolved oxygen above 20 mg/L, are left out.
        </p>
      </section>
    </div>
  );
}

/** The correlation in numbers and words, such as "Spearman ρ = +0.62, strong positive · 120 pairs · p < 0.001". */
function CorrelationLine({ c }: { c: FishWaterComparison }) {
  if (c.spearman === null) {
    return <p className="meta">Not enough fish surveys with a water reading within {c.max_gap_days} days to work out a correlation.</p>;
  }
  const rho = `${c.spearman >= 0 ? "+" : "−"}${Math.abs(c.spearman).toFixed(2)}`;
  const p = c.p_value === null ? "" : c.p_value < 0.001 ? "p < 0.001" : `p = ${c.p_value.toFixed(3)}`;
  return (
    <div className="row" style={{ gap: 20, flexWrap: "wrap", alignItems: "baseline" }}>
      <div>
        <span className="meta">Spearman correlation</span>
        <div style={{ fontSize: 22, fontWeight: 600 }} className="num">ρ = {rho}</div>
      </div>
      <div><span className="meta">Strength</span><div style={{ fontSize: 15, fontWeight: 500 }}>{c.strength}</div></div>
      <div><span className="meta">Pairs</span><div className="num" style={{ fontSize: 15 }}>{c.pairs}</div></div>
      <div><span className="meta">Chance of this by luck</span><div className="num" style={{ fontSize: 15 }}>{p}</div></div>
      <p className="meta" style={{ flexBasis: "100%", margin: 0 }}>
        Each fish survey is paired with the water reading closest in time, within {c.max_gap_days} days.
      </p>
    </div>
  );
}

/** How many points, the lowest, highest and average, and the date range. */
function Summary({ points, unit, what }: { points: Point[]; unit: string; what: string }) {
  if (points.length === 0) return null;
  const values = points.map((p) => p.value);
  const average = values.reduce((total, v) => total + v, 0) / values.length;
  const u = unit ? ` ${unit}` : "";
  const round = (v: number) => String(Number(v.toFixed(2)));
  return (
    <p className="meta num">
      {points.length} {what} · Lowest {round(Math.min(...values))}{u} · Highest {round(Math.max(...values))}{u} ·
      Average {round(average)}{u} · {points[0].date} to {points[points.length - 1].date}
    </p>
  );
}
