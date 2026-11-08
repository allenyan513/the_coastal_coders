import { FormEvent, ReactNode, useEffect, useState } from "react";
import { Link, Navigate, useNavigate, useSearchParams } from "react-router-dom";
import { authApi } from "./api";
import { ROLES, Role, useSession } from "./session";
import { acceptInvite, findMember, type Member } from "./teamStore";

/** Only follow paths inside the app, so a crafted link can't send someone elsewhere after sign-in. */
function safeNext(next: string | null) {
  return next && next.startsWith("/") && !next.startsWith("//") ? next : "/workspace";
}

const message = (e: unknown) => (e instanceof Error ? e.message : String(e));

function Card({ children, onSubmit }: { children: ReactNode; onSubmit: (e: FormEvent) => void }) {
  return (
    <main className="login">
      <form className="panel login-card" onSubmit={onSubmit}>
        <div>
          <p className="login-brand">Tideflow</p>
          <p className="lede">From footage to findings, in one place.</p>
        </div>
        {children}
      </form>
    </main>
  );
}

function Problem({ text }: { text: string }) {
  return text ? <p className="meta" role="alert" style={{ color: "var(--down)" }}>{text}</p> : null;
}

/**
 * Sign-in, sign-up (open to anyone: pick Volunteer or Manager), and invite and password-reset links.
 * After sign-up the new password is shown once, before going on, so it isn't lost.
 */
export function Login() {
  const { user, loading } = useSession();
  const [params] = useSearchParams();
  const next = safeNext(params.get("next"));
  const token = params.get("invite");
  // An invite from the Team page's sample team (?invite=m-…) picks the role it was sent for, as before.
  const invited = findMember(token);
  const [mode, setMode] = useState<"signin" | "register">(params.has("register") ? "register" : "signin");
  // The Volunteer / Manager toggle, shared by both forms so the choice carries across.
  const [role, setRole] = useState<Role>(invited?.role ?? "volunteer");
  const [created, setCreated] = useState<{ email: string; password: string } | null>(null);

  if (loading) return <main className="login"><p className="meta">Loading…</p></main>;
  if (created) return <NewPassword {...created} next={next} />; // signed in already, but show the password first
  if (token && !invited) return <AcceptLink token={token} next={next} />;
  if (user) return <Navigate to={next} replace />;
  return mode === "register"
    ? <Register role={role} onRole={setRole} onCreated={setCreated} onSignIn={() => setMode("signin")} />
    : <SignIn role={role} onRole={setRole} onRegister={() => setMode("register")} invited={invited} />;
}

/** The two role chips, with what the chosen role does underneath, as on the old sign-in. */
function RoleToggle({ role, onRole }: { role: Role; onRole: (r: Role) => void }) {
  return (
    <>
      <div className="login-roles" role="group" aria-label="Sign in as">
        {(Object.keys(ROLES) as Role[]).map((r) => (
          <button key={r} type="button" className="chip" aria-pressed={r === role} onClick={() => onRole(r)}>{ROLES[r].label}</button>
        ))}
      </div>
      <p className="meta">{ROLES[role].about}</p>
    </>
  );
}

const DEMO_EMAIL: Record<Role, string> = { volunteer: "volunteer@tideflow.demo", manager: "manager@tideflow.demo" };

/**
 * The demo sign-in, as before: pick a role, the email and password are filled in, and Sign in opens
 * that role's shared demo account on the server (POST /api/auth/demo). No password is checked; the
 * session and every permission check are the server's, as for any account.
 */
function SignIn({ role, onRole, invited }: { role: Role; onRole: (r: Role) => void; onRegister: () => void; invited?: Member }) {
  const { signedIn } = useSession();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true); setError("");
    try {
      if (invited?.status === "invited") acceptInvite(invited.id); // the sample team marks them active, as before
      const r = await authApi.demo(role);
      signedIn(r.user); // the page then follows ?next= (Login sees the user)
    } catch (err) {
      setError(message(err));
      setBusy(false);
    }
  };
  return (
    <Card onSubmit={submit}>
      {invited && <p className="hint">You're invited to Tideflow as a {ROLES[invited.role].label.toLowerCase()} ({invited.email}).</p>}
      <RoleToggle role={role} onRole={onRole} />
      <label className="field">Email
        <input value={DEMO_EMAIL[role]} readOnly />
      </label>
      <label className="field">Password
        <input type="password" value="demo-password" readOnly autoComplete="off" />
      </label>
      <Problem text={error} />
      <button className="btn primary block" type="submit" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
      <p className="meta">Demo sign-in. Pick a role; no password is checked.</p>
    </Card>
  );
}

