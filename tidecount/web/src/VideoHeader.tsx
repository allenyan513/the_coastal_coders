import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, snapshotApi } from "./api";
import { homeLabel, useUser } from "./session";

type Progress = { done: number; total: number };
type Props = {
  id: string;
  /** The step this page belongs to. Pages outside the three steps pass nothing. */
  step?: "review" | "snapshots" | "report";
  /** Which half of the review step is open. */
  view?: "segments" | "tracks";
  /** Live numbers from the page, so the header moves as soon as work is saved. */
  review?: Progress;
  snapshots?: Progress;
  title?: string;
  /** Where the first crumb leads. The person's home, unless the page belongs to another part of the app. */
  from?: { to: string; label: string };
};

/** One header for every page inside a video: where you are, and the three steps in order. */
export function VideoHeader({ id, step, view, review, snapshots, title, from }: Props) {
  const user = useUser();
  const crumb = from ?? { to: "/", label: homeLabel(user.role) };
  const [name, setName] = useState("");
  const [site, setSite] = useState("");
  const [loaded, setLoaded] = useState<{ review?: Progress; snapshots?: Progress }>({});

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
    return () => { stale = true; };
  }, [id]);

  const r = review ?? loaded.review;
  const s = snapshots ?? loaded.snapshots;
  const steps = [
    { key: "review", to: `/videos/${id}`, label: "Review footage", p: r, unit: "segments" },
    { key: "snapshots", to: `/videos/${id}/snapshots`, label: "Snapshot count", p: s, unit: "frames" },
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
        <nav className="steps" aria-label="Steps for this video">
          {steps.map((x, i) => {
            const finished = !!x.p && x.p.total > 0 && x.p.done >= x.p.total;
            return (
              <Link key={x.key} to={x.to} className="step" aria-current={step === x.key ? "step" : undefined}>
                <b className={finished ? "ok" : ""}>{finished ? "✓" : i + 1}</b>
                <span>{x.label}</span>
                {x.p && x.p.total > 0 && <span className="num meta">{x.p.done}/{x.p.total} {x.unit}</span>}
              </Link>
            );
          })}
        </nav>
        <span className="spacer" />
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
