import { DragEvent, PointerEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api, LibraryPhoto, ScanCrop, ScanResult, ScanStatus, SpeciesMediaSummary, SpeciesRow } from "./api";
import { InfoTip } from "./InfoTip";
import { ReviewPill } from "./PhotoLibrary";
import { speciesMedia, speciesPagePath, speciesRows } from "./speciesData";
import { SpeciesDrawer } from "./SpeciesDrawer";
import { boxBetween, commonOf, cropPixels, fileProblem, filterLibrary, MAX_BYTES, scorePercent, tooSmall } from "./scanHelpers";

type Source = "library" | "upload";
type Picked =
  | { kind: "library"; photo: LibraryPhoto; src: string; label: string }
  | { kind: "upload"; file: File; src: string; label: string };

/** Library photos shown at first; more on request, so a big library doesn't load every thumbnail. */
const PAGE = 48;

/**
 * Fish Scan: ask BioCLIP which listed species a still picture looks most like. The picture is a
 * Media Library photo, or one uploaded only for this scan and never saved. It can be cropped to the
 * fish first. Each suggestion opens the Species wiki, so a person can check the name against the
 * reference photos and notes. Separate from video analysis and counting: nothing here is recorded.
 */
export function FishScan() {
  const [source, setSource] = useState<Source>("library");
  const [photos, setPhotos] = useState<LibraryPhoto[] | null>(null);
  const [rows, setRows] = useState<SpeciesRow[]>(() => speciesRows.peek() ?? []);
  const [media, setMedia] = useState<SpeciesMediaSummary>(() => speciesMedia.peek() ?? {});
  const [query, setQuery] = useState("");
  const [limit, setLimit] = useState(PAGE);
  const [picked, setPicked] = useState<Picked | null>(null);
  const [natural, setNatural] = useState<{ w: number; h: number } | null>(null);
  const [crop, setCrop] = useState<ScanCrop | null>(null);
  const [cropping, setCropping] = useState(false);
  const [draft, setDraft] = useState<ScanCrop | null>(null);
  const [over, setOver] = useState(false);
  const [status, setStatus] = useState<ScanStatus | null>(null);
  const [scanning, setScanning] = useState(false);
  const [result, setResult] = useState<ScanResult | null>(null);
  const [error, setError] = useState("");
  const [libraryError, setLibraryError] = useState("");
  const [drawer, setDrawer] = useState<string | null>(null);
  const image = useRef<HTMLImageElement>(null);
  const preview = useRef<HTMLElement>(null);
  const from = useRef<{ x: number; y: number } | null>(null);
  const prepared = useRef(false);

  useEffect(() => {
    api.photoLibrary().then((r) => setPhotos(r.photos)).catch((e: Error) => setLibraryError(e.message));
    speciesRows.get().then(setRows).catch(() => {});
    speciesMedia.get().then(setMedia).catch(() => {});
    api.scanStatus().then(setStatus).catch(() => {});
  }, []);

  // While the model loads in the background, check now and then so the note under Scan stays true.
  useEffect(() => {
    if (status?.state !== "loading") return;
    const timer = setInterval(() => api.scanStatus().then(setStatus).catch(() => {}), 4000);
    return () => clearInterval(timer);
  }, [status?.state]);

  // An uploaded picture lives only in this tab, as an object URL, until another is picked or the page closes.
  useEffect(() => {
    if (picked?.kind !== "upload") return;
    const url = picked.src;
    return () => URL.revokeObjectURL(url);
  }, [picked]);

  const shown = useMemo(() => filterLibrary(photos ?? [], rows, query), [photos, rows, query]);
  useEffect(() => setLimit(PAGE), [query]);

  const pick = (next: Picked) => {
    setPicked(next);
    setNatural(null);
    setCrop(null);
    setCropping(false);
    setDraft(null);
    setResult(null);
    setError("");
    // In one column the preview is below the list, so bring it into view.
    if (window.matchMedia("(max-width: 1180px)").matches) {
      const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      requestAnimationFrame(() => preview.current?.scrollIntoView({ block: "start", behavior: still ? "auto" : "smooth" }));
    }
    // Someone means to scan: start loading the model now, so the first scan waits less.
    if (!prepared.current) {
      prepared.current = true;
      api.scanPrepare().then(setStatus).catch(() => {});
    }
  };

  const takeFile = (file?: File | null) => {
    if (!file) return;
    const why = fileProblem(file);
    if (why) { setError(why); return; }
    pick({ kind: "upload", file, src: URL.createObjectURL(file), label: file.name });
  };

  const onDrop = (e: DragEvent<HTMLLabelElement>) => {
    e.preventDefault();
    setOver(false);
    takeFile(e.dataTransfer.files?.[0]);
  };

  /** Where the pointer is on the picture, from 0 to 1 each way. */
  const spot = (e: PointerEvent) => {
    const box = image.current!.getBoundingClientRect();
    return { x: (e.clientX - box.left) / box.width, y: (e.clientY - box.top) / box.height };
  };
  const onDown = (e: PointerEvent<HTMLDivElement>) => {
    if (!cropping || e.button !== 0 || !image.current) return;
    e.preventDefault();
    e.currentTarget.setPointerCapture(e.pointerId);
    from.current = spot(e);
    setDraft(boxBetween(from.current, from.current));
  };
  const onMove = (e: PointerEvent<HTMLDivElement>) => {
    if (from.current) setDraft(boxBetween(from.current, spot(e)));
  };
  const onUp = (e: PointerEvent<HTMLDivElement>) => {
    if (!from.current) return;
    const box = boxBetween(from.current, spot(e));
    from.current = null;
    setDraft(null);
    if (natural && !tooSmall(box, natural.w, natural.h)) {
      setCrop(box);
      setCropping(false);
      setResult(null);
    }
  };
  const onCancel = () => { from.current = null; setDraft(null); };

  const run = async () => {
    if (!picked) return;
    setScanning(true);
    setError("");
    setResult(null);
    try {
      // A library photo is read by the server from its id (the browser can't always fetch a photo
      // hosted on another site); an uploaded picture is sent from here and never stored.
      setResult(picked.kind === "upload" ? await api.scan(picked.file, crop) : await api.scanPhoto(picked.photo.id, crop));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setScanning(false);
      api.scanStatus().then(setStatus).catch(() => {});
    }
  };

  // Stable, so the drawer doesn't take focus back every time this page redraws.
  const closeDrawer = useCallback(() => setDrawer(null), []);
  const expandDrawer = useCallback((tab: string) => { if (drawer) window.open(speciesPagePath(drawer, tab), "_blank", "noopener"); }, [drawer]);

  const box = draft ?? crop;
  const cropSize = crop && natural ? cropPixels(crop, natural.w, natural.h) : null;
  const unavailable = status?.state === "unavailable";
  const count = status?.species_count || rows.length || null;

  return (
    <div className="stack scan-page" style={{ gap: 20 }}>
      <div className="pagehead">
        <div>
          <h1>Fish Scan</h1>
          <p className="lede">
            Ask BioCLIP which of the {count ?? ""} species on Tideflow's list a still picture looks most like, then check its suggestions in the Species wiki.
            Scanning doesn't save the picture or record anything.
          </p>
        </div>
      </div>

      <div className="scan-layout">
        <section className="panel scan-source" aria-labelledby="scan-source-title">
          <div className="panel-head scan-head">
            <h2 id="scan-source-title">1. Choose a picture</h2>
            <div className="row" role="group" aria-label="Picture from">
              <button type="button" className="chip" aria-pressed={source === "library"} onClick={() => setSource("library")}>Media Library</button>
              <button type="button" className="chip" aria-pressed={source === "upload"} onClick={() => setSource("upload")}>Upload a picture</button>
            </div>
          </div>
          <div className="panel-pad">
            {source === "upload" ? (
              <>
                <label
                  className={`drop file-pick scan-drop ${over ? "over" : ""}`}
                  onDragOver={(e) => { e.preventDefault(); setOver(true); }}
                  onDragLeave={() => setOver(false)}
                  onDrop={onDrop}
                >
                  <input className="sr-only" type="file" accept="image/jpeg,image/png,image/webp" onChange={(e) => { takeFile(e.target.files?.[0]); e.target.value = ""; }} />
                  <span className="btn go" aria-hidden>Choose a picture</span>
                  <span>or drop it here. JPEG, PNG or WebP, up to {MAX_BYTES / (1024 * 1024)} MB.</span>
                </label>
                <p className="hint">Only scanned. The picture isn't added to the Media Library or saved anywhere, and it's gone when you leave this page.</p>
              </>
            ) : (
              <>
                <label className="field">Find a photo
                  <input type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Species, caption or photographer" autoComplete="off" />
                </label>
                {libraryError && <p className="meta" role="alert" style={{ color: "var(--down)" }}>{libraryError}</p>}
                {!photos && !libraryError && <p className="meta">Loading the Media Library…</p>}
                {photos && !shown.length && <p className="meta">No photos match.</p>}
                {photos && shown.length > 0 && (
                  <>
                    <p className="meta num">{shown.length} photos</p>
                    <ul className="scan-library" aria-label="Media Library photos">
                      {shown.slice(0, limit).map((p) => {
                        const name = p.species.length ? commonOf(rows, p.species[0]) : "Not on a species";
                        const on = picked?.kind === "library" && picked.photo.id === p.id;
                        return (
                          <li key={p.id}>
                            <button type="button" className="scan-photo" aria-pressed={on} aria-label={`Scan this photo: ${name}${p.caption ? `, ${p.caption}` : ""}`}
                              onClick={() => pick({ kind: "library", photo: p, src: p.url, label: name })}>
                              <img className="photo-thumb" src={p.thumb_url ?? p.url} alt="" loading="lazy" />
                              <span className="scan-photo-name">{name}</span>
                              {p.review && p.review !== "verified" && <ReviewPill review={p.review} />}
                            </button>
                          </li>
                        );
                      })}
                    </ul>
                    {shown.length > limit && <button type="button" className="btn" onClick={() => setLimit((n) => n + PAGE)}>Show more ({shown.length - limit} left)</button>}
                  </>
                )}
              </>
            )}
          </div>
        </section>

        <div className="stack scan-work">
          <section className="panel" aria-labelledby="scan-preview-title" ref={preview}>
            <div className="panel-head scan-head">
              <h2 id="scan-preview-title">2. Crop and scan</h2>
              {picked && <span className="meta scan-picked" title={picked.label}>{picked.label}</span>}
            </div>
            <div className="panel-pad">
              {!picked ? (
                <div className="gallery-empty compact"><p className="meta">Choose a photo from the Media Library, or upload one, to see it here.</p></div>
              ) : (
                <>
                  <div className="scan-frame">
                    <div className={`scan-stage ${cropping ? "cropping" : ""}`} onPointerDown={onDown} onPointerMove={onMove} onPointerUp={onUp} onPointerCancel={onCancel}>
                      <img
                        ref={image}
                        key={picked.src}
                        src={picked.src}
                        alt={`Picture to scan: ${picked.label}`}
                        draggable={false}
                        onLoad={(e) => setNatural({ w: e.currentTarget.naturalWidth, h: e.currentTarget.naturalHeight })}
                        onError={() => setError("This picture couldn't be shown. It may be damaged, or its host may be offline.")}
                      />
                      {box && (
                        <div className="scan-crop" style={{ left: `${box.x * 100}%`, top: `${box.y * 100}%`, width: `${box.w * 100}%`, height: `${box.h * 100}%` }} aria-hidden />
                      )}
                    </div>
                  </div>
                  <div className="row scan-tools">
                    <button type="button" className="btn" aria-pressed={cropping} disabled={!natural} onClick={() => { setCropping(!cropping); setDraft(null); }}>
                      {cropping ? "Cancel crop" : crop ? "Crop again" : "Crop to the fish"}
                    </button>
                    {crop && <button type="button" className="btn" onClick={() => { setCrop(null); setResult(null); }}>Use the whole picture</button>}
                    <span className="meta num" role="status">
                      {cropping ? "Drag a box around the fish." : cropSize ? `Cropped to ${cropSize.w} × ${cropSize.h} px` : natural ? `Whole picture, ${natural.w} × ${natural.h} px` : ""}
                    </span>
                  </div>
                  <p className="meta">Cropping to one fish usually helps: BioCLIP looks at the whole picture it's given, background included.</p>
                  <button type="button" className="btn primary scan-go" disabled={scanning || unavailable || !natural} onClick={run}>
                    {scanning ? <><span className="spinner" aria-hidden />Scanning…</> : "Scan with BioCLIP"}
                  </button>
                  {unavailable && <p className="meta" role="alert" style={{ color: "var(--down)" }}>The species model couldn't be loaded on this computer, so pictures can't be scanned.</p>}
                  {!unavailable && status && status.state !== "ready" && (
                    <p className="meta">{status.state === "loading" ? "The species model is loading. " : ""}The first scan loads BioCLIP, which can take a minute. Later scans are quick.</p>
                  )}
                </>
              )}
              {error && <p className="meta" role="alert" style={{ color: "var(--down)" }}>{error}</p>}
            </div>
          </section>

          <section className="panel" aria-labelledby="scan-results-title" aria-busy={scanning}>
            <div className="panel-head scan-head">
              <h2 id="scan-results-title">3. BioCLIP's top {status?.top_k ?? 5}</h2>
              <InfoTip label="What the scores mean">
                <b>These aren't confidence levels</b>
                BioCLIP compares the picture with the names of the {count ?? ""} species on Tideflow's list and shares a score out across them. The scores rank the options. They aren't calibrated probabilities: a high score can still be wrong, and a fish that isn't on the list still gets five names.
              </InfoTip>
            </div>
            <div className="panel-pad">
              <p className="meta">Model similarity scores, not calibrated confidence or the chance a name is right. Compare each name with the Species wiki's reference photos before trusting it.</p>
              {scanning ? (
                <div className="scan-busy" role="status">
                  {/* Indeterminate: the server doesn't report how far along it is, so no made-up percentage. */}
                  <div className="bar scan-progress" role="progressbar" aria-label="Scanning with BioCLIP"><i /></div>
                  <p className="meta">
                    {status?.state === "ready"
                      ? `Comparing the picture with ${count ?? "the"} species…`
                      : "Loading BioCLIP, then comparing the picture with the species list. The first scan can take a minute."}
                  </p>
                </div>
              ) : !result ? (
                <p className="meta">The suggestions appear here after a scan.</p>
              ) : (
                <>
                  {result.small && (
                    <p className="note warn">The scanned area is under {result.min_side} pixels on its shorter side. In Tideflow's tests, BioCLIP did no better than chance on fish that small.</p>
                  )}
                  <ol className="scan-results">
                    {result.suggestions.map((s) => {
                      const thumb = media[s.species]?.thumb;
                      return (
                        <li key={s.species} className="scan-result">
                          <span className="scan-rank num" aria-hidden>{s.rank}</span>
                          <span className="scan-ref" aria-hidden>{thumb && <img src={thumb} alt="" loading="lazy" onError={(e) => { e.currentTarget.style.display = "none"; }} />}</span>
                          <span className="scan-names">
                            <b>{s.common}</b>
                            {s.common !== s.species && <i className="meta">{s.species}</i>}
                            <span className="scan-score">
                              <span className="scan-bar" aria-hidden><i style={{ width: `${Math.max(1, s.score * 100)}%` }} /></span>
                              <span className="num meta">{scorePercent(s.score)} score</span>
                            </span>
                          </span>
                          <span className="scan-links">
                            <button type="button" className="btn" onClick={() => setDrawer(s.species)} aria-label={`Compare with ${s.common} in the Species wiki`}>Compare</button>
                            <Link className="meta" to={speciesPagePath(s.species)} target="_blank" rel="noopener noreferrer" aria-label={`Open ${s.common} in the Species wiki in a new tab`}>Species wiki ↗</Link>
                          </span>
                        </li>
                      );
                    })}
                  </ol>
                  <p className="meta num">
                    {result.model} · {result.scanned.cropped ? "cropped area" : "whole picture"}, {result.scanned.width} × {result.scanned.height} px · chosen from {result.species_count} species
                  </p>
                </>
              )}
            </div>
          </section>
        </div>
      </div>

      {drawer && (
        <SpeciesDrawer
          species={drawer}
          row={rows.find((r) => r.species === drawer)}
          rows={rows}
          media={media}
          onSelect={setDrawer}
          onClose={closeDrawer}
          onExpand={expandDrawer}
        />
      )}
    </div>
  );
}
