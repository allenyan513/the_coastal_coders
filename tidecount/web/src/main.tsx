import "@fontsource-variable/bricolage-grotesque";
import "@fontsource-variable/geist";
import "@fontsource-variable/jetbrains-mono";
import "./styles.css";

import { ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Link, Navigate, Route, Routes, useLocation, useSearchParams } from "react-router-dom";
import { Accuracy } from "./Accuracy";
import { Analyse, MyTasks } from "./Board";
import { Compare } from "./Compare";
import { Library } from "./Library";
import { Login } from "./Login";
import { ModelLab } from "./ModelLab";
import { Reports } from "./Reports";
import { River } from "./River";
import { School } from "./School";
import { homeLabel, SessionProvider, useSession, useUser } from "./session";
import { Settings } from "./Settings";
import { Snapshots } from "./Snapshots";
import { Species } from "./Species";
import { Start } from "./Start";
import { SummaryPage } from "./Summary";
import { Team } from "./Team";
import { Tracks } from "./Tracks";
import { Workspace } from "./Workspace";

const ICONS = {
  videos: "M4 5h16v14H4zM4 9h16M9 5v4M15 5v4M10 12.5v4l3.5-2z",
  tasks: "M9 6h11M9 12h11M9 18h11M4 6l1 1 2-2M4 12l1 1 2-2M4 18l1 1 2-2",
  board: "M4 5h4v14H4zM10 5h4v9h-4zM16 5h4v6h-4z",
  reports: "M5 20V10M12 20V4M19 20v-7",
  species: "M3 12c3-4 6-6 10-6 3 0 6 2 8 6-2 4-5 6-8 6-4 0-7-2-10-6zM17 10.5v.01M3 8l3 4-3 4",
  river: "M3 8c3-2 6-2 9 0s6 2 9 0M3 13c3-2 6-2 9 0s6 2 9 0M3 18c3-2 6-2 9 0s6 2 9 0",
  team: "M16 20v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M9 10a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM22 20v-2a4 4 0 0 0-3-3.9M16 2.1a4 4 0 0 1 0 7.8",
  settings: "M4 7h10M18 7h2M4 17h2M10 17h10M16 5v4M8 15v4",
};

function Icon({ name }: { name: keyof typeof ICONS }) {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d={ICONS[name]} />
    </svg>
  );
}

/** What the bar offers depends on the signed-in role. Inside a video it shrinks to icons, so the footage keeps its width. On a phone it is a tab bar. */
function Sidebar() {
  const user = useUser();
  const manager = user.role === "manager";
  const { pathname, search } = useLocation();
  const inVideo = pathname.startsWith("/videos/");
  // The model lab and AI accuracy have no entry here. People following the procedure don't need them,
  // and both still open from their own addresses for anyone tuning Tideflow.
  const inAccuracy = pathname.startsWith("/accuracy") || pathname.startsWith("/models") || pathname.endsWith("/compare") || search.includes("from=accuracy");
  const items = [
    { to: "/", label: homeLabel(user.role), icon: manager ? "videos" as const : "tasks" as const, on: (pathname === "/" || inVideo) && !inAccuracy },
    { to: "/analyse", label: "Analyse", icon: "board" as const, on: pathname.startsWith("/analyse") },
    ...(manager ? [{ to: "/reports", label: "Reports", icon: "reports" as const, on: pathname.startsWith("/reports") }] : []),
    { to: "/species", label: "Species wiki", icon: "species" as const, on: pathname.startsWith("/species") },
    { to: "/river", label: "Fish and water trends", icon: "river" as const, on: pathname.startsWith("/river") },
    ...(manager ? [{ to: "/team", label: "Team", icon: "team" as const, on: pathname.startsWith("/team") }] : []),
  ];
  return (
    <aside className={`side ${inVideo ? "rail" : ""}`}>
      <Link to="/" className="brand" aria-label="Tideflow"><img src="/favicon.svg" alt="" />{!inVideo && "Tideflow"}</Link>
      <nav className="side-nav" aria-label="Workspace">
        <p className="side-label">Workspace</p>
        {items.map((i) => (
          <Link key={i.to} to={i.to} className="side-link" aria-current={i.on ? "page" : undefined} title={i.label}>
            <Icon name={i.icon} /><span>{i.label}</span>
          </Link>
        ))}
        <Link to="/settings" className="side-link side-settings" aria-current={pathname.startsWith("/settings") ? "page" : undefined} title="Settings">
          <Icon name="settings" /><span>Settings</span>
        </Link>
      </nav>
    </aside>
  );
}

/** Volunteers open their tasks and managers open the surveys. The QR page's upload link stays open to both. */
function Home() {
  const user = useUser();
  const [params] = useSearchParams();
  return user.role === "manager" || params.has("import") ? <Library /> : <MyTasks />;
}

function ManagerOnly({ children }: { children: ReactNode }) {
  return useUser().role === "manager" ? children : <Navigate to="/" replace />;
}

function Shell() {
  const { user } = useSession();
  const { pathname, search } = useLocation();
  if (!user) return <Navigate to={`/login?next=${encodeURIComponent(pathname + search)}`} replace />;
  return (
    <div className="shell">
      <Sidebar />
      <main className="page">
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/analyse" element={<Analyse />} />
          <Route path="/reports" element={<ManagerOnly><Reports /></ManagerOnly>} />
          <Route path="/species" element={<Species />} />
          <Route path="/river" element={<River />} />
          <Route path="/team" element={<ManagerOnly><Team /></ManagerOnly>} />
          <Route path="/settings" element={<Settings />} />
          <Route path="/models" element={<ManagerOnly><ModelLab /></ManagerOnly>} />
          <Route path="/accuracy" element={<ManagerOnly><Accuracy /></ManagerOnly>} />
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
    <SessionProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/start" element={<Start />} />
          <Route path="/login" element={<Login />} />
          <Route path="*" element={<Shell />} />
        </Routes>
      </BrowserRouter>
    </SessionProvider>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
