"""Sign-in and roles: accounts, sessions, and the checks every route depends on.

- Passwords are hashed with scrypt (standard library). Session and invite tokens are random and only
  their SHA-256 is stored, so a copied database can't be used to sign in.
- The browser holds the session token in an HttpOnly, SameSite=Lax cookie, Secure on HTTPS. The role
  is read from the users table on every request; nothing the browser says about itself is trusted.
- Sessions last 30 days without use and 90 days at most, and survive restarts (they're in SQLite).
- Writes from another site are refused by checking Origin (see `origin_problem`), on top of SameSite.
- Anyone may sign up as a volunteer or a manager (routes/auth.py `register`); the server generates
  the password. The older one-time setup code for a first manager (`ensure_setup_code`) is kept but
  no longer printed on its own.

Routes declare who may call them with the lists at the bottom: PUBLIC, SIGNED_IN, MANAGER and
RECENT_MANAGER (a manager who confirmed their password in the last few minutes, for sensitive actions).
"""
import hashlib
import hmac
import ipaddress
import os
import secrets
import threading
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

from fastapi import Depends, HTTPException, Request, Response

from . import api_guard, db

IDLE_S = 30 * 86400          # signed out after 30 days without use
ABSOLUTE_S = 90 * 86400      # and after 90 days whatever happens
TOUCH_S = 3600               # last_seen is written at most once an hour
REAUTH_S = 10 * 60           # how long a password confirmation covers sensitive actions
LINK_S = 7 * 86400           # invite and password-reset links
SETUP_S = 3600               # the first-manager setup code
ROLES = ("manager", "volunteer")
MIN_PASSWORD, MAX_PASSWORD = 10, 256
SECURE_COOKIE = "__Host-tideflow_session"  # the browser only accepts it Secure, from this host, on path /
PLAIN_COOKIE = "tideflow_session"          # plain HTTP on this computer (start.bat)
REAUTH_HEADER = "X-Tideflow-Reauth"

# Sign-in limits, per visitor address and per email. Reuse the wiki's visitor limiter.
login_by_ip = api_guard.Limiter(int(os.environ.get("TIDECOUNT_LOGIN_PER_10_MIN", 10)), 600.0)
failures_by_email = api_guard.Limiter(5, 900.0)
sensitive_by_ip = api_guard.Limiter(5, 900.0)  # setup, invite acceptance, password change and confirmation
# New accounts per address: a team signing up from one office shares an address, so this is looser.
register_by_ip = api_guard.Limiter(int(os.environ.get("TIDECOUNT_SIGNUPS_PER_HOUR", 20)), 3600.0)


# --- passwords ---------------------------------------------------------------------------------

_N, _R, _P, _LEN = 2 ** 14, 8, 1, 64


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=_LEN, maxmem=64 * 1024 * 1024)
    return f"scrypt${_N}${_R}${_P}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        kind, n, r, p, salt, digest = stored.split("$")
        if kind != "scrypt":
            return False
        found = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p),
                               dklen=len(digest) // 2, maxmem=64 * 1024 * 1024)
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(found.hex(), digest)


_dummy: list[str] = []


def burn_time(password: str) -> None:
    """An unknown email costs as long as a wrong password, so timing doesn't say which emails exist."""
    if not _dummy:
        _dummy.append(hash_password(secrets.token_hex(16)))
    verify_password(password, _dummy[0])


# The demo sign-in (routes/auth.py `demo`): one shared account per role, opened without a password.
DEMO_DOMAIN = "@tideflow.demo"
DEMO_ACCOUNTS = {"volunteer": ("volunteer@tideflow.demo", "Demo Volunteer"), "manager": ("manager@tideflow.demo", "Demo Manager")}
DEMO_EMAILS = {email for email, _name in DEMO_ACCOUNTS.values()}


def demo_signin_enabled() -> bool:
    """On unless TIDECOUNT_DEMO_SIGNIN is 0. Anyone can then sign in as the demo manager."""
    return os.environ.get("TIDECOUNT_DEMO_SIGNIN", "1").strip().lower() not in ("0", "false", "no", "off")


_PASSWORD_ALPHABET = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O, 1/l/I


def generate_password() -> str:
    """A new account's password: 20 characters from `secrets`, about 115 bits, in groups of five so
    it can be read and typed (e.g. "k7Qm2-xP9ta-Rv4Ne-8hWcZ")."""
    chars = "".join(secrets.choice(_PASSWORD_ALPHABET) for _ in range(20))
    return "-".join(chars[i:i + 5] for i in range(0, 20, 5))


def password_problem(password: str) -> str | None:
    if len(password) < MIN_PASSWORD:
        return f"Use at least {MIN_PASSWORD} characters."
    if len(password) > MAX_PASSWORD:
        return f"Use at most {MAX_PASSWORD} characters."
    return None


def digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def clean_email(email: str) -> str:
    email = (email or "").strip().lower()
    if len(email) > 254 or "@" not in email or email.startswith("@") or email.endswith("@") or any(c.isspace() for c in email):
        raise HTTPException(400, "Enter a valid email address.")
    return email


def clean_name(name: str) -> str:
    name = " ".join((name or "").split())
    if not name or len(name) > 100:
        raise HTTPException(400, "Enter a name of up to 100 characters.")
    return name


# --- requests: address, HTTPS and cookies ------------------------------------------------------

def _private_peer(request: Request) -> bool:
    try:
        return ipaddress.ip_address(request.client.host if request.client else "").is_private
    except ValueError:
        return False


def client_ip(request: Request) -> str:
    return api_guard.client_ip(request.client.host if request.client else None, request.headers.get("x-forwarded-for"))


def is_https(request: Request) -> bool:
    """HTTPS as the browser sees it. Behind Caddy the app is reached over plain HTTP on Docker's
    network, so X-Forwarded-Proto counts, but only from a private-network peer (Caddy), never from
    a visitor who could write it themselves. TIDECOUNT_SECURE_COOKIES=1 or 0 overrides the guess."""
    forced = os.environ.get("TIDECOUNT_SECURE_COOKIES", "auto").strip().lower()
    if forced in ("1", "true", "yes"):
        return True
    if forced in ("0", "false", "no"):
        return False
    if request.url.scheme == "https":
        return True
    proto = request.headers.get("x-forwarded-proto", "").split(",")[0].strip().lower()
    return proto == "https" and _private_peer(request)


def cookie_name(request: Request) -> str:
    return SECURE_COOKIE if is_https(request) else PLAIN_COOKIE


def set_session_cookie(response: Response, request: Request, token: str) -> None:
    response.set_cookie(cookie_name(request), token, max_age=ABSOLUTE_S, path="/", httponly=True,
                        samesite="lax", secure=is_https(request))


def clear_session_cookie(response: Response, request: Request) -> None:
    response.delete_cookie(cookie_name(request), path="/", httponly=True, samesite="lax", secure=is_https(request))


# --- cross-site request protection -------------------------------------------------------------

UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}


def _origin_of(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}".lower() if parts.scheme and parts.netloc else ""


def allowed_origins(request: Request) -> set[str]:
    """Tideflow's own address as the browser used it (Caddy passes the Host header through), plus
    TIDECOUNT_ALLOWED_ORIGINS, comma-separated, for setups that serve the page from elsewhere."""
    host = request.headers.get("host", "").lower()
    own = {f"{'https' if is_https(request) else request.url.scheme}://{host}"} if host else set()
    extra = {o.strip().rstrip("/").lower() for o in os.environ.get("TIDECOUNT_ALLOWED_ORIGINS", "").split(",") if o.strip()}
    return own | extra


def origin_problem(request: Request) -> str | None:
    """Why an API write must be refused as coming from another site, or None. SameSite=Lax already
    keeps the cookie off other sites' writes; this is the second layer. Browsers send Origin with
    every fetch and XMLHttpRequest write. A write with neither Origin nor Referer is refused only
    when it carries a session cookie: a tool with no cookie has no session to misuse."""
    if request.method not in UNSAFE or not request.url.path.startswith("/api/"):
        return None
    origin = request.headers.get("origin", "").strip().lower()
    if not origin:
        origin = _origin_of(request.headers.get("referer", ""))
    if not origin:
        has_cookie = SECURE_COOKIE in request.cookies or PLAIN_COOKIE in request.cookies
        return "This request didn't say which site sent it, so it was refused." if has_cookie else None
    if origin in allowed_origins(request):
        return None
    return "This request came from another site, so it was refused."


# --- sessions and the signed-in person ---------------------------------------------------------

@dataclass(frozen=True)
class User:
    id: int
    email: str
    name: str
    role: str
    session: str = ""        # this session's token hash
    reauth_at: float = 0.0   # when this session last confirmed the password

    @property
    def manager(self) -> bool:
        return self.role == "manager"

    def public(self) -> dict:
        return {"id": self.id, "email": self.email, "name": self.name, "role": self.role}


def start_session(con, user_id: int) -> str:
    """A new session for a person who just proved their password. Returns the token for the cookie.
    Signing in counts as confirming the password, so sensitive actions don't ask again at once."""
    now = time.time()
    con.execute("DELETE FROM sessions WHERE last_seen < ? OR created_at < ?", (now - IDLE_S, now - ABSOLUTE_S))
    token = secrets.token_urlsafe(32)
    con.execute("INSERT INTO sessions (token_hash, user_id, created_at, last_seen, reauth_at) VALUES (?, ?, ?, ?, ?)",
                (digest(token), user_id, now, now, now))
    return token


