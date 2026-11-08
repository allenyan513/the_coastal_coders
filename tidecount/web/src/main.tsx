import "@fontsource-variable/bricolage-grotesque";
import "@fontsource-variable/geist";
import "@fontsource-variable/jetbrains-mono";
import "./styles.css";

import { ReactNode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Link, Navigate, Route, Routes, useLocation, useSearchParams } from "react-router-dom";
import { Accuracy } from "./Accuracy";
import { Analysis, AnalysisHome } from "./Analysis";
import { MyTasks, Workflow } from "./Board";
import { Compare } from "./Compare";
import { Library } from "./Library";
import { Login } from "./Login";
import { ModelLab } from "./ModelLab";
import { School } from "./School";
import { homeLabel, SessionProvider, useSession, useUser } from "./session";
import { Landing } from "./Landing";
import { Settings } from "./Settings";
import { Snapshots } from "./Snapshots";
import { Species } from "./Species";
import { SpeciesPage } from "./SpeciesPage";
import { SummaryPage } from "./Summary";
import { Team } from "./Team";
import { TopBar } from "./TopBar";
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
  more: "M3.5 12a1.5 1.5 0 1 0 3 0a1.5 1.5 0 1 0-3 0M10.5 12a1.5 1.5 0 1 0 3 0a1.5 1.5 0 1 0-3 0M17.5 12a1.5 1.5 0 1 0 3 0a1.5 1.5 0 1 0-3 0",
};

function Icon({ name }: { name: keyof typeof ICONS }) {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d={ICONS[name]} />
    </svg>
  );
}

type NavItem = { to: string; label: string; short: string; icon: keyof typeof ICONS; on: boolean; more?: boolean; className?: string };

/** The phone's More tab. It lists the pages that don't fit in the tab bar and closes on Escape, a tap outside or a new page. */
function MoreTab({ items }: { items: NavItem[] }) {
  const [open, setOpen] = useState(false);
  const { pathname } = useLocation();
  useEffect(() => setOpen(false), [pathname]);
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);
  if (!items.length) return null;
  return (
    <>
      <button type="button" className="side-link side-more" aria-haspopup="menu" aria-expanded={open} aria-current={items.some((i) => i.on) ? "page" : undefined} onClick={() => setOpen(!open)}>
        <Icon name="more" /><span>More</span>
      </button>
      {open && (
        <div className="more-back" onClick={() => setOpen(false)}>
          <div className="more-sheet" role="menu" aria-label="More pages" onClick={(e) => e.stopPropagation()}>
            {items.map((i) => (
              <Link key={i.to} to={i.to} role="menuitem" className="more-link" aria-current={i.on ? "page" : undefined}>
                <Icon name={i.icon} />{i.label}
              </Link>
            ))}
          </div>
        </div>
      )}
    </>
  );
}

/** What the bar offers depends on the signed-in role. Inside a video it shrinks to icons, so the footage keeps its width.
 *  On a phone it is a tab bar with short labels and at most five tabs. Pages marked `more` move into the More tab there. */
function Sidebar() {
  const user = useUser();
  const manager = user.role === "manager";
  const { pathname, search } = useLocation();
  const inVideo = pathname.startsWith("/videos/");
  // The model lab and AI accuracy have no entry here. People following the procedure don't need them,
  // and both still open from their own addresses for anyone tuning Tideflow.
  const inAccuracy = pathname.startsWith("/accuracy") || pathname.startsWith("/models") || pathname.endsWith("/compare") || search.includes("from=accuracy");
  const items: NavItem[] = [
    { to: "/workspace", label: homeLabel(user.role), short: homeLabel(user.role), icon: manager ? "videos" : "tasks", on: (pathname === "/workspace" || inVideo) && !inAccuracy },
    { to: "/workflow", label: "Workflow", short: "Workflow", icon: "board", on: pathname.startsWith("/workflow") },
    { to: "/analysis", label: "Data analysis", short: "Analysis", icon: "reports", on: pathname.startsWith("/analysis") },
    { to: "/species", label: "Species wiki", short: "Species", icon: "species", on: pathname.startsWith("/species"), more: manager },
    ...(manager ? [{ to: "/team", label: "Team", short: "Team", icon: "team" as const, on: pathname.startsWith("/team"), more: true }] : []),
    { to: "/settings", label: "Settings", short: "Settings", icon: "settings", on: pathname.startsWith("/settings"), more: manager, className: "side-settings" },
  ];
  return (
    <aside className={`side ${inVideo ? "rail" : ""}`}>
      <Link to="/workspace" className="brand" aria-label="Tideflow"><img src="/favicon.svg" alt="" />{!inVideo && "Tideflow"}</Link>
      <nav className="side-nav" aria-label="Workspace">
        <p className="side-label">Workspace</p>
        {items.map((i) => (
          <Link key={i.to} to={i.to} className={`side-link ${i.more ? "in-more" : ""} ${i.className ?? ""}`} aria-current={i.on ? "page" : undefined} title={i.label}>
            <Icon name={i.icon} /><span className="side-full">{i.label}</span><span className="side-short">{i.short}</span>
          </Link>
        ))}
        <MoreTab items={items.filter((i) => i.more)} />
      </nav>
    </aside>
  );
}

/** Volunteers open their tasks and managers open the surveys. The front page's upload link stays open to both. */
function Home() {
  const user = useUser();
  const [params] = useSearchParams();
  return user.role === "manager" || params.has("import") ? <Library /> : <MyTasks />;
}

function ManagerOnly({ children }: { children: ReactNode }) {
  return useUser().role === "manager" ? children : <Navigate to="/workspace" replace />;
}

function Shell() {
  const { user } = useSession();
  const { pathname, search } = useLocation();
  if (!user) return <Navigate to={`/login?next=${encodeURIComponent(pathname + search)}`} replace />;
  return (
    <div className="shell">
      <Sidebar />
      <TopBar />
      <main className="page">
        <Routes>
          <Route path="/workspace" element={<Home />} />
          <Route path="/workflow" element={<Workflow />} />
          <Route path="/analyse" element={<Navigate to="/workflow" replace />} />
          <Route path="/analysis" element={<AnalysisHome />} />
          <Route path="/analysis/stations" element={<ManagerOnly><Analysis tab="stations" /></ManagerOnly>} />
          <Route path="/analysis/trends" element={<Analysis tab="trends" />} />
          {/* The old addresses of the two tabs still work. */}
          <Route path="/reports" element={<Navigate to="/analysis/stations" replace />} />
          <Route path="/river" element={<Navigate to="/analysis/trends" replace />} />
          <Route path="/species" element={<Species />} />
          <Route path="/species/:name" element={<SpeciesPage />} />
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
          <Route path="/" element={<Landing />} />
          {/* The underwater-footer front page was tested here before it replaced / (issue #50). */}
          <Route path="/homepage_v2" element={<Navigate to="/" replace />} />
          {/* Old QR codes and links still lead somewhere. */}
          <Route path="/start" element={<Navigate to="/" replace />} />
          <Route path="/login" element={<Login />} />
          <Route path="*" element={<Shell />} />
        </Routes>
      </BrowserRouter>
    </SessionProvider>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
