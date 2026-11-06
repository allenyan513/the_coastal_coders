import { MouseEvent, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api, clock, Dot, SchoolCount } from "./api";

export function School() {
  const { id = "" } = useParams();
  const [search] = useSearchParams();
  const navigate = useNavigate();
  const t = Number(search.get("t") ?? 0);
  const back = `/videos/${id}?seg=${search.get("seg") ?? ""}`;
  const [count, setCount] = useState<SchoolCount | null>(null);
  const [dots, setDots] = useState<Dot[]>([]);
  const [removed, setRemoved] = useState(0);
  const [showDots, setShowDots] = useState(true);
  const [showGrid, setShowGrid] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    api.startSchool(id, t).then((c) => { setCount(c); setDots(c.dots); }).catch((e) => setError(e.message));
  }, [id, t]);

  const cells = useMemo(() => {
    const out = Array(15).fill(0);
    dots.forEach((d) => { out[Math.min(2, Math.floor(d.y * 3)) * 5 + Math.min(4, Math.floor(d.x * 5))] += 1; });
    return out;
  }, [dots]);

  const add = (e: MouseEvent<HTMLDivElement>) => {
    const box = e.currentTarget.getBoundingClientRect();
    setDots([...dots, { x: (e.clientX - box.left) / box.width, y: (e.clientY - box.top) / box.height, source: "user" }]);
  };
  const remove = (i: number) => {
    if (dots[i].source === "ai") setRemoved(removed + 1);
    setDots(dots.filter((_, n) => n !== i));
  };
  const save = async () => {
    if (!count) return;
    await api.saveSchool(count.id, dots, removed);
    navigate(back);
  };

  if (error) return <p className="meta">{error}</p>;
  if (!count) return <p className="meta">Freezing the frame and asking AI for dots…</p>;

  return (
    <div className="stack">
      <div className="row">
        <Link className="btn" to={back}>← Back to video</Link>
        <h2>School count</h2>
        <span className="num meta">Frozen at {clock(t)}</span>
      </div>
      <div className="split">
        <div className="stage" style={{ cursor: "crosshair" }} onClick={add}>
          <img src={`/api/school-counts/${count.id}/frame`} alt="Frozen video frame" draggable={false} />
          {showGrid && <div className="gridlines">{cells.map((n, i) => <div key={i}><span>{n}</span></div>)}</div>}
          {showDots && dots.map((d, i) => (
            <button
              key={i}
              className={`dot ${d.source}`}
              style={{ left: `${d.x * 100}%`, top: `${d.y * 100}%` }}
              aria-label={`Remove dot ${i + 1}`}
              onClick={(e) => { e.stopPropagation(); remove(i); }}
            />
          ))}
        </div>
        <aside className="stack">
          <div className="panel" style={{ padding: 16 }}>
            <span className="meta">Total in this frame</span>
            <div className="num" style={{ fontSize: 32, fontWeight: 600, letterSpacing: "-.8px", marginTop: 6 }}>{dots.length}</div>
            <div className="stack" style={{ gap: 6, marginTop: 16, fontSize: 13 }}>
              <div className="row" style={{ justifyContent: "space-between" }}><span>AI proposed</span><span className="num">{count.dots.length}</span></div>
              <div className="row" style={{ justifyContent: "space-between" }}><span>You removed</span><span className="num">{removed}</span></div>
              <div className="row" style={{ justifyContent: "space-between" }}><span>You added</span><span className="num">{dots.filter((d) => d.source === "user").length}</span></div>
            </div>
          </div>
          <div className="panel panel-pad">
            <div className="row">
              <button className="chip" aria-pressed={showDots} onClick={() => setShowDots(!showDots)}>Dots</button>
              <button className="chip" aria-pressed={showGrid} onClick={() => setShowGrid(!showGrid)}>Grid totals</button>
            </div>
            <p style={{ color: "var(--text-2)", fontSize: 13 }}>Click empty water to add a dot. Click a dot to remove it.</p>
            <p className="meta">AI dots: {count.model}, low threshold. Expect many misses.</p>
            <button className="btn primary" onClick={save}>Save count</button>
          </div>
        </aside>
      </div>
    </div>
  );
}