/** Name, email and role, as before. The server makes the password and signs the person in. */
function Register({ role, onRole, onCreated, onSignIn }: {
  role: Role; onRole: (r: Role) => void; onCreated: (c: { email: string; password: string }) => void; onSignIn: () => void;
}) {
  const { signedIn } = useSession();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true); setError("");
    try {
      const r = await authApi.register(name, email, role);
      onCreated({ email: r.user.email, password: r.password }); // first, so the password shows before anything moves on
      signedIn(r.user);
    } catch (err) {
      setError(message(err));
      setBusy(false);
    }
  };
  return (
    <Card onSubmit={submit}>
      <RoleToggle role={role} onRole={onRole} />
      <label className="field">Your name
        <input required autoFocus autoComplete="name" value={name} onChange={(e) => setName(e.target.value)} />
      </label>
      <label className="field">Email
        <input type="email" required autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} />
      </label>
      <Problem text={error} />
      <button className="btn primary block" type="submit" disabled={busy}>{busy ? "Creating…" : "Create account"}</button>
      <p className="meta">Tideflow makes your password and shows it once. You can change it later in Settings.</p>
      <p className="meta">Already have an account? <button type="button" className="link" onClick={onSignIn}>Sign in</button></p>
    </Card>
  );
}

/** The generated password, shown this once, with a way to copy it. */
function NewPassword({ email, password, next }: { email: string; password: string; next: string }) {
  const navigate = useNavigate();
  const [copied, setCopied] = useState<"" | "yes" | "no">("");
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(password);
      setCopied("yes");
    } catch {
      setCopied("no");
    }
  };
  return (
    <Card onSubmit={(e) => { e.preventDefault(); navigate(next, { replace: true }); }}>
      <p className="hint">Your account is ready and you're signed in as {email}.</p>
      <label className="field">Your password
        <input readOnly value={password} className="num" onFocus={(e) => e.currentTarget.select()} aria-describedby="password-note" />
      </label>
      <div className="row">
        <button type="button" className="btn" onClick={copy}>{copied === "yes" ? "Copied" : "Copy password"}</button>
        {copied === "no" && <span className="meta" role="status">Your browser blocked copying. Select the password and copy it.</span>}
      </div>
      <p className="meta" id="password-note">
        Save it somewhere safe now: it's shown only this once and Tideflow keeps no copy. This browser stays signed in,
        and you can choose your own password in Settings.
      </p>
      <button className="btn primary block" type="submit">Continue</button>
    </Card>
  );
}


/** An invite (a new account) or a password-reset link (a new password for an existing one). */
function AcceptLink({ token, next }: { token: string; next: string }) {
  const { signedIn } = useSession();
  const navigate = useNavigate();
  const [link, setLink] = useState<{ email: string; role: Role; kind: "invite" | "reset"; name: string } | null>(null);
  const [error, setError] = useState("");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    authApi.invite(token).then((l) => setLink(l)).catch((e) => setError(message(e)));
  }, [token]);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (password !== confirm) return setError("The two passwords don't match.");
    setBusy(true); setError("");
    try {
      const r = await authApi.acceptInvite(token, name, password);
      signedIn(r.user);
      navigate(next, { replace: true });
    } catch (err) {
      setError(message(err));
      setBusy(false);
    }
  };

  if (!link) {
    return (
      <Card onSubmit={(e) => e.preventDefault()}>
        {error ? <Problem text={error} /> : <p className="meta">Checking the link…</p>}
        {error && <p className="meta"><Link to="/login">Go to sign-in</Link></p>}
      </Card>
    );
  }
  const reset = link.kind === "reset";
  return (
    <Card onSubmit={submit}>
      <p className="hint">
        {reset
          ? <>Set a new password for {link.email}. You'll be signed out everywhere else.</>
          : <>You're invited to Tideflow as a {ROLES[link.role].label.toLowerCase()} ({link.email}).</>}
      </p>
      {!reset && <label className="field">Your name<input required autoFocus value={name} onChange={(e) => setName(e.target.value)} /></label>}
      <label className="field">{reset ? "New password" : "Password"} (at least 10 characters)
        <input type="password" required minLength={10} autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} />
      </label>
      <label className="field">Password again
        <input type="password" required autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} />
      </label>
      <Problem text={error} />
      <button className="btn primary block" type="submit" disabled={busy}>{busy ? "Saving…" : reset ? "Set password and sign in" : "Join Tideflow"}</button>
    </Card>
  );
}
