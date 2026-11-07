import { FormEvent, useState } from "react";
import { Navigate, useSearchParams } from "react-router-dom";
import { accountEmail, Role, ROLES, useSession } from "./session";
import { acceptInvite, findMember } from "./teamStore";

/** Only follow paths inside the app, so a crafted link can't send someone elsewhere after sign-in. */
function safeNext(next: string | null) {
  return next && next.startsWith("/") && !next.startsWith("//") ? next : "/";
}

export function Login() {
  const { user, signIn } = useSession();
  const [params] = useSearchParams();
  // An invite link from the Team page carries ?invite=<id>, which picks the role it was sent for.
  const invited = findMember(params.get("invite"));
  const [role, setRole] = useState<Role>(invited?.role ?? "volunteer");

  if (user) return <Navigate to={safeNext(params.get("next"))} replace />;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (invited?.status === "invited") acceptInvite(invited.id);
    signIn(role);
  };

  return (
    <main className="login">
      <form className="panel login-card" onSubmit={submit}>
        <div>
          <p className="login-brand">Tideflow</p>
          <p className="lede">From footage to findings, in one place.</p>
        </div>
        {invited && <p className="hint">You're invited to Tideflow as a {ROLES[invited.role].label.toLowerCase()} ({invited.email}).</p>}
        <div className="login-roles" role="group" aria-label="Sign in as">
          {(Object.keys(ROLES) as Role[]).map((r) => (
            <button key={r} type="button" className="chip" aria-pressed={r === role} onClick={() => setRole(r)}>{ROLES[r].label}</button>
          ))}
        </div>
        <p className="meta">{ROLES[role].about}</p>
        <label className="field">Email
          <input value={accountEmail(role)} readOnly />
        </label>
        <label className="field">Password
          <input type="password" value="demo-password" readOnly autoComplete="off" />
        </label>
        <button className="btn primary block" type="submit">Sign in</button>
        <p className="meta">Demo sign-in. Pick a role; no password is checked.</p>
      </form>
    </main>
  );
}
