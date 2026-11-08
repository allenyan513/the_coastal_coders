/**
 * Reference photo management: the Media Library page, and the photo editor the species drawer and
 * the full species page share in edit mode. A photo is uploaded once to the library and can be shown
 * on any number of species; removing it from a species only unlinks it. Uploads start pending review,
 * so they're never taken for a verified identification reference. Curated Wikimedia Commons and
 * iNaturalist photos keep their credits and links and are never deleted from here.
 */
import { FormEvent, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, LibraryPhoto, PhotoCredit, PhotoReview, SpeciesImage, SpeciesProfile, SpeciesRow } from "./api";
import { speciesMedia, speciesProfile, speciesRows } from "./speciesData";
import { normalizeProfile } from "./speciesProfile";
import { Modal } from "./Modal";

export const VIEW_LABELS: Record<SpeciesImage["view"], string> = {
  side: "Side profile",
  underwater: "Underwater",
  in_hand: "In hand",
  illustration: "Illustration",
  other: "Photo",
};
const REVIEW_LABELS: Record<PhotoReview, string> = { pending: "Pending review", verified: "Verified", rejected: "Rejected" };
const REVIEW_PILL: Record<PhotoReview, string> = { pending: "warn", verified: "up", rejected: "down" };
// The licences the curated photos use, plus the usual permissions for a survey's own photos.
const LICENCES: { label: string; url: string }[] = [
  { label: "CC BY 4.0", url: "https://creativecommons.org/licenses/by/4.0/" },
  { label: "CC BY-SA 4.0", url: "https://creativecommons.org/licenses/by-sa/4.0/" },
  { label: "CC0 1.0", url: "https://creativecommons.org/publicdomain/zero/1.0/" },
  { label: "Public domain", url: "" },
  { label: "Own photo, used with permission", url: "" },
  { label: "Used with the photographer's permission", url: "" },
];
const OTHER = "__other__";
const BLANK: PhotoCredit = { view: "side", caption: "", creator: "", license: "", license_url: "", source: "", source_url: "", place: "" };

const nameOf = (rows: SpeciesRow[] | null, species: string) => {
  const r = rows?.find((x) => x.species === species);
  return r && r.common !== r.species ? r.common : species;
};

/** After a change, the species galleries and list badges ask again rather than show the old photos. */
function refresh(species: string[]) {
  for (const s of new Set(species)) speciesProfile(s).reload().catch(() => {});
  speciesMedia.reload();
}

export function ReviewPill({ review = "verified" }: { review?: PhotoReview }) {
  return <span className={`pill ${REVIEW_PILL[review]}`}>{REVIEW_LABELS[review]}</span>;
}

/** The credit an uploaded photo needs: who took it, the licence or permission to use it, what it shows and where it's from. */
function CreditFields({ value, onChange }: { value: PhotoCredit; onChange: (v: PhotoCredit) => void }) {
  const set = (k: keyof PhotoCredit) => (e: { target: { value: string } }) => onChange({ ...value, [k]: e.target.value });
  // A licence that isn't in the list (typed before, or edited elsewhere) shows as Other with its text.
  const [other, setOther] = useState(() => value.license !== "" && !LICENCES.some((l) => l.label === value.license));
  return (
    <div className="photo-fields">
      <label className="field">Photo type
        <select value={value.view} onChange={set("view")}>
          {Object.entries(VIEW_LABELS).map(([k, label]) => <option key={k} value={k}>{label}</option>)}
        </select>
      </label>
      <label className="field">Photographer *<input required value={value.creator} onChange={set("creator")} placeholder="Who took the photo" /></label>
      <label className="field">Licence or permission *
        <select
          required value={other ? OTHER : value.license}
          onChange={(e) => {
            const pick = e.target.value;
            if (pick === OTHER) { setOther(true); onChange({ ...value, license: "" }); return; }
            setOther(false);
            // A known licence fills in its link; a permission has none, so a link left from a licence is cleared.
            const known = LICENCES.find((l) => l.label === pick);
            const wasKnownLink = LICENCES.some((l) => l.url && l.url === value.license_url);
            onChange({ ...value, license: pick, license_url: known?.url || (wasKnownLink ? "" : value.license_url) });
          }}
        >
          <option value="" disabled>Choose…</option>
          {LICENCES.map((l) => <option key={l.label} value={l.label}>{l.label}</option>)}
          <option value={OTHER}>Other…</option>
        </select>
      </label>
      {other && <label className="field">Other licence or permission *<input required value={value.license} onChange={set("license")} placeholder="Describe the licence or permission" /></label>}
      <label className="field">Licence link<input type="url" pattern="https://.*" value={value.license_url} onChange={set("license_url")} placeholder="https://…" /></label>
      <label className="field">Source<input value={value.source} onChange={set("source")} placeholder="Field survey, iNaturalist…" /></label>
      <label className="field">Source link<input type="url" pattern="https://.*" value={value.source_url} onChange={set("source_url")} placeholder="https://…" /></label>
      <label className="field">Caption<input value={value.caption} onChange={set("caption")} /></label>
      <label className="field">Place<input value={value.place ?? ""} onChange={set("place")} placeholder="Where it was taken" /></label>
    </div>
  );
}