def end_sessions(con, user_id: int, keep: str = "") -> None:
    """Sign a person out everywhere, except the session `keep` (a token hash) when given."""
    con.execute("DELETE FROM sessions WHERE user_id = ? AND token_hash != ?", (user_id, keep))


def viewer(request: Request) -> User | None:
    """The signed-in person for this request, read from the database, or None for a guest."""
    token = request.cookies.get(cookie_name(request))
    if not token or len(token) > 200:
        return None
    th, now = digest(token), time.time()
    with db.session() as con:
        row = con.execute(
            "SELECT s.user_id, s.created_at, s.last_seen, s.reauth_at, u.email, u.name, u.role, u.active "
            "FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token_hash = ?", (th,),
        ).fetchone()
        if not row:
            return None
        if not row["active"] or now - row["last_seen"] > IDLE_S or now - row["created_at"] > ABSOLUTE_S:
            con.execute("DELETE FROM sessions WHERE token_hash = ?", (th,))
            return None
        if now - row["last_seen"] > TOUCH_S:
            con.execute("UPDATE sessions SET last_seen = ? WHERE token_hash = ?", (now, th))
    return User(row["user_id"], row["email"], row["name"], row["role"], th, row["reauth_at"])


def require_user(user: User | None = Depends(viewer)) -> User:
    if user is None:
        raise HTTPException(401, "Sign in to do this.")
    return user


def require_manager(user: User = Depends(require_user)) -> User:
    if not user.manager:
        raise HTTPException(403, "Only a manager can do this.")
    return user


def require_recent_manager(user: User = Depends(require_manager)) -> User:
    """Sensitive manager actions: the password must have been entered in the last few minutes.
    The shared demo manager has no password anyone knows, so there's nothing to confirm: it goes ahead."""
    if user.email in DEMO_EMAILS:
        return user
    if time.time() - user.reauth_at > REAUTH_S:
        raise HTTPException(403, "Confirm your password to do this.", headers={REAUTH_HEADER: "required"})
    return user


def level(user: User | None) -> str:
    """What a viewer may see of content with a review status: "guest", "user" or "manager"."""
    return "guest" if user is None else ("manager" if user.manager else "user")


# --- limits ------------------------------------------------------------------------------------

def too_many(wait: float | None) -> None:
    if wait is not None:
        minutes = max(1, int(wait // 60) + 1)
        raise HTTPException(429, f"Too many attempts. Try again in {minutes} minute{'s' if minutes != 1 else ''}.",
                            headers={"Retry-After": str(max(1, int(wait) + 1))})


# --- first manager -----------------------------------------------------------------------------

_setup_lock = threading.Lock()
_setup: dict = {"hash": "", "expires": 0.0}


def users_exist(con) -> bool:
    return con.execute("SELECT 1 FROM users LIMIT 1").fetchone() is not None


def ensure_setup_code(announce=print) -> None:
    """While there are no accounts, keep a one-time setup code and print it on the server's console.
    Only someone who can see that console (the start.bat window, `docker compose logs`) can create
    the first manager, so a visitor to a public site can't claim it first."""
    with db.session() as con:
        if users_exist(con):
            return
    with _setup_lock:
        if _setup["hash"] and time.time() < _setup["expires"]:
            return
        alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
        code = "-".join("".join(secrets.choice(alphabet) for _ in range(4)) for _ in range(4))
        _setup.update(hash=digest(code), expires=time.time() + SETUP_S)
    announce(
        "\n" + "=" * 64 + "\n"
        "  Tideflow has no accounts yet. To create the first manager,\n"
        f"  open /login and enter this setup code: {code}\n"
        "  It works once and expires in an hour (a restart prints a new one).\n"
        + "=" * 64 + "\n", flush=True,
    )


def take_setup_code(code: str) -> bool:
    """True, once, for the current setup code."""
    given = digest((code or "").strip().upper())
    with _setup_lock:
        ok = bool(_setup["hash"]) and time.time() < _setup["expires"] and hmac.compare_digest(given, _setup["hash"])
        if ok:
            _setup.update(hash="", expires=0.0)
        return ok


def reset_state() -> None:
    """Forget limits and the setup code. For tests."""
    for limiter in (login_by_ip, failures_by_email, sensitive_by_ip, register_by_ip):
        limiter.reset()
    with _setup_lock:
        _setup.update(hash="", expires=0.0)


# --- what routes declare -------------------------------------------------------------------------

SIGNED_IN = [Depends(require_user)]
MANAGER = [Depends(require_manager)]
RECENT_MANAGER = [Depends(require_recent_manager)]
