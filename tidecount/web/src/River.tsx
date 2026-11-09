import { ReactNode, useEffect, useState } from "react";
import { api, FishOptions, FishSeries, FishWaterComparison, VideoLinks, WaterSeries, WaterSite } from "./api";
import { CompareChart } from "./CompareChart";
import { WaterChart } from "./WaterChart";
import { WqiTable } from "./WqiTable";

/** The measurements Coastal Action takes on site, as named in their data. Matches KEEP in server/tidecount/water.py. */
const MEASUREMENTS = [
  "Dissolved oxygen (DO)",
  "Dissolved oxygen saturation",
  "Temperature, water",
  "pH",
  "Specific conductance",
  "Salinity",
];

/** What the chart shows: the water line, the fish line, or both on one scale with their correlation. */
type View = "water" | "fish" | "both";
const VIEWS: { key: View; label: string }[] = [
  { key: "water", label: "Water" },
  { key: "fish", label: "Fish" },
  { key: "both", label: "Both" },
];

type Point = { date: string; value: number };

/** A word with a dotted underline that explains itself on hover, so the page doesn't need paragraphs of explanation. */
function Hint({ tip, children }: { tip: string; children: ReactNode }) {
  return <span title={tip} style={{ textDecoration: "underline dotted", textUnderlineOffset: 3, cursor: "help" }}>{children}</span>;
}

/**
 * Fish and water trends. Ethan owns this page.
 * Fish counts come from the fish_counts table (server/tidecount/trends.py), which holds made-up demo
 * data for now. Water readings come from the water_readings table, imported by server/tidecount/water.py.
 */
