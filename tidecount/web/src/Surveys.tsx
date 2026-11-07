import { FormEvent, ReactNode, useState } from "react";
import { Menu } from "./Menu";
import { Modal } from "./Modal";
import {
  activeTree, Flag, newId, placeLabel, removeItem, saveItem, setArchived, setPlace,
  Site, Station, suggestStation, SurveyData, Transect, useSurveys, useSurveyStatus, videoCount,
} from "./surveyStore";

const FLAGS: { value: Flag; label: string }[] = [{ value: "", label: "Not set" }, { value: "treatment", label: "Treatment" }, { value: "reference", label: "Reference" }];

type Field = { key: string; label: string; options?: { value: string; label: string }[]; hint?: string };
type EditState = { title: string; fields: Field[]; values: Record<string, string>; check?: (v: Record<string, string>) => string; save: (v: Record<string, string>) => Promise<string> };

function EditDialog({ edit, onClose }: { edit: EditState; onClose: () => void }) {
  const [values, setValues] = useState(edit.values);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  /** Checked here first for a quick answer, then on the server, whose reason shows if it refuses. */
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const checked = edit.check?.(values) ?? "";
    if (checked) return setError(checked);
    setBusy(true);
    const problem = await edit.save(values);
    setBusy(false);
    if (problem) return setError(problem);
    onClose();
  };
  return (
    <Modal title={edit.title} onClose={onClose}>
      <form className="stack" onSubmit={submit}>
        {edit.fields.map((f, i) => (
          <label className="field" key={f.key}>{f.label}
            {f.options
              ? <select value={values[f.key]} onChange={(e) => setValues({ ...values, [f.key]: e.target.value })}>{f.options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}</select>
              : <input autoFocus={i === 0} value={values[f.key]} onChange={(e) => setValues({ ...values, [f.key]: e.target.value })} />}
            {f.hint && <span>{f.hint}</span>}
          </label>
        ))}
        {error && <p className="meta" role="alert" style={{ color: "var(--down)" }}>{error}</p>}
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <button className="btn" type="button" onClick={onClose}>Cancel</button>
          <button className="btn go" type="submit" disabled={busy}>{busy ? "Saving…" : "Save"}</button>
        </div>
      </form>
    </Modal>
  );
}

type Ask = { title: string; text: string; action: string; run: () => Promise<string> };

function ConfirmDialog({ ask, onClose }: { ask: Ask; onClose: () => void }) {
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const go = async () => {
    setBusy(true);
    const problem = await ask.run();
    setBusy(false);
    if (problem) setError(problem);
    else onClose();
  };
  return (
    <Modal title={ask.title} onClose={onClose}>
      <p>{ask.text}</p>
      {error && <p className="meta" role="alert" style={{ color: "var(--down)" }}>{error}</p>}
      <div className="row" style={{ justifyContent: "flex-end" }}>
        <button className="btn" onClick={onClose}>Cancel</button>
        <button className="btn danger" disabled={busy} onClick={go}>{ask.action}</button>
      </div>
    </Modal>
  );
}

/** Names must be unique among siblings: file names are matched to stations by them. */
const unique = (taken: string[], word: string) => (v: Record<string, string>) => {
  const name = v.name.trim();
  if (!name) return `Enter a ${word} name.`;
  return taken.some((t) => t.toLowerCase() === name.toLowerCase()) ? `There's already a ${word} called ${name} here.` : "";
};

function useDialogs() {
  const [edit, setEdit] = useState<EditState | null>(null);
  const [ask, setAsk] = useState<Ask | null>(null);
  /** Why a change made without a dialog, like archiving, didn't go through. */
  const [problem, setProblem] = useState("");
  const dialogs = (
    <>
      {edit && <EditDialog edit={edit} onClose={() => setEdit(null)} />}
      {ask && <ConfirmDialog ask={ask} onClose={() => setAsk(null)} />}
    </>
  );
  return { setEdit, setAsk, dialogs, problem, setProblem };
}

