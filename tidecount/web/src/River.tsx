import { useEffect, useState } from "react";
import { api, WaterSeries, WaterSite } from "./api";
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

/**
 * Fish and water trends. Ethan owns this page: the route and the sidebar entry already point here.
 * The readings come from the water_readings table, imported by server/tidecount/water.py.
 */
export function River() {
  const [sites, setSites] = useState<WaterSite[]>([]);
  const [siteId, setSiteId] = useState("1");
  const [measurement, setMeasurement] = useState("Dissolved oxygen (DO)");
  const [data, setData] = useState<WaterSeries | null>(null);

  // Load the sites once, when the page opens.
  useEffect(() => { api.waterSites().then(setSites); }, []);

  // Load the readings whenever the site or the measurement changes.
  useEffect(() => { api.waterSeries(siteId, measurement).then(setData); }, [siteId, measurement]);

  // Summary numbers for the chosen series.
  const values = data ? data.points.map((p) => p.value) : [];
  const lowest = Math.min(...values);
  const highest = Math.max(...values);
  const average = values.reduce((total, v) => total + v, 0) / values.length;
  const unitText = data?.unit ? ` ${data.unit}` : "";
  const round = (v: number) => String(Number(v.toFixed(2)));

  return (
    <div className="stack" style={{ gap: 20 }}>
      <div>
        <h1>Fish and water trends</h1>
        <p className="lede">How fish counts change over time, next to Coastal Action's water readings from the LaHave River.</p>
        <p className="meta">Fish trends will appear here once videos are linked to a sampling site and date.</p>
      </div>

      <div className="row" style={{ gap: 12 }}>
        <label>
          Site{" "}
          <select value={siteId} onChange={(e) => setSiteId(e.target.value)}>
            {sites.map((s) => <option key={s.site_id} value={s.site_id}>{s.site_name}</option>)}
          </select>
        </label>
        <label>
          Measurement{" "}
          <select value={measurement} onChange={(e) => setMeasurement(e.target.value)}>
            {MEASUREMENTS.map((name) => <option key={name} value={name}>{name}</option>)}
          </select>
        </label>
      </div>

      <section className="panel panel-pad">
        <h2>{measurement}{data?.unit ? ` (${data.unit})` : ""}</h2>
        <p className="meta">{data ? `${data.points.length} readings` : "Loading…"}</p>
        {data && values.length > 0 && (
          <p className="meta num">
            Lowest {round(lowest)}{unitText} · Highest {round(highest)}{unitText} · Average {round(average)}{unitText}
            {" "}· {data.points[0].date} to {data.points[data.points.length - 1].date}
          </p>
        )}
        {data && <WaterChart points={data.points} label={measurement} unit={data.unit} />}
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