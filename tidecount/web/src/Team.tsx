import { FormEvent, useEffect, useState } from "react";
import { Menu } from "./Menu";
import { Modal } from "./Modal";
import { Avatar, Role, ROLES, useUser } from "./session";
import { invite, inviteLink, Member, removeMember, resend, resetTeam, setRole, useTeam } from "./teamStore";

/** What each role opens in the app. Kept beside the invite so the choice is an informed one. */
const CAN: Record<Role, string[]> = {
  volunteer: ["Count fish in the videos waiting", "Follow every video on the Workflow board", "Look up species in the wiki"],
  manager: ["Everything a volunteer can do", "Import footage and set up sites and stations", "Compare stations in the Station report", "Invite people and change roles"],
};

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const shortDate = (iso: string) => new Date(`${iso}T12:00:00`).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });

async function copy(text: string) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

function CopyLink({ member }: { member: Member }) {
  const [state, setState] = useState<"" | "copied" | "failed">("");
  return (
    <button className="btn" onClick={async () => setState((await copy(inviteLink(member))) ? "copied" : "failed")}>
      {state === "copied" ? "Copied" : state === "failed" ? "Copy failed" : "Copy link"}
    </button>
  );
}

function RolePicker({ value, onChange }: { value: Role; onChange: (role: Role) => void }) {
  return (
    <div className="role-pick" role="radiogroup" aria-label="Role">
      {(Object.keys(ROLES) as Role[]).map((r) => (
        <button key={r} type="button" role="radio" aria-checked={r === value} className="role-card" onClick={() => onChange(r)}>
          <b>{ROLES[r].label}</b>
          <span>{ROLES[r].about}</span>
        </button>
      ))}
    </div>
  );
}

/** Invite by email. The demo can't send mail, so it ends on the links to send by hand, and says so. */
function InviteDialog({ taken, onClose }: { taken: string[]; onClose: () => void }) {
  const [text, setText] = useState("");
  const [role, setRolePick] = useState<Role>("volunteer");
  const [error, setError] = useState("");
  const [sent, setSent] = useState<Member[] | null>(null);
  const emails = [...new Set(text.split(/[\s,;]+/).map((e) => e.trim().toLowerCase()).filter(Boolean))];

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!emails.length) return setError("Enter at least one email address.");
    const bad = emails.filter((x) => !EMAIL.test(x));
    if (bad.length) return setError(`${bad.join(", ")} ${bad.length === 1 ? "isn't an" : "aren't"} email ${bad.length === 1 ? "address" : "addresses"}.`);
    const already = emails.filter((x) => taken.includes(x));
    if (already.length) return setError(`${already.join(", ")} ${already.length === 1 ? "is" : "are"} already on the team.`);
    setSent(invite(emails, role));
  };

  if (sent) {
    return (
      <Modal title={sent.length === 1 ? "Invite ready" : `${sent.length} invites ready`} onClose={onClose}>
        <p className="hint">Tideflow can't send email in this demo. Copy each link and send it yourself. It opens sign-in with the role already chosen.</p>
        <div className="panel">
          {sent.map((m) => (
            <div className="invite-row" key={m.id}>
              <Avatar user={{ name: m.name, avatar: "" }} size={28} />
              <span className="invite-email">{m.email}</span>
              <span className="pill muted">{ROLES[m.role].label}</span>
              <CopyLink member={m} />
            </div>
          ))}
        </div>
        <div className="row dialog-foot"><button className="btn go" onClick={onClose}>Done</button></div>
      </Modal>
    );
  }

  return (
    <Modal title="Invite people" onClose={onClose}>
      <form className="stack" onSubmit={submit}>
        <label className="field">Email addresses
          <textarea className="record-input invite-input" rows={3} autoFocus value={text} onChange={(e) => { setText(e.target.value); setError(""); }} placeholder="jane@coastalaction.org, sam@coastalaction.org" />
          <span>Separate several with commas or new lines.</span>
        </label>
        <div className="stack" style={{ gap: 6 }}>
          <span className="meta">Role</span>
          <RolePicker value={role} onChange={setRolePick} />
          <ul className="rules meta">{CAN[role].map((c) => <li key={c}>{c}</li>)}</ul>
        </div>
        {error && <p className="meta" role="alert" style={{ color: "var(--down)" }}>{error}</p>}
        <div className="row dialog-foot">
          <button className="btn" type="button" onClick={onClose}>Cancel</button>
          <button className="btn go" type="submit" disabled={!emails.length}>{emails.length > 1 ? `Invite ${emails.length} people` : "Invite"}</button>
        </div>
      </form>
    </Modal>
  );
}

type Ask = { title: string; text: string; action: string; run: () => void };
type Filter = "all" | Role | "invited";

