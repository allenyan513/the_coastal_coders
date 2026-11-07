import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, Video } from "./api";
import { QrCode, startUrl } from "./Qr";

const STEPS = [
  ["AI scans the video", "It skips the footage with no detections."],
  ["You review what it found", "Confirm, correct or reject each fish."],
  ["Export the report", "Only counts a person confirmed reach it."],
];

/** The page the QR code opens: what TideCount is, and one tap into the app. */
export function Start() {
  // undefined while loading, null when no video is ready yet
  const [sample, setSample] = useState<Video | null>();

  useEffect(() => {
    api.videos()
      .then((all) => setSample(all.find((v) => v.status === "Ready to review") ?? null))
      .catch(() => setSample(null));
  }, []);

  return (
    <main className="start">
      <div className="start-main">
        <p className="start-brand"><img src="/favicon.svg" alt="" />Tideflow</p>
        <div>
          <h1>Count fish in underwater video.</h1>
          <p className="lede">AI finds the footage worth watching. A person reviews it and confirms every count.</p>
        </div>
        <div className="start-actions">
          {sample === undefined && <button className="btn primary block" disabled>Loading…</button>}
          {sample && <Link className="btn primary block" to={`/videos/${sample.id}`}>Try a sample video</Link>}
          {sample && <Link className="btn tall block" to={`/videos/${sample.id}/summary`}>See a sample report</Link>}
          <Link className={`btn block ${sample === null ? "primary" : "tall"}`} to="/?import=1">Upload your own video</Link>
        </div>
        <ol className="start-steps">
          {STEPS.map(([title, text], i) => (
            <li key={title}>
              <b className="num">{i + 1}</b>
              <span><strong>{title}</strong><span className="meta">{text}</span></span>
            </li>
          ))}
        </ol>
      </div>
      <aside className="panel start-qr">
        <QrCode value={startUrl()} size={240} />
        <p>Scan to open on your phone</p>
      </aside>
    </main>
  );
}