/** A file and its credit. What happens on submit is up to the caller: upload now, or on Save. */
function UploadForm({ submitLabel, busy, onSubmit }: { submitLabel: string; busy?: boolean; onSubmit: (file: File, credit: PhotoCredit) => Promise<void> | void }) {
  const [file, setFile] = useState<File | null>(null);
  const [credit, setCredit] = useState<PhotoCredit>(BLANK);
  const [key, setKey] = useState(0);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!file) return;
    try { await onSubmit(file, credit); } catch { return; } // keep what was typed, so it can be fixed and sent again
    setFile(null); setCredit(BLANK); setKey((k) => k + 1);
  };
  return (
    <form className="panel panel-pad photo-upload" onSubmit={submit}>
      <label className="field">Photo (JPEG, PNG or WebP, up to 15 MB)
        {/* The import dialog's button. The real input stays in the form, hidden from sight only, so it
            still takes keyboard focus, opens on Enter or Space and counts for `required`. */}
        <span className="file-pick">
          <input key={key} className="sr-only" type="file" accept="image/jpeg,image/png,image/webp" required onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
          <span className="btn go" aria-hidden>Choose file</span>
          <span className="file-pick-name">{file ? file.name : "No file chosen"}</span>
        </span>
      </label>
      {/* Keyed with the file input, so a sent form starts again from "Choose…". */}
      <CreditFields key={key} value={credit} onChange={setCredit} />
      <p className="meta">New photos are marked Pending review. They aren't treated as identification references until a person verifies them.</p>
      <div className="row"><button className="btn go" type="submit" disabled={!file || busy}>{submitLabel}</button></div>
    </form>
  );
}

function Thumb({ img }: { img: SpeciesImage }) {
  return <img className="photo-thumb" src={img.thumb_url ?? img.url} alt="" loading="lazy" />;
}

function CreditLine({ img }: { img: SpeciesImage }) {
  return (
    <span className="meta">
      {img.creator || "Unknown photographer"} · {img.license_url ? <a href={img.license_url} target="_blank" rel="noreferrer noopener">{img.license}</a> : img.license}
      {img.source && <> · {img.source_url ? <a href={img.source_url} target="_blank" rel="noreferrer noopener">{img.source}</a> : img.source}</>}
    </span>
  );
}

type Staged = { key: string; file: File; credit: PhotoCredit; preview: string };

/**
 * Unsaved photo edits by species, in memory only. Expand and Collapse swap the drawer for the page
 * (or back), which remounts the editor; they pass `editing: true` in the navigation state, and the
 * new view picks up the same draft. Arriving any other way drops a leftover draft.
 */