export function Team() {
  const user = useUser();
  const team = useTeam();
  const [inviting, setInviting] = useState(false);
  const [ask, setAsk] = useState<Ask | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const [query, setQuery] = useState("");
  const [toast, setToast] = useState("");

  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(""), 3000);
    return () => clearTimeout(timer);
  }, [toast]);

  const me: Member = { id: "me", name: user.name, email: user.email, role: user.role, status: "active", since: "" };
  const everyone = [me, ...team];
  const active = everyone.filter((m) => m.status === "active");
  const invited = everyone.filter((m) => m.status === "invited");
  const count = (f: Filter) => (f === "all" ? everyone.length : f === "invited" ? invited.length : active.filter((m) => m.role === f).length);
  const FILTERS: { key: Filter; label: string }[] = [
    { key: "all", label: "Everyone" },
    { key: "volunteer", label: "Volunteers" },
    { key: "manager", label: "Managers" },
    { key: "invited", label: "Invited" },
  ];

  const q = query.trim().toLowerCase();
  const shown = everyone.filter((m) => {
    if (q && !`${m.name} ${m.email}`.toLowerCase().includes(q)) return false;
    if (filter === "invited") return m.status === "invited";
    return filter === "all" || (m.role === filter && m.status === "active");
  });

  const changeRole = (m: Member, role: Role) => {
    setRole(m.id, role);
    setToast(`${m.name} is now a ${ROLES[role].label.toLowerCase()}.`);
  };
  const confirmRemove = (m: Member) => setAsk(m.status === "invited"
    ? { title: `Cancel the invite to ${m.email}?`, text: "The link stops working. You can invite them again later.", action: "Cancel invite", run: () => removeMember(m.id) }
    : { title: `Remove ${m.name}?`, text: "They lose access to this Tideflow. Counts they saved stay.", action: "Remove", run: () => removeMember(m.id) });

  return (
    <div className="stack" style={{ gap: 20 }}>
      <div className="pagehead">
        <div>
          <h1>Team</h1>
          <p className="lede">Who works in this Tideflow. Volunteers count; managers validate, coordinate and report.</p>
        </div>
        <button className="btn primary" onClick={() => setInviting(true)}>Invite people</button>
      </div>

      <div className="panel kpis">
        <div className="kpi"><span className="meta">Members</span><b>{active.length}</b></div>
        <div className="kpi"><span className="meta">Volunteers</span><b>{count("volunteer")}</b></div>
        <div className="kpi"><span className="meta">Managers</span><b>{count("manager")}</b></div>
        <div className="kpi"><span className="meta">Open invites</span><b>{invited.length}</b></div>
      </div>

      <div className="flow-bar">
        <div className="row" role="group" aria-label="Show">
          {FILTERS.map((f) => (
            <button key={f.key} className="chip" aria-pressed={filter === f.key} onClick={() => setFilter(f.key)}>
              {f.label} <span className="num">{count(f.key)}</span>
            </button>
          ))}
        </div>
        <span className="spacer" />
        <input className="flow-search" type="search" placeholder="Find a person" value={query} onChange={(e) => setQuery(e.target.value)} aria-label="Find a person by name or email" />
      </div>

      <div className="panel">
        <table className="cards team-table">
          <thead><tr><th>Person</th><th>Role</th><th>Status</th><th>Since</th><th aria-label="Actions" /></tr></thead>
          <tbody>
            {shown.map((m) => {
              const self = m.id === "me";
              const other: Role = m.role === "manager" ? "volunteer" : "manager";
              return (
                <tr key={m.id}>
                  <td>
                    <div className="person">
                      <Avatar user={self ? user : { name: m.name, avatar: "" }} size={34} />
                      <span className="stack" style={{ gap: 0, minWidth: 0 }}>
                        <b>{m.name}{self && <span className="meta"> (you)</span>}</b>
                        <span className="meta person-email">{m.email}</span>
                      </span>
                    </div>
                  </td>
                  <td data-label="Role"><span className={`pill ${m.role === "manager" ? "accent" : "muted"}`}>{ROLES[m.role].label}</span></td>
                  <td data-label="Status">{m.status === "invited" ? <span className="pill warn">Invited</span> : <span className="pill up">Active</span>}</td>
                  <td data-label="Since" className="meta">{self ? "—" : m.status === "invited" ? `Invited ${shortDate(m.since)}` : shortDate(m.since)}</td>
                  <td className="right">
                    {!self && (
                      <Menu label={`More for ${m.name}`}>
                        {m.status === "invited" && (
                          <>
                            <button role="menuitem" onClick={async () => setToast((await copy(inviteLink(m))) ? "Invite link copied." : "Couldn't copy. Your browser blocked it.")}>Copy invite link</button>
                            <button role="menuitem" onClick={() => { resend(m.id); setToast(`Invite to ${m.email} renewed.`); }}>Renew invite</button>
                          </>
                        )}
                        <button role="menuitem" onClick={() => changeRole(m, other)}>Make {ROLES[other].label.toLowerCase()}</button>
                        <hr />
                        <button role="menuitem" className="danger-item" onClick={() => confirmRemove(m)}>{m.status === "invited" ? "Cancel invite" : "Remove from team"}</button>
                      </Menu>
                    )}
                  </td>
                </tr>
              );
            })}
            {shown.length === 0 && <tr><td colSpan={5} className="meta" style={{ padding: 16 }}>Nobody matches.</td></tr>}
          </tbody>
        </table>
      </div>

      <div className="settings-grid role-grid">
        {(Object.keys(ROLES) as Role[]).map((r) => (
          <section className="panel settings-card" key={r}>
            <div className="row"><h2>{ROLES[r].label}</h2><span className="num meta">{count(r)} active</span></div>
            <p className="meta">{ROLES[r].about}</p>
            <ul className="rules">{CAN[r].map((c) => <li key={c}>{c}</li>)}</ul>
          </section>
        ))}
      </div>

      <p className="meta">Sample people, saved in this browser only. <button className="link" onClick={() => setAsk({ title: "Reset to the sample team?", text: "Invites and role changes made in this browser are lost.", action: "Reset", run: resetTeam })}>Reset to the sample</button></p>

      {inviting && <InviteDialog taken={everyone.map((m) => m.email.toLowerCase())} onClose={() => setInviting(false)} />}
      {ask && (
        <Modal title={ask.title} onClose={() => setAsk(null)}>
          <p>{ask.text}</p>
          <div className="row dialog-foot">
            <button className="btn" onClick={() => setAsk(null)}>Keep</button>
            <button className="btn danger" onClick={() => { ask.run(); setAsk(null); }}>{ask.action}</button>
          </div>
        </Modal>
      )}
      {toast && <div className="toast" role="status">{toast}</div>}
    </div>
  );
}
