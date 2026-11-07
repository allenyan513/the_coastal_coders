import { DragEvent, useRef, useState } from "react";
import { api, isLocal, ModelOption } from "./api";
import { Modal } from "./Modal";
import { FilmedOn, StationPicker } from "./Surveys";
import { placeLabel, refreshSurveys, season, suggestStation, useSurveys } from "./surveyStore";

const STEPS = ["Footage", "Station and date", "Check and import"] as const;

/** Where the footage comes from: a file picked in the browser, or a path on this PC for files too large to upload. */
type Source = { kind: "file"; file: File } | { kind: "path"; path: string };

const sourceName = (s: Source) => (s.kind === "file" ? s.file.name : s.path.split(/[\\/]/).pop() || s.path);

function size(bytes: number) {
  if (bytes >= 1e9) return `${(bytes / 1e9).toFixed(1)} GB`;
  if (bytes >= 1e6) return `${Math.round(bytes / 1e6)} MB`;
  return `${Math.max(1, Math.round(bytes / 1e3))} KB`;
}

const longDate = (iso: string) => new Date(`${iso}T12:00:00`).toLocaleDateString(undefined, { day: "numeric", month: "long", year: "numeric" });

type Props = {
  models: ModelOption[];
  /** Set when the import starts from a station's row, so that step is already done. */
  station?: string;
  onClose: () => void;
  onImported: (name: string) => void;
};

/**
 * Import one video in three steps: the footage, where and when it was filmed, then a last look before it goes.
 * A Coastal Action file name like T1-STAT2 411.MP4 fills in the station, for the person to confirm.
 */
