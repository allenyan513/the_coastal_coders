import "@fontsource-variable/bricolage-grotesque";
import "@fontsource-variable/geist";
import "@fontsource-variable/jetbrains-mono";
import "./styles.css";

import { useState } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Link, Route, Routes, useLocation } from "react-router-dom";
import { Accuracy } from "./Accuracy";
import { isLocal } from "./api";
import { Compare } from "./Compare";
import { Library } from "./Library";
import { ModelLab } from "./ModelLab";
import { QrDialog } from "./Qr";
import { Reports } from "./Reports";
import { School } from "./School";
import { Snapshots } from "./Snapshots";
import { Species } from "./Species";
import { Start } from "./Start";
import { SummaryPage } from "./Summary";
import { Tracks } from "./Tracks";
import { Workspace } from "./Workspace";

const ICONS = {
  videos: "M4 5h16v14H4zM4 9h16M9 5v4M15 5v4M10 12.5v4l3.5-2z",
  reports: "M5 20V10M12 20V4M19 20v-7",
  species: "M3 12c3-4 6-6 10-6 3 0 6 2 8 6-2 4-5 6-8 6-4 0-7-2-10-6zM17 10.5v.01M3 8l3 4-3 4",
  accuracy: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 16a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM12 12v.01",
  phone: "M7 3h10a1 1 0 0 1 1 1v16a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1zM11 18h2",
};

function Icon({ name }: { name: keyof typeof ICONS }) {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d={ICONS[name]} />
    </svg>
  );
}

/** TideCount is the workspace and Fish Counter is its first tool. Inside a video the bar shrinks to icons, so the footage keeps its width. On a phone it is a tab bar. */
function Sidebar() {
  const { pathname, search } = useLocation();
  const [sharing, setSharing] = useState(false);
  const inVideo = pathname.startsWith("/videos/");
  // The model lab has no entry here. People reviewing footage don't need it, and AI accuracy links to it.
  const inAccuracy = pathname.startsWith("/accuracy") || pathname.startsWith("/models") || pathname.endsWith("/compare") || search.includes("from=accuracy");
  const items = [
    { to: "/", label: "Videos", icon: "videos" as const, on: (pathname === "/" || inVideo) && !inAccuracy },
    { to: "/reports", label: "Reports", icon: "reports" as const, on: pathname.startsWith("/reports") },
    { to: "/species", label: "Species list", icon: "species" as const, on: pathname.startsWith("/species") },
    { to: "/accuracy", label: "AI accuracy", icon: "accuracy" as const, on: inAccuracy },
  ];
  return (
    <aside className={`side ${inVideo ? "rail" : ""}`}>
      <Link to="/" className="brand" aria-label="TideCount">{inVideo ? "T" : "TideCount"}</Link>
      <nav className="side-nav" aria-label="Fish Counter">
        <p className="side-label">Fish Counter</p>
        {items.map((i) => (
          <Link key={i.to} to={i.to} className="side-link" aria-current={i.on ? "page" : undefined} title={i.label}>
            <Icon name={i.icon} /><span>{i.label}</span>
          </Link>
        ))}
      </nav>
      <button className="side-link side-share" title="Open on your phone" onClick={() => setSharing(true)}>
        <Icon name="phone" /><span>Open on phone</span>
      </button>
      {sharing && <QrDialog onClose={() => setSharing(false)} />}
      {isLocal
        ? <p className="side-foot" title="Local. Nothing leaves this PC."><i />Local<span> · nothing leaves this PC</span></p>
        : <p className="side-foot" title="Public demo. Uploads go to the demo server."><i />Public demo</p>}
    </aside>
  );
}

function Shell() {
  return (
    <div className="shell">
      <Sidebar />
      <main className="page">
        <Routes>
          <Route path="/" element={<Library />} />
          <Route path="/reports" element={<Reports />} />
          <Route path="/species" element={<Species />} />
          <Route path="/models" element={<ModelLab />} />
          <Route path="/accuracy" element={<Accuracy />} />
          <Route path="/videos/:id" element={<Workspace />} />
          <Route path="/videos/:id/tracks" element={<Tracks />} />
          <Route path="/videos/:id/compare" element={<Compare />} />
          <Route path="/videos/:id/school" element={<School />} />
          <Route path="/videos/:id/snapshots" element={<Snapshots />} />
          <Route path="/videos/:id/summary" element={<SummaryPage />} />
        </Routes>
      </main>
    </div>
  );
}

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/start" element={<Start />} />
        <Route path="*" element={<Shell />} />
      </Routes>
    </BrowserRouter>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