/** Archive and restore always work. Delete only shows when no video refers to the item, so old records stay whole. */
function ItemMenu({ label, onEdit, archived, onArchive, used, onDelete }: { label: string; onEdit: () => void; archived: boolean; onArchive: () => void; used: number; onDelete: () => void }) {
  return (
    <Menu label={`More for ${label}`}>
      <button role="menuitem" onClick={onEdit}>Edit</button>
      <button role="menuitem" onClick={onArchive}>{archived ? "Restore" : "Archive"}</button>
      {used === 0 ? <button role="menuitem" onClick={onDelete}>Delete</button> : <p>Used by {used} {used === 1 ? "video" : "videos"}, so it can't be deleted.</p>}
    </Menu>
  );
}

const orDash = (s: string) => s || "—";
const plural = (n: number) => `${n} ${n === 1 ? "video" : "videos"}`;

export type StationStats = { videos: number; done: number; total: number };
type TreeProps = {
  site: Site;
  data: SurveyData;
  showArchived: boolean;
  editing: boolean;
  dialogs: ReturnType<typeof useDialogs>;
  videosAt: (stationId: string) => ReactNode;
  statsAt: (stationId: string) => StationStats;
  onImport: (stationId: string) => void;
  isOpen: (id: string) => boolean;
  toggle: (id: string) => void;
};

function Toggle({ open, label, onClick }: { open: boolean; label: string; onClick: () => void }) {
  return (
    <button className="tree-toggle" aria-expanded={open} aria-label={`${open ? "Collapse" : "Expand"} ${label}`} onClick={onClick}>
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden><path d="M9 6l6 6-6 6" /></svg>
    </button>
  );
}

/** How far the counting has got under a row. Fewer words than a table, and the same at every level. */
function Rollup({ stats, empty }: { stats: StationStats; empty: string }) {
  if (!stats.total) return <div className="tree-roll"><span className="meta">{stats.videos ? plural(stats.videos) : empty}</span></div>;
  const finished = stats.done >= stats.total;
  return (
    <div className="tree-roll">
      <span className="meta"><span className="num">{stats.done} of {stats.total}</span> points counted</span>
      <span className="bar wide"><i className={finished ? "up" : ""} style={{ width: `${(stats.done / stats.total) * 100}%` }} /></span>
    </div>
  );
}

const addUp = (all: StationStats[]) => all.reduce((a, b) => ({ videos: a.videos + b.videos, done: a.done + b.done, total: a.total + b.total }), { videos: 0, done: 0, total: 0 });

function SiteTree({ site, data, showArchived, editing, dialogs, videosAt, statsAt, onImport, isOpen, toggle }: TreeProps) {
  const { setEdit, setAsk, setProblem } = dialogs;
  const archive = (kind: "sites" | "transects" | "stations", item: { id: string; archived: boolean }) =>
    setArchived(kind, item.id, !item.archived).then(setProblem);
  const shown = <T extends { archived: boolean }>(list: T[]) => list.filter((x) => showArchived || !x.archived);
  const transects = shown(data.transects.filter((t) => t.siteId === site.id));
  const siblings = (t: Transect) => data.stations.filter((s) => s.transectId === t.id);

  const editSite = () => setEdit({
    title: "Edit site",
    fields: SITE_FIELDS,
    values: { name: site.name, coordinates: site.coordinates, flag: site.flag },
    check: unique(data.sites.filter((s) => s.id !== site.id).map((s) => s.name), "site"),
    save: (v) => saveItem("sites", { ...site, name: v.name.trim(), coordinates: v.coordinates.trim(), flag: v.flag as Flag }),
  });
  const addTransect = () => setEdit({
    title: `Add a transect to ${site.name}`,
    fields: [{ key: "name", label: "Transect name", hint: "Use the number in the file names, like T3." }],
    values: { name: `T${data.transects.filter((t) => t.siteId === site.id).length + 1}` },
    check: unique(data.transects.filter((t) => t.siteId === site.id).map((t) => t.name), "transect"),
    save: (v) => saveItem("transects", { id: newId(), siteId: site.id, name: v.name.trim(), archived: false }),
  });
  const editTransect = (t: Transect) => setEdit({
    title: `Edit ${t.name}`,
    fields: [{ key: "name", label: "Transect name" }],
    values: { name: t.name },
    check: unique(data.transects.filter((x) => x.siteId === site.id && x.id !== t.id).map((x) => x.name), "transect"),
    save: (v) => saveItem("transects", { ...t, name: v.name.trim() }),
  });
  const addStation = (t: Transect) => setEdit({
    title: `Add a station to ${t.name}`,
    fields: STATION_FIELDS,
    values: { name: `STAT${siblings(t).length + 1}`, coordinates: "", depth: "" },
    check: unique(siblings(t).map((s) => s.name), "station"),
    save: (v) => saveItem("stations", { id: newId(), transectId: t.id, name: v.name.trim(), coordinates: v.coordinates.trim(), depth: v.depth.trim(), archived: false }),
  });
  const editStation = (t: Transect, s: Station) => setEdit({
    title: `Edit ${t.name} · ${s.name}`,
    fields: STATION_FIELDS,
    values: { name: s.name, coordinates: s.coordinates, depth: s.depth },
    check: unique(siblings(t).filter((x) => x.id !== s.id).map((x) => x.name), "station"),
    save: (v) => saveItem("stations", { ...s, name: v.name.trim(), coordinates: v.coordinates.trim(), depth: v.depth.trim() }),
  });
  const confirmDelete = (kind: "sites" | "transects" | "stations", id: string, name: string, under: string) => setAsk({
    title: `Delete ${name}?`,
    text: `This can't be undone.${under ? ` ${under}` : ""}`,
    action: "Delete",
    run: () => removeItem(kind, id),
  });

  const stationsOf = (t: Transect) => shown(siblings(t));
  const siteStats = addUp(transects.flatMap(stationsOf).map((x) => statsAt(x.id)));
  const siteOpen = editing || isOpen(site.id);

  return (
    <section className={`panel ${site.archived ? "is-archived" : ""}`}>
      <div className="tree-head">
        <div className="tree-name">
          {!editing && <Toggle open={siteOpen} label={site.name} onClick={() => toggle(site.id)} />}
          <h2>{site.name}</h2>
          {site.flag && <span className={`pill ${site.flag === "treatment" ? "accent" : "muted"}`}>{site.flag === "treatment" ? "Treatment" : "Reference"}</span>}
          {site.archived && <span className="pill warn">Archived</span>}
          {editing && site.coordinates && <span className="meta">{site.coordinates}</span>}
        </div>
        {editing
          ? <ItemMenu label={site.name} onEdit={editSite} archived={site.archived} onArchive={() => archive("sites", site)} used={videoCount(data, "sites", site.id)} onDelete={() => confirmDelete("sites", site.id, site.name, "Its transects and stations go with it.")} />
          : <Rollup stats={siteStats} empty="No footage yet" />}
      </div>
      {siteOpen && transects.map((t) => {
        const stations = stationsOf(t);
        const filmed = stations.filter((x) => statsAt(x.id).videos > 0).length;
        const open = editing || isOpen(t.id);
        return (
          <div key={t.id} className={t.archived ? "is-archived" : ""}>
            <div className="tree-row tree-transect">
              <div className="tree-name">
                {!editing && <Toggle open={open} label={t.name} onClick={() => toggle(t.id)} />}
                <b>{t.name}</b>
                {t.archived && <span className="pill warn">Archived</span>}
                {!editing && <span className="meta">{filmed} of {stations.length} {stations.length === 1 ? "station" : "stations"} filmed</span>}
              </div>
              {editing
                ? <ItemMenu label={t.name} onEdit={() => editTransect(t)} archived={t.archived} onArchive={() => archive("transects", t)} used={videoCount(data, "transects", t.id)} onDelete={() => confirmDelete("transects", t.id, t.name, "Its stations go with it.")} />
                : <Rollup stats={addUp(stations.map((x) => statsAt(x.id)))} empty="" />}
            </div>
            {open && stations.map((x) => {
              const stats = statsAt(x.id);
              const details = [x.coordinates, x.depth && `${x.depth} m`].filter(Boolean).join(" · ");
              const videosOpen = stats.videos > 0 && isOpen(x.id);
              return (
                <div key={x.id} className={x.archived ? "is-archived" : ""}>
                  <div className="tree-row tree-leaf">
                    <div className="tree-name">
                      {!editing && stats.videos > 0 ? <Toggle open={videosOpen} label={x.name} onClick={() => toggle(x.id)} /> : <span className="tree-gap" />}
                      <span>{x.name}</span>
                      {x.archived && <span className="pill warn">Archived</span>}
                      {editing && <span className="meta">{details || "No location details"}</span>}
                      {!editing && stats.videos === 0 && !x.archived && <button className="link tree-import" onClick={() => onImport(x.id)}>Import footage</button>}
                    </div>
                    {editing
                      ? <ItemMenu label={`${t.name} ${x.name}`} onEdit={() => editStation(t, x)} archived={x.archived} onArchive={() => archive("stations", x)} used={videoCount(data, "stations", x.id)} onDelete={() => confirmDelete("stations", x.id, `${t.name} · ${x.name}`, "")} />
                      : <Rollup stats={stats} empty="No footage yet" />}
                  </div>
                  {!editing && videosOpen && videosAt(x.id)}
                </div>
              );
            })}
            {editing && <button className="tree-add tree-add-station" onClick={() => addStation(t)}>+ Add station</button>}
          </div>
        );
      })}
      {editing && <button className="tree-add" onClick={addTransect}>+ Add transect</button>}
      {!editing && siteOpen && transects.length === 0 && <p className="meta tree-empty">No transects yet.</p>}
    </section>
  );
}

const SITE_FIELDS: Field[] = [
  { key: "name", label: "Site name" },
  { key: "coordinates", label: "Coordinates", hint: "Latitude, longitude. Optional." },
  { key: "flag", label: "Treatment or reference", options: FLAGS },
];
const STATION_FIELDS: Field[] = [
  { key: "name", label: "Station name", hint: "Use the number in the file names, like STAT4." },
  { key: "coordinates", label: "Coordinates", hint: "Latitude, longitude. Optional." },
  { key: "depth", label: "Depth in metres", hint: "Optional." },
];

type ListProps = Pick<TreeProps, "videosAt" | "statsAt" | "onImport"> & { editing: boolean };

/**
 * The whole survey, as one tree with the work rolled up at every level. Setting up the structure is rare,
 * so it stays out of sight until a manager turns on editing.
 */
export function SiteList({ editing, videosAt, statsAt, onImport }: ListProps) {
  const data = useSurveys();
  const { loaded, error } = useSurveyStatus();
  const dialogs = useDialogs();
  const [showArchived, setShowArchived] = useState(false);
  const [closed, setClosed] = useState<string[]>([]);
  const includeArchived = editing && showArchived;
  const sites = data.sites.filter((s) => includeArchived || !s.archived);
  const toggle = (id: string) => setClosed(closed.includes(id) ? closed.filter((x) => x !== id) : [...closed, id]);

  const addSite = () => dialogs.setEdit({
    title: "Add a site",
    fields: SITE_FIELDS,
    values: { name: "", coordinates: "", flag: "" },
    check: unique(data.sites.map((s) => s.name), "site"),
    save: (v) => saveItem("sites", { id: newId(), name: v.name.trim(), coordinates: v.coordinates.trim(), flag: v.flag as Flag, archived: false }),
  });

  if (!loaded) return <div className="panel panel-pad"><p className="meta" role={error ? "alert" : undefined}>{error || "Loading the surveys…"}</p></div>;

  return (
    <>
      {error && <p className="meta" role="alert" style={{ color: "var(--down)" }}>{error}</p>}
      {dialogs.problem && <p className="meta" role="alert" style={{ color: "var(--down)" }}>{dialogs.problem}</p>}
      {sites.map((s) => (
        <SiteTree
          key={s.id}
          site={s}
          data={data}
          showArchived={includeArchived}
          editing={editing}
          dialogs={dialogs}
          videosAt={videosAt}
          statsAt={statsAt}
          onImport={onImport}
          isOpen={(id) => !closed.includes(id)}
          toggle={toggle}
        />
      ))}
      {sites.length === 0 && !editing && <div className="panel panel-pad"><p className="meta">No sites yet.</p></div>}
      {editing && (
        <>
          <button className="tree-add tree-add-site" onClick={addSite}>+ Add site</button>
          <div className="row" style={{ justifyContent: "space-between" }}>
            <button className="chip" aria-pressed={showArchived} onClick={() => setShowArchived(!showArchived)}>Show archived</button>
            <p className="meta">Saved on the server, so the whole team sees the same sites.</p>
          </div>
        </>
      )}
      {dialogs.dialogs}
    </>
  );
}

/** One list of stations, grouped by site. Every video has to sit under one of them. */
export function StationPicker({ data, value, onChange }: { data: SurveyData; value: string; onChange: (stationId: string) => void }) {
  return (
    <label className="field">Station
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">Choose a station</option>
        {activeTree(data).map(({ site, stations }) => (
          <optgroup key={site.id} label={site.name}>
            {stations.map((s) => <option key={s.station.id} value={s.station.id}>{s.label}</option>)}
          </optgroup>
        ))}
      </select>
    </label>
  );
}

export function FilmedOn({ value, onChange }: { value: string; onChange: (date: string) => void }) {
  return (
    <label className="field">Filmed on
      <input type="date" value={value} onChange={(e) => onChange(e.target.value)} />
      <span>Reports compare seasons by this date.</span>
    </label>
  );
}

/** File a video under a station. A name like T1-STAT2 411.MP4 pre-fills it, for the person to confirm. */
export function StationDialog({ root, name, onClose }: { root: string; name: string; onClose: () => void }) {
  const data = useSurveys();
  const current = data.places[root];
  const suggested = current ? "" : suggestStation(data, name);
  const [stationId, pick] = useState(current ?? suggested);
  const [date, setDate] = useState(data.filmedOn[root] ?? "");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const save = async () => {
    setBusy(true);
    const problem = await setPlace(root, stationId, date);
    setBusy(false);
    if (problem) setError(problem);
    else onClose();
  };
  return (
    <Modal title={name} onClose={onClose}>
      <div className="stack">
        {suggested && <p className="meta">Filled in from the file name. Check it's right.</p>}
        {current && <p className="meta">Now: {placeLabel(data, current)}</p>}
        <StationPicker data={data} value={stationId} onChange={pick} />
        <FilmedOn value={date} onChange={setDate} />
        {error && <p className="meta" role="alert" style={{ color: "var(--down)" }}>{error}</p>}
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <button className="btn" onClick={onClose}>Cancel</button>
          <button className="btn go" disabled={!stationId || busy} onClick={save}>{busy ? "Saving…" : "Save"}</button>
        </div>
      </div>
    </Modal>
  );
}