export function ImportDialog({ models, station = "", onClose, onImported }: Props) {
  const data = useSurveys();
  const [step, setStep] = useState(0);
  const [source, setSource] = useState<Source | null>(null);
  const [path, setPath] = useState("");
  const [stationId, setStationId] = useState(station);
  const [guessed, setGuessed] = useState(false);
  const [filmed, setFilmed] = useState("");
  const [detector, setDetector] = useState(() => models.find((m) => m.default)?.key ?? "");
  const [over, setOver] = useState(false);
  const [sent, setSent] = useState<number | null>(null);
  const [error, setError] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const busy = sent !== null;

  /** Takes the footage and moves on. The station comes from the name only if nobody has chosen one yet. */
  const take = (next: Source) => {
    setSource(next);
    setError("");
    const suggested = suggestStation(data, sourceName(next));
    if (!stationId && suggested) {
      setStationId(suggested);
      setGuessed(true);
    }
    setStep(1);
  };
  const drop = (e: DragEvent) => {
    e.preventDefault();
    setOver(false);
    const file = e.dataTransfer.files[0];
    if (file) take({ kind: "file", file });
  };

  async function submit() {
    if (!source || !stationId) return;
    setSent(0);
    setError("");
    try {
      const place = { station_id: stationId, filmed_on: filmed };
      if (source.kind === "file") await api.upload(source.file, place, detector, setSent);
      else await api.importPath(source.path, place, detector);
      await refreshSurveys();
      onImported(sourceName(source));
    } catch (e) {
      setError((e as Error).message);
      setSent(null);
    }
  }

  const canOpen = (i: number) => !busy && (i === 0 || (i === 1 && !!source) || (i === 2 && !!source && !!stationId));
  const model = models.find((m) => m.key === detector);

  return (
    <Modal title="Import video" onClose={onClose} wide locked={busy}>
      <nav className="steps wizard-steps" aria-label="Import steps">
        {STEPS.map((label, i) => (
          <button key={label} type="button" className="step" disabled={!canOpen(i)} aria-current={step === i ? "step" : undefined} onClick={() => setStep(i)}>
            <b className={i < step ? "ok" : ""}>{i < step ? "✓" : i + 1}</b>
            <span>{label}</span>
          </button>
        ))}
      </nav>

      {step === 0 && (
        <div className="stack">
          <div
            className={`drop drop-big ${over ? "over" : ""}`}
            onDragOver={(e) => { e.preventDefault(); setOver(true); }}
            onDragLeave={() => setOver(false)}
            onDrop={drop}
          >
            <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden><path d="M4 5h16v14H4zM10 9.5v5l4-2.5z" /></svg>
            <b><span className="hide-phone">Drop a video here</span><span className="only-phone">Choose a video</span></b>
            <span className="meta">MP4, MOV, MKV or AVI. {isLocal ? "It's copied into this PC's Tideflow folder and nowhere else." : "It's uploaded to the demo server."}</span>
            <button className="btn go" onClick={() => input.current?.click()}>Choose file</button>
            <input
              ref={input}
              type="file"
              accept="video/*,.mp4,.mov,.mkv,.avi"
              hidden
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) take({ kind: "file", file });
                e.target.value = "";
              }}
            />
          </div>
          {source && <p className="meta">Chosen: <b>{sourceName(source)}</b>. <button className="link" onClick={() => setStep(1)}>Keep it</button></p>}
          {isLocal && (
            <details className="advanced hide-phone">
              <summary>File too large to upload? Import it from a path on this PC</summary>
              <form className="row" style={{ alignItems: "flex-end" }} onSubmit={(e) => { e.preventDefault(); if (path.trim()) take({ kind: "path", path: path.trim() }); }}>
                <label className="field" style={{ flex: 1 }}>File path
                  <input value={path} onChange={(e) => setPath(e.target.value)} placeholder="D:\Surveys\GX010123.MP4" />
                </label>
                <button className="btn" type="submit" disabled={!path.trim()}>Use this path</button>
              </form>
            </details>
          )}
        </div>
      )}

      {step === 1 && source && (
        <div className="stack">
          <div className="file-chip">
            <span className="num">{source.kind === "file" ? size(source.file.size) : "Path"}</span>
            <b>{sourceName(source)}</b>
          </div>
          {guessed && stationId && <p className="hint">Filled in from the file name. Check it's right.</p>}
          <StationPicker data={data} value={stationId} onChange={(id) => { setStationId(id); setGuessed(false); }} />
          <FilmedOn value={filmed} onChange={setFilmed} />
          <div className="row dialog-foot">
            <button className="btn" onClick={() => setStep(0)}>Back</button>
            <button className="btn go" disabled={!stationId} onClick={() => setStep(2)}>Next</button>
          </div>
        </div>
      )}

      {step === 2 && source && (
        <div className="stack">
          <dl className="facts">
            <dt>Video</dt><dd>{sourceName(source)}{source.kind === "file" && <span className="meta"> · {size(source.file.size)}</span>}</dd>
            <dt>Station</dt><dd>{placeLabel(data, stationId)}</dd>
            <dt>Filmed</dt><dd>{filmed ? `${longDate(filmed)} · ${season(filmed)}` : <span className="meta">No date. Reports leave it out of season comparisons.</span>}</dd>
          </dl>
          <label className="field">Detection model
            <select value={detector} disabled={busy} onChange={(e) => setDetector(e.target.value)}>
              {models.map((m) => <option key={m.key} value={m.key} disabled={!m.available}>{m.label}{m.available ? "" : " (off)"}</option>)}
            </select>
            {model?.note && <span>{model.note}</span>}
          </label>
          <p className="meta">After import, AI scans the video for fish. It shows up under Analysing on the Workflow board, then moves to To count.</p>
          {busy && source.kind === "file" && (
            <div className="stack" style={{ gap: 6 }}>
              <span className="meta num">{sent! < 1 ? `Uploading… ${Math.round(sent! * 100)}%` : "Saving…"}</span>
              <span className="bar wide"><i style={{ width: `${sent! * 100}%` }} /></span>
            </div>
          )}
          {error && <p className="meta" role="alert" style={{ color: "var(--down)" }}>{error}</p>}
          <div className="row dialog-foot">
            <button className="btn" disabled={busy} onClick={() => setStep(1)}>Back</button>
            <button className="btn go" disabled={busy} onClick={submit}>{busy ? "Importing…" : "Import"}</button>
          </div>
        </div>
      )}
    </Modal>
  );
}
