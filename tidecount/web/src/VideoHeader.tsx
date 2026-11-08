import { ReactNode, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, snapshotApi, validationApi } from "./api";
import { homeLabel, useUser } from "./session";

type Progress = { done: number; total: number };
type Props = {
  id: string;
  /** The tab this page belongs to. Pages outside the tabs pass nothing. */
  step?: "review" | "snapshots" | "validate" | "report";
  /** Which half of the review step is open. */
  view?: "segments" | "tracks";
  /** Live numbers from the page, so the header moves as soon as work is saved. */
  review?: Progress;
  snapshots?: Progress;
  validate?: Progress;
  title?: string;
  /** Where the first crumb leads. The person's home, unless the page belongs to another part of the app. */
  from?: { to: string; label: string };
  /** Page tools that sit on the tab row, at its right end. */
  actions?: ReactNode;
};

/** One header for every page inside a video: where you are, and the tabs for this video. */
export function VideoHeader({ id, step, view, review, snapshots, validate, title, from, actions }: Props) {
  const user = useUser();
  const crumb = from ?? { to: "/workspace", label: homeLabel(user.role) };
  const [name, setName] = useState("");
  const [site, setSite] = useState("");
  const [loaded, setLoaded] = useState<{ review?: Progress; snapshots?: Progress; validate?: Progress }>({});

  useEffect(() => {
    let stale = false;
    api.video(id).then((v) => {
      if (stale) return;
      setName(v.name);
      setSite(v.site);
      const queue = v.segments.filter((s) => s.status !== "skipped");
      setLoaded((l) => ({ ...l, review: { done: queue.filter((s) => s.status !== "needs_review").length, total: queue.length } }));
    }).catch(() => {});
    snapshotApi.list(id).then((l) => {
      if (!stale) setLoaded((x) => ({ ...x, snapshots: { done: l.stats.frames_done, total: l.stats.frames_total } }));
    }).catch(() => {});
    validationApi.report(id).then((r) => {
      if (!stale && r.ready) setLoaded((x) => ({ ...x, validate: { done: r.points.filter((p) => p.state === "agree").length, total: r.points.length } }));
    }).catch(() => {});
    return () => { stale = true; };
  }, [id]);

  const r = review ?? loaded.review;
  const s = snapshots ?? loaded.snapshots;
  const val = validate ?? loaded.validate;
  // Add a tab here and it shows up on every video page.
  const tabs = [
    { key: "review", to: `/videos/${id}`, label: "Identify", p: r, unit: "segments reviewed" },
    { key: "snapshots", to: `/videos/${id}/snapshots`, label: "Count", p: s, unit: "points counted" },
    { key: "validate", to: `/videos/${id}/validate`, label: "Validate", p: val, unit: "sampled points agree" },
    { key: "report", to: `/videos/${id}/summary`, label: "Report", p: undefined, unit: "" },
  ];

  return (
    <header className="vhead">
      <div className="row">
        <Link className="crumb" to={crumb.to}>{crumb.label}</Link>
        <span className="crumb-sep">/</span>
        <h2 className="vhead-name">{name || "…"}</h2>
        {site && <span className="meta">{site}</span>}
        {title && <span className="pill muted">{title}</span>}
      </div>
      <div className="row">
        <nav className="tabs" aria-label="Video tabs">
          {tabs.map((x) => {
            const finished = !!x.p && x.p.total > 0 && x.p.done >= x.p.total;
            return (
              <Link key={x.key} to={x.to} className="tab" aria-current={step === x.key ? "page" : undefined}>
                {x.label}
                {x.p && x.p.total > 0 && (
                  <span className={`tab-count num ${finished ? "ok" : ""}`} title={`${x.p.done} of ${x.p.total} ${x.unit}`}>
                    {finished ? "✓" : `${x.p.done}/${x.p.total}`}
                  </span>
                )}
              </Link>
            );
          })}
        </nav>
        <span className="spacer" />
        {actions}
        {step === "review" && view && (
          <div className="seg" role="group" aria-label="Review by">
            <Link to={`/videos/${id}`} aria-current={view === "segments" ? "page" : undefined}>By segment</Link>
            <Link to={`/videos/${id}/tracks`} aria-current={view === "tracks" ? "page" : undefined}>All tracks</Link>
          </div>
        )}
      </div>
    </header>
  );
}
