import { useEffect, useLayoutEffect, useState } from "react";
import { Link, useLocation, useNavigate, useNavigationType } from "react-router-dom";
import { homeLabel, Role, useUser } from "./session";

/** The part of the app a page belongs to. Every page inside one video, or one species, is the same section,
 *  so switching tabs inside it never counts as somewhere to go back to. */
function sectionOf(pathname: string) {
  const [first = "", second] = pathname.split("/").filter(Boolean);
  if ((first === "videos" || first === "species") && second) return `${first}/${second}`;
  return first;
}

/** The bottom tab bar's pages. They have no Back: the tabs are how you move between them. */
const TAB_SECTIONS = ["workspace", "workflow", "analysis", "species", "scan", "team", "settings"];

/** Where Back leads when this page was opened straight from a link, with nothing of ours behind it. */
function fallbackOf(section: string) {
  if (section.startsWith("species/")) return "/species";
  if (section === "models") return "/accuracy";
  return "/workspace";
}

function labelOf(section: string, role: Role) {
  if (section.startsWith("videos/")) return "Video";
  if (section.startsWith("species/")) return decodeURIComponent(section.slice("species/".length));
  const labels: Record<string, string> = {
    workspace: homeLabel(role), workflow: "Workflow", analysis: "Analysis",
    species: "Species", scan: "Fish Scan", team: "Team", settings: "Settings", models: "Model lab", accuracy: "AI accuracy",
  };
  return labels[section] ?? "Back";
}

type Entry = { section: string; path: string };
const KEY = "tideflow.trail";

/** The pages visited in this tab, by their place in the browser history. It survives a reload,
 *  because the browser keeps its history position across one. */
function readTrail(): Record<number, Entry> {
  try { return JSON.parse(sessionStorage.getItem(KEY) || "{}"); } catch { return {}; }
}
function saveTrail(trail: Record<number, Entry>) {
  try { sessionStorage.setItem(KEY, JSON.stringify(trail)); } catch { /* private mode: Back falls back to the section's home */ }
}
const historyIdx = () => (window.history.state?.idx as number | undefined) ?? 0;

/** The page's own title element, which the bar repeats once it has scrolled away. */
const TITLE = "h1, .vhead-name, #drawer-title";

/** A phone's top bar. It holds Back on pages below the tabs, and the page's title once its own heading
 *  has scrolled out of sight, so you always know where you are and how to get out. Hidden above phone width. */
export function TopBar() {
  const user = useUser();
  const navigate = useNavigate();
  const navType = useNavigationType();
  const { pathname, search } = useLocation();
  const section = sectionOf(pathname);
  const [back, setBack] = useState<{ delta?: number; to: string; label: string } | null>(null);
  const [title, setTitle] = useState("");
  const [scrolled, setScrolled] = useState(false);
  const [showTitle, setShowTitle] = useState(false);

  // Record this page against its history position, then work out where Back goes from here.
  useLayoutEffect(() => {
    const idx = historyIdx();
    const trail = readTrail();
    if (navType === "PUSH") Object.keys(trail).forEach((k) => { if (Number(k) > idx) delete trail[Number(k)]; });
    trail[idx] = { section, path: pathname + search };
    saveTrail(trail);

    if (TAB_SECTIONS.includes(section)) return setBack(null);
    // The closest page behind this one that is somewhere else: another video, the list it was opened from.
    for (let i = idx - 1; i >= 0; i--) {
      const e = trail[i];
      if (!e) break;
      if (e.section !== section) return setBack({ delta: i - idx, to: e.path, label: labelOf(e.section, user.role) });
    }
    const to = fallbackOf(section);
    setBack({ to, label: labelOf(sectionOf(to), user.role) });
  }, [pathname, search, section, navType, user.role]);

  // Follow the page's heading: the bar shows the title only after the heading is out of sight.
  useEffect(() => {
    let frame = 0;
    const check = () => {
      frame = 0;
      const bar = document.querySelector(".topbar");
      const el = document.querySelector<HTMLElement>(`.page :is(${TITLE})`);
      const barBottom = bar?.getBoundingClientRect().bottom ?? 0;
      setScrolled(window.scrollY > 2);
      setTitle(el?.textContent?.trim() ?? "");
      setShowTitle(!!el && el.getBoundingClientRect().bottom <= barBottom);
    };
    const queue = () => { if (!frame) frame = requestAnimationFrame(check); };
    check();
    // Pages load their data after they mount, so the heading can appear or change after this runs.
    const page = document.querySelector(".page");
    const watch = new MutationObserver(queue);
    if (page) watch.observe(page, { childList: true, subtree: true, characterData: true });
    window.addEventListener("scroll", queue, { passive: true });
    window.addEventListener("resize", queue);
    return () => {
      cancelAnimationFrame(frame);
      watch.disconnect();
      window.removeEventListener("scroll", queue);
      window.removeEventListener("resize", queue);
    };
  }, [pathname]);

  const goBack = () => {
    if (!back) return;
    if (back.delta) navigate(back.delta);
    else navigate(back.to);
  };

  return (
    <header className={`topbar ${scrolled ? "scrolled" : ""}`}>
      <div className="topbar-side">
        {back ? (
          <button type="button" className="topbar-back" onClick={goBack} aria-label={`Back to ${back.label}`}>
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden><path d="M15 5l-7 7 7 7" /></svg>
            <span>{back.label}</span>
          </button>
        ) : (
          <Link to="/workspace" className="topbar-brand" aria-label="Tideflow"><img src="/favicon.svg" alt="" />Tideflow</Link>
        )}
      </div>
      <p className={`topbar-title ${showTitle ? "on" : ""}`} aria-hidden={!showTitle}>{title}</p>
      <div className="topbar-side" />
    </header>
  );
}
