import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, clock, Comparison, Track } from "./api";
import { pos } from "./trackHelpers";
import { VideoHeader } from "./VideoHeader";

const FRAME = 1 / 30;

export function Compare() {
  const { id = "" } = useParams();
  const [data, setData] = useState<Comparison | null>(null);
  const [tracks, setTracks] = useState<Record<string, Track[]>>({});
  const [time, setTime] = useState(0);
  const [playing, setPlaying] = useState(false);
  const players = useRef<(HTMLVideoElement | null)[]>([]);

  useEffect(() => {
    let timer = 0;
    const load = async () => {
      const next = await api.compare(id);
      setData(next);
      const ready = next.runs.filter((r) => r.status === "Ready to review");
      const entries = await Promise.all(ready.map(async (r) => [r.id, await api.tracks(r.id)] as const));
      setTracks(Object.fromEntries(entries));
      if (ready.length < next.runs.filter((r) => r.status !== "Failed").length) timer = window.setTimeout(load, 2500);
    };
    load();
    return () => clearTimeout(timer);
  }, [id]);

  const ready = useMemo(() => data?.runs.filter((r) => r.status === "Ready to review") ?? [], [data]);

  useEffect(() => {
    const lead = players.current[0];
    if (!lead) return;
    let handle = 0;
    const tick = () => {
      setTime(lead.currentTime);
      players.current.slice(1).forEach((p) => {
        if (p && Math.abs(p.currentTime - lead.currentTime) > 0.12) p.currentTime = lead.currentTime;
      });
      handle = lead.requestVideoFrameCallback(tick);
    };
    handle = lead.requestVideoFrameCallback(tick);
    return () => lead.cancelVideoFrameCallback(handle);
  }, [ready.length]);

  const seek = (t: number) => {
    players.current.forEach((p) => { if (p) p.currentTime = t; });
    setTime(t);
  };
  const toggle = () => {
    const lead = players.current[0];
    if (!lead) return;
    const start = lead.paused;
    players.current.forEach((p) => { if (p) { if (start) p.play(); else p.pause(); } });
    setPlaying(start);
  };
  const step = (n: number) => {
    players.current.forEach((p) => p?.pause());
    setPlaying(false);
    seek(Math.max(0, (players.current[0]?.currentTime ?? 0) + n * FRAME));
  };

  if (!data) return <p className="meta">Loading…</p>;

  return (
    <div className="stack">
      <VideoHeader id={id} title="Model comparison" from={{ to: "/models", label: "Model lab" }} />
      <p className="meta">More boxes doesn't mean better. Look for missed fish and false boxes.</p>

      <div className="panel" style={{ overflowX: "auto" }}>
        <table>
          <thead>
            <tr>
              <th>Model</th><th>State</th><th className="right">Tracks</th><th className="right">Boxes</th>
              <th className="right">Seconds with detections</th><th className="right">To review</th><th className="right">ms per frame</th><th className="right">Open</th>
            </tr>
          </thead>
          <tbody>
            {data.runs.map((r) => (
              <tr key={r.id}>
                <td>{r.label}</td>
                <td>{r.error || (r.status === "Analyzing" ? `${r.stage} ${Math.round(r.progress * 100)}%` : r.status)}</td>
                <td className="num right">{r.tracks}</td>
                <td className="num right">{r.boxes}</td>
                <td className="num right">{r.seconds_with_fish} of {r.seconds.length}</td>
                <td className="num right">{clock(r.to_review)}</td>
                <td className="num right">{r.ms_per_frame ? Math.round(r.ms_per_frame) : "—"}</td>
                <td className="right">{r.status === "Ready to review" && <Link className="btn" to={`/videos/${r.id}`}>Review</Link>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="panel row" style={{ padding: 8 }}>
        <button className="btn" onClick={() => step(-1)}>−1 frame</button>
        <button className="btn" style={{ minWidth: 68 }} onClick={toggle}>{playing ? "Pause" : "Play"}</button>
        <button className="btn" onClick={() => step(1)}>+1 frame</button>
        <span className="num meta">{clock(time)} / {clock(data.duration)}</span>
      </div>

      <div className="compare-grid">
        {ready.map((r, i) => (
          <section key={r.id} className="stack" style={{ gap: 6 }}>
            <p style={{ fontSize: 13, fontWeight: 600 }}>{r.label}</p>
            <div className="stage" style={{ aspectRatio: `${data.width || 16} / ${data.height || 9}` }}>
              <video
                ref={(el) => { players.current[i] = el; }}
                src={`/api/videos/${r.id}/proxy`}
                muted
                playsInline
                preload="auto"
                onEnded={() => setPlaying(false)}
              />
              <div className="overlay">
                {(tracks[r.id] ?? []).flatMap((t) => {
                  const box = pos(t, time);
                  if (!box) return [];
                  const [, x, y, w, h] = box;
                  return [
                    <div key={t.id} className="fishbox" style={{ left: `${x * 100}%`, top: `${y * 100}%`, width: `${w * 100}%`, height: `${h * 100}%` }} />,
                  ];
                })}
              </div>
            </div>
            <div className="timeline" style={{ height: 28 }}>
              {r.seconds.map((s) => (
                <button
                  key={s.second}
                  aria-label={`${r.label}, jump to ${clock(s.second)}`}
                  style={{ height: `${s.detections ? Math.max(20, Math.min(100, s.detections * 12)) : 8}%`, background: s.detections ? "var(--text-2)" : "#d5dbe5" }}
                  onClick={() => seek(s.second)}
                />
              ))}
              <span className="playhead" style={{ left: `${(time / (data.duration || 1)) * 100}%` }} />
            </div>
          </section>
        ))}
      </div>
      {ready.length < 2 && <p className="meta">Run another model from the Model lab to compare them here.</p>}
    </div>
  );
}