const drafts = new Map<string, { images: SpeciesImage[]; staged: Staged[] }>();
export const editDrafts = {
  start: (species: string, images: SpeciesImage[]) => { drafts.set(species, { images, staged: [] }); },
  has: (species: string) => drafts.has(species),
  discard: (species: string) => {
    drafts.get(species)?.staged.forEach((s) => URL.revokeObjectURL(s.preview));
    drafts.delete(species);
  },
  /** True when this view should open in edit mode with the draft a move carried over. */
  resume: (species: string, navState: unknown) => {
    if ((navState as { editing?: boolean } | null)?.editing && drafts.has(species)) return true;
    editDrafts.discard(species);
    return false;
  },
};

/**
 * Edit mode for one species' photos: add from the library, upload new ones, remove (unlink) any.
 * Nothing is stored until Save; Cancel leaves the species as it was. Shared by the drawer and the page.
 */
export function PhotoEditor({ data, onSaved, onCancel }: { data: SpeciesProfile; onSaved: (p: SpeciesProfile) => void; onCancel: () => void }) {
  const [draft, setDraft] = useState<SpeciesImage[]>(() => drafts.get(data.species)?.images ?? data.images);
  const [staged, setStaged] = useState<Staged[]>(() => drafts.get(data.species)?.staged ?? []);
  // Kept in step, so Expand or Collapse mid-edit carries every unsaved change to the other view.
  useEffect(() => { drafts.set(data.species, { images: draft, staged }); }, [data.species, draft, staged]);
  const cancel = () => { editDrafts.discard(data.species); onCancel(); };
  const [library, setLibrary] = useState<LibraryPhoto[] | null>(null);
  const [picking, setPicking] = useState(false);
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const openPicker = () => {
    setPicking(true);
    if (!library) api.photoLibrary().then((r) => setLibrary(r.photos)).catch((e) => setError(e.message));
  };
  const inDraft = new Set(draft.map((i) => i.id));
  const choices = (library ?? []).filter((p) => !inDraft.has(p.id) && p.review !== "rejected" && (!query.trim() || [p.creator, p.caption, p.source, ...p.species].join(" ").toLowerCase().includes(query.trim().toLowerCase())));

  const save = async () => {
    setBusy(true); setError("");
    try {
      // Uploads go to the library first (stored once); then one save sets this species' photos.
      const uploaded: string[] = [];
      for (const s of staged) uploaded.push((await api.uploadPhoto(s.file, s.credit)).id);
      const saved = normalizeProfile(await api.saveSpeciesPhotos(data.species, [...draft.map((i) => i.id), ...uploaded]), data.species);
      refresh([data.species]);
      editDrafts.discard(data.species);
      onSaved(saved);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  };

  return (
    <section className="photo-editor stack" aria-label="Edit photos" style={{ gap: 12 }}>
      <div className="photo-editor-head">
        <h3>Photos</h3>
        <span className="meta">Removing a photo only takes it off this species. It stays in the <Link to="/species/library">Media Library</Link>.</span>
      </div>
      {draft.length + staged.length === 0 && <p className="meta">No photos on this species.</p>}
      <ul className="photo-grid">
        {draft.map((img) => (
          <li key={img.id} className="photo-card">
            <Thumb img={img} />
            <div className="photo-card-body">
              <span className="row" style={{ gap: 6 }}><span className="pill muted">{VIEW_LABELS[img.view]}</span><ReviewPill review={img.review} /></span>
              <CreditLine img={img} />
              <button type="button" className="btn" onClick={() => setDraft((d) => d.filter((i) => i.id !== img.id))} aria-label={`Remove photo by ${img.creator} from this species`}>Remove from species</button>
            </div>
          </li>
        ))}
        {staged.map((s) => (
          <li key={s.key} className="photo-card">
            <img className="photo-thumb" src={s.preview} alt="" />
            <div className="photo-card-body">
              <span className="row" style={{ gap: 6 }}><span className="pill muted">{VIEW_LABELS[s.credit.view]}</span><span className="pill accent">New, uploads on Save</span></span>
              <span className="meta">{s.credit.creator} · {s.credit.license}</span>
              <button type="button" className="btn" onClick={() => { URL.revokeObjectURL(s.preview); setStaged((x) => x.filter((y) => y.key !== s.key)); }}>Don't upload</button>
            </div>
          </li>
        ))}
      </ul>

      <div className="row">
        <button type="button" className="btn" aria-expanded={picking} onClick={() => (picking ? setPicking(false) : openPicker())}>Add from library</button>
      </div>
      {picking && (
        <div className="panel panel-pad stack" style={{ gap: 8 }}>
          <label className="field">Find a photo<input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Photographer, caption, source or species" /></label>
          {!library ? <p className="meta">Loading the library…</p> : !choices.length ? <p className="meta">No other photos match.</p> : (
            <ul className="photo-grid">
              {choices.map((p) => (
                <li key={p.id} className="photo-card">
                  <Thumb img={p} />
                  <div className="photo-card-body">
                    <span className="row" style={{ gap: 6 }}><span className="pill muted">{VIEW_LABELS[p.view]}</span><ReviewPill review={p.review} /></span>
                    <CreditLine img={p} />
                    <span className="meta">{p.species.length ? `On ${p.species.length} species` : "Not on any species"}</span>
                    <button type="button" className="btn" onClick={() => setDraft((d) => [...d, p])}>Add to species</button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      <details className="fold">
        <summary>Upload a new photo</summary>
        <div className="fold-body">
          <UploadForm submitLabel="Add to this species" onSubmit={(file, credit) => setStaged((x) => [...x, { key: `${Date.now()}-${file.name}`, file, credit, preview: URL.createObjectURL(file) }])} />
        </div>
      </details>

      {error && <p className="meta" role="alert" style={{ color: "var(--down)" }}>{error}</p>}
      <div className="row photo-editor-actions">
        <button type="button" className="btn go" onClick={save} disabled={busy}>{busy ? "Saving…" : "Save"}</button>
        <button type="button" className="btn" onClick={cancel} disabled={busy}>Cancel</button>
      </div>
    </section>
  );
}

/** One uploaded photo's credit and review, edited in place in the library. */
function EditUpload({ photo, onDone }: { photo: LibraryPhoto; onDone: (p?: LibraryPhoto) => void }) {
  const [credit, setCredit] = useState<PhotoCredit>({ view: photo.view, caption: photo.caption, creator: photo.creator, license: photo.license, license_url: photo.license_url, source: photo.source, source_url: photo.source_url, place: photo.place ?? "" });
  const [error, setError] = useState("");
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    try { onDone(await api.editPhoto(photo.id, credit)); } catch (err) { setError(err instanceof Error ? err.message : String(err)); }
  };
  return (
    <form className="stack" style={{ gap: 8 }} onSubmit={submit}>
      <CreditFields value={credit} onChange={setCredit} />
      {error && <p className="meta" role="alert" style={{ color: "var(--down)" }}>{error}</p>}
      <div className="row"><button className="btn go" type="submit">Save</button><button className="btn" type="button" onClick={() => onDone()}>Cancel</button></div>
    </form>
  );
}

/**
 * Confirms a permanent delete. Nothing happens until "Delete photo". If the server asks for the
 * deletion key (anywhere but the computer running Tideflow), a field for it appears.
 */
function DeletePhotoDialog({ photo, nameOf, onClose, onDeleted }: { photo: LibraryPhoto; nameOf: (s: string) => string; onClose: () => void; onDeleted: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [needsKey, setNeedsKey] = useState(false);
  const [key, setKey] = useState("");
  const go = async () => {
    setBusy(true); setError("");
    try {
      await api.deletePhoto(photo.id, key);
      onDeleted();
    } catch (e) {
      if ((e as { status?: number }).status === 403) setNeedsKey(true);
      setError(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  };
  return (
    <Modal title="Delete photo" onClose={onClose} locked={busy}>
      <div className="row" style={{ gap: 12, alignItems: "flex-start", flexWrap: "nowrap" }}>
        <img className="photo-thumb" src={photo.thumb_url ?? photo.url} alt="" style={{ width: 120, flex: "none", borderRadius: 6 }} />
        <div className="stack" style={{ gap: 4, minWidth: 0 }}>
          <b>{photo.caption || `${VIEW_LABELS[photo.view]} by ${photo.creator}`}</b>
          <span className="meta">{photo.creator} · {photo.license}{photo.added_on ? ` · added ${photo.added_on}` : ""}</span>
        </div>
      </div>
      <p><b>Are you sure you want to permanently delete this photo?</b></p>
      <p className="meta">
        {photo.species.length
          ? <>It will also be removed from every species profile linked to it: {photo.species.map(nameOf).join(", ")}.</>
          : "It will also be removed from every species profile linked to it. It isn't on any species now."}
        {" "}This can't be undone. To take it off one species only, use Remove from species in that species' Edit mode instead.
      </p>
      {needsKey && (
        <label className="field">Deletion key
          <input type="password" autoComplete="off" value={key} onChange={(e) => setKey(e.target.value)} />
        </label>
      )}
      {error && <p className="meta" role="alert" style={{ color: "var(--down)" }}>{error}</p>}
      <div className="row dialog-foot" style={{ justifyContent: "flex-end" }}>
        <button className="btn" onClick={onClose} disabled={busy}>Cancel</button>
        <button className="btn danger" onClick={go} disabled={busy || (needsKey && !key)}>{busy ? "Deleting…" : "Delete photo"}</button>
      </div>
    </Modal>
  );
}

/** Every reference photo: browse, filter, upload and review. Reached from the Species wiki. */
export function MediaLibrary() {
  const [photos, setPhotos] = useState<LibraryPhoto[] | null>(null);
  const [rows, setRows] = useState<SpeciesRow[] | null>(() => speciesRows.peek() ?? null);
  const [error, setError] = useState("");
  const [species, setSpecies] = useState("");
  const [view, setView] = useState("");
  const [review, setReview] = useState("");
  const [assignTo, setAssignTo] = useState("");
  const [editing, setEditing] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [deleting, setDeleting] = useState<LibraryPhoto | null>(null);

  const load = () => api.photoLibrary().then((r) => setPhotos(r.photos)).catch((e) => setError(e.message));
  useEffect(() => { load(); speciesRows.get().then(setRows).catch(() => {}); }, []);

  const shown = useMemo(() => (photos ?? []).filter((p) =>
    (!species || (species === "none" ? p.species.length === 0 : p.species.includes(species)))
    && (!view || p.view === view)
    && (!review || (p.review ?? "verified") === review)), [photos, species, view, review]);

  const upload = async (file: File, credit: PhotoCredit) => {
    setBusy(true); setMessage(""); setError("");
    try {
      const photo = await api.uploadPhoto(file, credit);
      if (assignTo) {
        const current = await speciesProfile(assignTo).reload();
        if (!current.images.some((i) => i.id === photo.id)) await api.saveSpeciesPhotos(assignTo, [...current.images.map((i) => i.id), photo.id]);
        refresh([assignTo]);
      }
      setMessage(photo.duplicate ? "That photo was already in the library, so it wasn't stored again." : "Uploaded. It is pending review.");
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      throw e;
    } finally {
      setBusy(false);
    }
  };

  const changeReview = async (p: LibraryPhoto, value: PhotoReview) => {
    try {
      const saved = await api.editPhoto(p.id, { review: value });
      setPhotos((all) => all?.map((x) => (x.id === p.id ? { ...x, ...saved, species: x.species } : x)) ?? null);
      refresh(p.species);
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
  };

  const deleted = (p: LibraryPhoto) => {
    setPhotos((all) => all?.filter((x) => x.id !== p.id) ?? null);
    refresh(p.species);
    setDeleting(null);
    setMessage("Photo deleted.");
  };

  const sorted = [...(rows ?? [])].sort((a, b) => nameOf(rows, a.species).localeCompare(nameOf(rows, b.species)));

  return (
    <div className="stack" style={{ gap: 20 }}>
      <nav className="species-page-nav" aria-label="Species wiki"><Link className="btn species-back" to="/species">← Back to Species list</Link></nav>
      {deleting && <DeletePhotoDialog photo={deleting} nameOf={(s) => nameOf(rows, s)} onClose={() => setDeleting(null)} onDeleted={() => deleted(deleting)} />}
      <div>
        <h1>Media Library</h1>
        <p className="lede">Reference photos for the Species wiki. A photo is stored once and can be shown on any number of species.</p>
      </div>

      <details className="fold">
        <summary>Upload a photo</summary>
        <div className="fold-body stack" style={{ gap: 8 }}>
          <label className="field">Show on species (optional)
            <select value={assignTo} onChange={(e) => setAssignTo(e.target.value)}>
              <option value="">Not on a species yet</option>
              {sorted.map((r) => <option key={r.species} value={r.species}>{nameOf(rows, r.species)}</option>)}
            </select>
          </label>
          <UploadForm submitLabel={busy ? "Uploading…" : "Upload"} busy={busy} onSubmit={upload} />
        </div>
      </details>
      {message && <p className="meta" role="status">{message}</p>}
      {error && <p className="meta" role="alert" style={{ color: "var(--down)" }}>{error}</p>}

      <div className="panel">
        <div className="panel-head row">
          <label className="field">Species
            <select value={species} onChange={(e) => setSpecies(e.target.value)}>
              <option value="">All species</option>
              <option value="none">Not on any species</option>
              {sorted.map((r) => <option key={r.species} value={r.species}>{nameOf(rows, r.species)}</option>)}
            </select>
          </label>
          <label className="field">Photo type
            <select value={view} onChange={(e) => setView(e.target.value)}>
              <option value="">All types</option>
              {Object.entries(VIEW_LABELS).map(([k, label]) => <option key={k} value={k}>{label}</option>)}
            </select>
          </label>
          <label className="field">Review
            <select value={review} onChange={(e) => setReview(e.target.value)}>
              <option value="">Any status</option>
              {Object.entries(REVIEW_LABELS).map(([k, label]) => <option key={k} value={k}>{label}</option>)}
            </select>
          </label>
          <span className="num meta" style={{ alignSelf: "flex-end", paddingBottom: 10 }}>{shown.length} of {photos?.length ?? 0}</span>
        </div>
        <div className="panel-pad">
          {!photos ? <p className="meta">Loading…</p> : !shown.length ? <p className="meta">No photos match.</p> : (
            <ul className="photo-grid library">
              {shown.map((p) => (
                <li key={p.id} className="photo-card">
                  <a href={p.url} target="_blank" rel="noreferrer noopener" aria-label="Open the full photo"><Thumb img={p} /></a>
                  <div className="photo-card-body">
                    <span className="row" style={{ gap: 6 }}><span className="pill muted">{VIEW_LABELS[p.view]}</span><ReviewPill review={p.review} /></span>
                    {p.caption && <span>{p.caption}</span>}
                    <CreditLine img={p} />
                    <span className="meta">
                      {p.species.length ? <>On {p.species.map((s, i) => <span key={s}>{i > 0 && ", "}<Link to={`/species?species=${encodeURIComponent(s)}`}>{nameOf(rows, s)}</Link></span>)}</> : "Not on any species"}
                    </span>
                    {p.kind === "upload" ? (
                      editing === p.id ? (
                        <EditUpload photo={p} onDone={(saved) => { setEditing(""); if (saved) { setPhotos((all) => all?.map((x) => (x.id === p.id ? { ...x, ...saved, species: x.species } : x)) ?? null); refresh(p.species); } }} />
                      ) : (
                        <div className="row" style={{ gap: 6 }}>
                          <label className="field compact" aria-label="Review status">
                            <select value={p.review ?? "pending"} onChange={(e) => changeReview(p, e.target.value as PhotoReview)}>
                              {Object.entries(REVIEW_LABELS).map(([k, label]) => <option key={k} value={k}>{label}</option>)}
                            </select>
                          </label>
                          <button className="btn" onClick={() => setEditing(p.id)}>Edit credit</button>
                          {/* Permanent. Taking a photo off one species is "Remove from species" in that species' Edit mode. */}
                          <button className="btn reject" onClick={() => setDeleting(p)}>Delete</button>
                        </div>
                      )
                    ) : (
                      <span className="meta">Hosted on {p.source}. Managed in the curated list, so it can't be edited or deleted here.</span>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}
