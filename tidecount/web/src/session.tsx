import { createContext, ReactNode, useContext, useMemo, useState } from "react";

/** Sign-in is simulated in the browser. The server has no accounts, so nothing here protects data. */
export type Role = "volunteer" | "manager";
export type User = { role: Role; email: string; name: string; avatar: string };
type Profile = Pick<User, "name" | "avatar">;
type Stored = { role: Role | null; profiles: Partial<Record<Role, Profile>> };

export const ROLES: Record<Role, { label: string; about: string }> = {
  volunteer: { label: "Volunteer", about: "Counts fish and follows the work on the board." },
  manager: { label: "Manager", about: "Validator and coordinator. Runs surveys, reports and the team." },
};

const ACCOUNTS: Record<Role, { email: string; name: string }> = {
  volunteer: { email: "volunteer@tideflow.demo", name: "Demo Volunteer" },
  manager: { email: "manager@tideflow.demo", name: "Demo Manager" },
};
export const accountEmail = (role: Role) => ACCOUNTS[role].email;
export const homeLabel = (role: Role) => (role === "manager" ? "Surveys" : "My tasks");

const KEY = "tideflow-session";

function read(): Stored {
  try {
    return { role: null, profiles: {}, ...JSON.parse(localStorage.getItem(KEY) ?? "{}") };
  } catch {
    return { role: null, profiles: {} };
  }
}

function write(stored: Stored) {
  try {
    localStorage.setItem(KEY, JSON.stringify(stored));
  } catch {
    // Private windows can refuse storage. The session then lasts until the page reloads.
  }
}

type Session = {
  user: User | null;
  signIn: (role: Role) => void;
  signOut: () => void;
  updateProfile: (patch: Partial<Profile>) => void;
};

const SessionContext = createContext<Session | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const [stored, setStored] = useState(read);
  const commit = (next: Stored) => {
    write(next);
    setStored(next);
  };

  const value = useMemo<Session>(() => {
    const { role, profiles } = stored;
    return {
      user: role ? { role, avatar: "", ...ACCOUNTS[role], ...profiles[role] } : null,
      signIn: (next) => commit({ ...stored, role: next }),
      signOut: () => commit({ ...stored, role: null }),
      updateProfile: (patch) => {
        if (!role) return;
        const current = { name: ACCOUNTS[role].name, avatar: "", ...profiles[role] };
        commit({ ...stored, profiles: { ...profiles, [role]: { ...current, ...patch } } });
      },
    };
  }, [stored]);

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
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
