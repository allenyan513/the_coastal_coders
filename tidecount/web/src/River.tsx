/**
 * River Sensor. Ethan owns this page: the route and the sidebar entry already point here,
 * so charts and the map can replace this placeholder without touching the app shell.
 * The readings come from the water_readings table on the ethan-water-quality branch.
 */
export function River() {
  return (
    <div className="stack" style={{ gap: 20 }}>
      <div>
        <h1>River Sensor</h1>
        <p className="lede">Coastal Action's public river readings, in the same workspace as the fish counts.</p>
      </div>
      <div className="panel river-empty">
        <b>Coming soon</b>
        <p className="meta">Temperature, pH, dissolved oxygen, conductance and salinity from the LaHave River.</p>
      </div>
    </div>
  );
}
