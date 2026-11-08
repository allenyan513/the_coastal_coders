"""Accounts from the command line, for a server without a browser handy or a locked-out manager.

    python -m tidecount.users create-manager you@example.org --name "Your Name"
    python -m tidecount.users reset-password you@example.org
    python -m tidecount.users list

In Docker: docker compose run --rm app .venv/bin/python -m tidecount.users create-manager you@example.org
Passwords are asked for, never taken on the command line, so they don't end up in shell history.
"""
import argparse
import getpass
import sys
import time

from . import auth, config, db


def _password() -> str:
    while True:
        first = getpass.getpass("Password: ")
        problem = auth.password_problem(first)
        if problem:
            print(problem)
            continue
        if getpass.getpass("Password again: ") != first:
            print("The two don't match.")
            continue
        return first


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tidecount.users")
    sub = parser.add_subparsers(dest="command", required=True)
    make = sub.add_parser("create-manager", help="Create a manager account")
    make.add_argument("email")
    make.add_argument("--name", default="")
    reset = sub.add_parser("reset-password", help="Set a new password and sign the person out everywhere")
    reset.add_argument("email")
    sub.add_parser("list", help="List accounts")
    args = parser.parse_args(argv)

    config.DATA.mkdir(parents=True, exist_ok=True)
    db.init()
    with db.session() as con:
        if args.command == "list":
            for r in con.execute("SELECT email, name, role, active FROM users ORDER BY email"):
                print(f"{r['email']:40} {r['role']:10} {'active' if r['active'] else 'off':7} {r['name']}")
            return 0
        try:
            email = auth.clean_email(args.email)
        except Exception:
            print("That isn't an email address.")
            return 1
        row = con.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
        if args.command == "create-manager":
            if row:
                print("There's already an account for that email.")
                return 1
            name = " ".join((args.name or email.split("@")[0]).split())[:100]
            con.execute("INSERT INTO users (email, name, role, password_hash, created_at) VALUES (?, ?, 'manager', ?, ?)",
                        (email, name, auth.hash_password(_password()), time.time()))
            print(f"Manager {email} created.")
            return 0
        if not row:
            print("No account for that email.")
            return 1
        con.execute("UPDATE users SET password_hash = ?, active = 1 WHERE id = ?", (auth.hash_password(_password()), row["id"]))
        auth.end_sessions(con, row["id"])
        print(f"New password set for {email}. Their other sessions have ended.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