export function River() {
  const [sites, setSites] = useState<WaterSite[]>([]);
  const [siteId, setSiteId] = useState("1");
  const [view, setView] = useState<View>("both");
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

  const hasFish = !!fish && fish.points.length > 0;
  const siteName = sites.find((s) => s.site_id === siteId)?.site_name ?? "this site";
  const showFish = view !== "water";
  const showWater = view !== "fish";
  const seasonal = deseason ? ", seasonal pattern removed" : "";
  const title = view === "both" ? "Fish and water together" : view === "fish" ? `Fish: ${fish?.label ?? ""}` : `Water: ${measurement}${data?.unit ? ` (${data.unit})` : ""}`;

  return (
    <div className="stack" style={{ gap: 20 }}>
      <div>
        <h1>Fish and water trends</h1>
        <p className="lede">How fish counts change over time, next to Coastal Action's water readings.</p>
      </div>

      <section className="panel panel-pad">
        <WqiTable onPickSite={(id) => { setSiteId(id); document.getElementById("site-charts")?.scrollIntoView({ behavior: "smooth" }); }} />
      </section>

      <div id="site-charts" className="row" style={{ gap: 16, flexWrap: "wrap", alignItems: "flex-end" }}>
        <label className="field">Site
          <select value={siteId} onChange={(e) => setSiteId(e.target.value)}>
            {sites.map((s) => <option key={s.site_id} value={s.site_id}>{s.site_name}</option>)}
          </select>
        </label>
        <div className="field">Show
          <div className="seg" role="group" aria-label="Show">
            {VIEWS.map((v) => (
              <button key={v.key} type="button" aria-pressed={view === v.key} onClick={() => setView(v.key)}>{v.label}</button>
            ))}
          </div>
        </div>
        <label style={{ paddingBottom: 9 }} title="Takes out each calendar month's usual level, so year-to-year change is easier to see">
          <input type="checkbox" checked={deseason} onChange={(e) => setDeseason(e.target.checked)} />{" "}
          Remove seasonal pattern
        </label>
      </div>

      <section className="panel panel-pad stack" style={{ gap: 12 }}>
        <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-end", gap: 12, flexWrap: "wrap" }}>
          <h2 title={view === "both" ? "Both lines on one scale: how far each is above or below its own usual level" : undefined}>{title}{seasonal}</h2>
          <div className="row" style={{ gap: 12, flexWrap: "wrap" }}>
            {showFish && fishOptions && (
              <label className="field">Fish measure
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
            {showWater && (
              <label className="field">Water measure
                <select value={measurement} onChange={(e) => setMeasurement(e.target.value)}>
                  {MEASUREMENTS.map((name) => <option key={name} value={name}>{name}</option>)}
                </select>
              </label>
            )}
          </div>
        </div>

        {showFish && fish?.demo && (
          <p className="demo-flag" style={{ background: "var(--warn-soft)", color: "var(--down-ink)", padding: "6px 10px", borderRadius: 6, fontSize: 13 }}>
            <b>Demo data.</b> These fish counts are made up to show how trends will look.
          </p>
        )}
        {showFish && fish && !hasFish && <p className="meta">No fish counts at {siteName} yet.</p>}

        {view === "both" && hasFish && comparison && (
          <>
            <CorrelationLine c={comparison} />
            <CompareChart fish={comparison.fish} water={comparison.water} />
          </>
        )}
        {view === "fish" && hasFish && (
          <>
            <Summary points={fish.points} unit={fish.unit} what="surveys" />
            <WaterChart points={fish.points} label={fish.label} unit={fish.unit} />
          </>
        )}
        {view === "water" && !data && <p className="meta">Loading…</p>}
        {view === "water" && data && (
          <>
            <Summary points={data.points} unit={data.unit} what="readings" />
            <WaterChart points={data.points} label={measurement} unit={data.unit} />
          </>
        )}

        {showFish && fishOptions && <VideoLinkList links={fishOptions.videos} siteId={siteId} />}
        {showWater && (
          <p className="meta" style={{ borderTop: "1px solid var(--border-2)", paddingTop: 8 }}
            title="Readings outside sensible limits are left out, and 739 conductance readings at salty sites labelled uS/cm were really mS/cm, so they were multiplied by 1,000.">
            Data: Coastal Action,{" "}
            <a href="https://doi.org/10.25976/r245-z904" target="_blank" rel="noreferrer">LaHave River Water Quality Monitoring</a>
            {" "}(DataStream), ODC-By.
          </p>
        )}
      </section>
    </div>
  );
}

/** The correlation in numbers and words, such as "ρ = +0.62, strong positive, 120 pairs, p < 0.001". Hover a label to see what it means. */
function CorrelationLine({ c }: { c: FishWaterComparison }) {
  if (c.spearman === null) {
    return <p className="meta">Not enough fish surveys with a water reading within {c.max_gap_days} days to work out a correlation.</p>;
  }
  const rho = `${c.spearman >= 0 ? "+" : "−"}${Math.abs(c.spearman).toFixed(2)}`;
  const p = c.p_value === null ? "" : c.p_value < 0.001 ? "p < 0.001" : `p = ${c.p_value.toFixed(3)}`;
  return (
    <div className="row" style={{ gap: 20, flexWrap: "wrap", alignItems: "baseline" }}>
      <div>
        <span className="meta"><Hint tip="Spearman correlation, from −1 to +1: how closely fish and water move together. 0 means no relationship. It shows they move together, not that one causes the other.">Correlation</Hint></span>
        <div style={{ fontSize: 22, fontWeight: 600 }} className="num">ρ = {rho}</div>
      </div>
      <div><span className="meta">Strength</span><div style={{ fontSize: 15, fontWeight: 500 }}>{c.strength}</div></div>
      <div>
        <span className="meta"><Hint tip={`Fish surveys paired with the water reading closest in time, within ${c.max_gap_days} days`}>Pairs</Hint></span>
        <div className="num" style={{ fontSize: 15 }}>{c.pairs}</div>
      </div>
      {p && (
        <div className="num meta" style={{ fontSize: 15 }}>
          <Hint tip="The p-value: how likely a result this strong would be by chance alone. Smaller is more convincing.">{p}</Hint>
        </div>
      )}
    </div>
  );
}

/** Which reviewed videos give fish counts at this site, and, folded away, why other videos don't count anywhere. */
function VideoLinkList({ links, siteId }: { links: VideoLinks; siteId: string }) {
  const here = links.linked.filter((l) => l.site_id === siteId);
  if (here.length === 0 && links.not_linked.length === 0) return null;
  return (
    <details className="meta" style={{ lineHeight: 1.6 }}>
      <summary>
        {here.length === 0 ? "No reviewed videos from this site yet" : `${here.length} reviewed video${here.length === 1 ? "" : "s"} from this site`}
        {links.not_linked.length > 0 && ` · ${links.not_linked.length} video${links.not_linked.length === 1 ? "" : "s"} not counted`}
      </summary>
      <p style={{ margin: "6px 0" }}>A video counts when it was filmed within {links.match_km} km of a water sampling site.</p>
      {here.length > 0 && (
        <ul style={{ margin: "4px 0" }}>
          {here.map((l) => <li key={l.video + l.date}>{l.video}: filmed {l.date}, {l.km} km from the water site</li>)}
        </ul>
      )}
      {links.not_linked.length > 0 && (
        <>
          <b>Not counted</b>
          <ul style={{ margin: "4px 0" }}>
            {links.not_linked.map((n) => <li key={n.video}>{n.video}: {n.reason}</li>)}
          </ul>
        </>
      )}
    </details>
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
