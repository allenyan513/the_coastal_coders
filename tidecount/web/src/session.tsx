import { createContext, FormEvent, ReactNode, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { authApi, onReauthNeeded, onSignedOut, ServerUser } from "./api";
import { Modal } from "./Modal";

/**
 * Who is signed in, from the server. The session itself is an HttpOnly cookie the browser keeps and
 * this code never sees; the role comes from the server's account on every request. Only the profile
 * photo stays in this browser (it's cosmetic), stored by email.
 */
export type Role = "volunteer" | "manager";
export type User = { id: number; role: Role; email: string; name: string; avatar: string };
type Profile = Pick<User, "name" | "avatar">;

export const ROLES: Record<Role, { label: string; about: string }> = {
  volunteer: { label: "Volunteer", about: "Counts fish and follows the work on the board." },
  manager: { label: "Manager", about: "Validator and coordinator. Runs surveys, reports and the team." },
};

export const homeLabel = (role: Role) => (role === "manager" ? "Surveys" : "My tasks");

const AVATARS = "tideflow-avatars";
// From the simulated sign-in this replaces. (The sample team, tideflow-team-v1, stays: the Team page uses it.)
for (const old of ["tideflow-session"]) {
  try { localStorage.removeItem(old); } catch { /* storage can be off in private windows */ }
}

// The display names used on the shared demo accounts, kept in this browser, as in the old demo,
// so one teammate renaming "Demo Manager" doesn't rename it for everyone else.
const NAMES = "tideflow-names";

/** The shared demo accounts (the demo sign-in). Their name and password live in each browser, not the server. */
export const isDemoAccount = (email: string) => email.endsWith("@tideflow.demo");

function stored(key: string): Record<string, string> {
  try { return JSON.parse(localStorage.getItem(key) ?? "{}"); } catch { return {}; }
}
function store(key: string, email: string, value: string) {
  try {
    const all = stored(key);
    if (value) all[email] = value; else delete all[email];
    localStorage.setItem(key, JSON.stringify(all));
  } catch { /* it then lasts until the page reloads */ }
}
const avatars = () => stored(AVATARS);
const saveAvatar = (email: string, avatar: string) => store(AVATARS, email, avatar);

type Session = {
  user: User | null;
  /** True until the server has said who this is, so pages don't send a signed-in person to sign-in. */
  loading: boolean;
  /** True while Tideflow has no accounts: sign-in offers first-time setup instead. */
  setupNeeded: boolean;
  signIn: (email: string, password: string) => Promise<void>;
  /** After setup or accepting an invite, which sign the person in on the server. */
  signedIn: (user: ServerUser) => void;
  signOut: () => Promise<void>;
  updateProfile: (patch: Partial<Profile>) => Promise<void>;
};

const SessionContext = createContext<Session | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const [server, setServer] = useState<ServerUser | null>(null);
  const [loading, setLoading] = useState(true);
  const [setupNeeded, setSetupNeeded] = useState(false);
  const [avatar, setAvatar] = useState("");
  const [localName, setLocalName] = useState("");
  const [reauth, setReauth] = useState<((ok: boolean) => void) | null>(null);

  const take = useCallback((u: ServerUser | null) => {
    setServer(u);
    setAvatar(u ? avatars()[u.email] ?? "" : "");
    setLocalName(u && isDemoAccount(u.email) ? stored(NAMES)[u.email] ?? "" : "");
  }, []);

  useEffect(() => {
    authApi.me()
      .then((r) => { take(r.user); setSetupNeeded(r.setup_needed); })
      .catch(() => take(null))
      .finally(() => setLoading(false));
    // A 401 anywhere means the session ended (expired, signed out elsewhere, access removed).
    onSignedOut(() => take(null));
    // A sensitive manager action asks for the password once, then the request is sent again.
    onReauthNeeded(() => new Promise<boolean>((resolve) => setReauth(() => resolve)));
  }, [take]);

  const value = useMemo<Session>(() => ({
    user: server ? { ...server, name: localName || server.name, role: server.role as Role, avatar } : null,
    loading,
    setupNeeded,
    signIn: async (email, password) => {
      const r = await authApi.login(email, password);
      take(r.user);
      setSetupNeeded(false);
    },
    signedIn: (u) => { take(u); setSetupNeeded(false); },
    signOut: async () => {
      try { await authApi.logout(); } finally { take(null); }
    },
    updateProfile: async (patch) => {
      if (!server) return;
      if (patch.avatar !== undefined) {
        saveAvatar(server.email, patch.avatar);
        setAvatar(patch.avatar);
      }
      if (patch.name !== undefined && isDemoAccount(server.email)) {
        // A shared demo account: the name is this browser's own, as in the old demo.
        store(NAMES, server.email, patch.name === server.name ? "" : patch.name);
        setLocalName(patch.name === server.name ? "" : patch.name);
      } else if (patch.name !== undefined && patch.name !== server.name) {
        const r = await authApi.updateMe(patch.name);
        setServer(r.user);
      }
    },
  }), [server, avatar, localName, loading, setupNeeded, take]);

  return (
    <SessionContext.Provider value={value}>
      {children}
      {reauth && <ConfirmPassword onDone={(ok) => { reauth(ok); setReauth(null); }} />}
    </SessionContext.Provider>
  );
}

/** Asked before a sensitive manager action (team changes, permanent deletes) when the last confirmation is old. */
function ConfirmPassword({ onDone }: { onDone: (ok: boolean) => void }) {
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true); setError("");
    try {
      await authApi.reauth(password);
      onDone(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setBusy(false);
    }
  };
  return (
    <Modal title="Confirm your password" onClose={() => onDone(false)} locked={busy}>
      <form className="stack" onSubmit={submit}>
        <p className="meta">This changes who can do what, or can't be undone, so Tideflow asks for your password again.</p>
        <label className="field">Password
          <input type="password" autoComplete="current-password" autoFocus value={password} onChange={(e) => setPassword(e.target.value)} />
        </label>
        {error && <p className="meta" role="alert" style={{ color: "var(--down)" }}>{error}</p>}
        <div className="row dialog-foot">
          <button className="btn" type="button" onClick={() => onDone(false)} disabled={busy}>Cancel</button>
          <button className="btn go" type="submit" disabled={busy || !password}>{busy ? "Checking…" : "Confirm"}</button>
        </div>
      </form>
    </Modal>
  );
}

export function useSession() {
  const session = useContext(SessionContext);
  if (!session) throw new Error("useSession needs a SessionProvider");
  return session;
}

/** The signed-in person, for pages the shell only shows after sign-in. */
export function useUser() {
  const { user } = useSession();
  if (!user) throw new Error("useUser needs a signed-in person");
  return user;
}

export function Avatar({ user, size = 32 }: { user: Pick<User, "name" | "avatar">; size?: number }) {
  if (user.avatar) return <img className="avatar" src={user.avatar} alt="" width={size} height={size} />;
  const initials = user.name.split(/\s+/).filter(Boolean).slice(0, 2).map((word) => word[0].toUpperCase()).join("");
  return <span className="avatar" style={{ width: size, height: size, fontSize: size * 0.38 }} aria-hidden>{initials || "?"}</span>;
}
