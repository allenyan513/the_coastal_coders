import { Link, Navigate } from "react-router-dom";
import { Reports } from "./Reports";
import { River } from "./River";
import { useUser } from "./session";

type Tab = "stations" | "trends";

/**
 * Data analysis: the Station report and the Fish and water trends, as two tabs under one sidebar entry.
 * They stay separate pages because they answer different questions from different data: the Station
 * report compares survey stations season by season (managers only), and Fish and water follows fish
 * over the years next to Coastal Action's water readings (everyone).
 */
export function Analysis({ tab }: { tab: Tab }) {
  const manager = useUser().role === "manager";
  const tabs = [
    ...(manager ? [{ key: "stations" as const, to: "/analysis/stations", label: "Station report" }] : []),
    { key: "trends" as const, to: "/analysis/trends", label: "Fish and water" },
  ];
  return (
    <div className="stack" style={{ gap: 20 }}>
      <div>
        <p style={{ marginBottom: 6, font: "500 12px var(--mono)", letterSpacing: ".3px", textTransform: "uppercase", color: "var(--muted)" }}>Data analysis</p>
        <nav className="tabs" aria-label="Data analysis" style={{ overflowY: "hidden" }}>
          {tabs.map((t) => (
            <Link key={t.key} to={t.to} className="tab" aria-current={tab === t.key ? "page" : undefined}>{t.label}</Link>
          ))}
        </nav>
      </div>
      {tab === "stations" ? <Reports /> : <River />}
    </div>
  );
}

/** /analysis on its own: managers start on the Station report, volunteers on Fish and water. */
export function AnalysisHome() {
  return <Navigate to={useUser().role === "manager" ? "/analysis/stations" : "/analysis/trends"} replace />;
}