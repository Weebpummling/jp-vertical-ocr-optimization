"""Issue the id code a worker types to identify themselves.

The project's identity model (docs/decision-workstation-auth.md, decided 2 Aug
2026): each worker gets an id code, entering it is how they identify themselves,
and that code *is* their unique identifier. No passwords, no roles.

Codes are minted here rather than chosen. A code someone picks - `verifier1`,
their initials - is guessable, and if the workstation ever leaves the lead's
machine the code is the only thing standing in front of the transcription
database. `secrets.choice` over a 31-character alphabet, 12 characters, is ~59
bits: brute force stops being a consideration and nobody has to remember a
password.

    python scripts/issue_access_code.py "Alice Tanaka"          # new worker
    python scripts/issue_access_code.py --list                  # who exists
    python scripts/issue_access_code.py --rotate <user_id>      # code leaked

Writes are attributed like every other write. Pass --issuer <code> to record who
issued it; without one the insert lands with a NULL actor, which is correct only
for the very first user, when there is nobody to attribute it to yet.
"""

from __future__ import annotations

import argparse
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import db  # noqa: E402

# No 0/O, 1/I/L, 8/B: these codes get read aloud, written on paper, and typed by
# someone who is not looking at the screen. Ambiguity costs more than the two
# bits of entropy it saves.
ALPHABET = "ACDEFGHJKMNPQRTUVWXYZ2345679"
GROUPS, GROUP_LEN = 3, 4


def mint() -> str:
    """A fresh code: JP-K7QP-3M2X-9WTD."""
    body = "".join(secrets.choice(ALPHABET) for _ in range(GROUPS * GROUP_LEN))
    return "JP-" + "-".join(body[i:i + GROUP_LEN]
                            for i in range(0, len(body), GROUP_LEN))


def _unique_code(cur) -> str:
    """Mint until the code is unused. `login` is UNIQUE; collision is a retry."""
    for _ in range(10):
        code = mint()
        cur.execute("SELECT 1 FROM app_user WHERE login = ?", (code,))
        if not cur.fetchone():
            return code
    raise RuntimeError("could not mint an unused code in 10 attempts")


def _resolve_issuer(issuer_code: str | None) -> str | None:
    if not issuer_code:
        return None
    user = db.find_user(issuer_code.strip())
    if not user:
        raise SystemExit("--issuer is not a recognized id code")
    return str(user["user_id"])


def issue(display_name: str, issuer: str | None) -> str:
    with db.read_session() as cur:
        code = _unique_code(cur)
    sql = "INSERT INTO app_user (user_id, login, display_name) VALUES (?, ?, ?)"
    values = (db.new_id(), code, display_name)
    if issuer:
        with db.actor_session(issuer) as cur:
            cur.execute(sql, values)
            db.log_work(cur, issuer, "issue_code", detail={"for": display_name})
    else:
        # Bootstrap: there is nobody to attribute the first worker to.
        with db.session() as conn:
            conn.execute(sql, values)
    return code


def rotate(user_id: str, issuer: str | None) -> str:
    with db.read_session() as cur:
        cur.execute("SELECT display_name FROM app_user WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        if not row:
            raise SystemExit(f"no app_user with user_id {user_id}")
        code = _unique_code(cur)
    actor = issuer or user_id      # rotating your own code attributes to you
    with db.actor_session(actor) as cur:
        cur.execute("UPDATE app_user SET login = ? WHERE user_id = ?", (code, user_id))
        db.log_work(cur, actor, "rotate_code", detail={"user_id": user_id})
    return code


def listing() -> list[dict]:
    """Everyone, without their codes. Names and ids are not secrets; codes are."""
    with db.read_session() as cur:
        cur.execute("""
            SELECT u.user_id, COALESCE(u.display_name, '(unnamed)') AS display_name,
                   COUNT(o.obs_id) AS observations
              FROM app_user u
         LEFT JOIN observation o ON o.author_user_id = u.user_id
          GROUP BY u.user_id, u.display_name
          ORDER BY display_name
        """)
        return [dict(r) for r in cur.fetchall()]


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("display_name", nargs="?", help="the worker's name, for attribution displays")
    ap.add_argument("--list", action="store_true", help="list workers (never prints codes)")
    ap.add_argument("--rotate", metavar="USER_ID", help="replace an existing worker's code")
    ap.add_argument("--issuer", metavar="CODE", help="id code of whoever is issuing this")
    args = ap.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    if args.list:
        for row in listing():
            print(f"{row['user_id']}  {row['display_name']:<24} "
                  f"{row['observations']:>6} observations")
        return 0

    issuer = _resolve_issuer(args.issuer)

    if args.rotate:
        code = rotate(args.rotate, issuer)
        print(f"\n  new code: {code}\n\nThe old code stops working immediately.")
        return 0

    if not args.display_name:
        ap.error("give the worker's name, or --list / --rotate")

    if not issuer:
        print("note: no --issuer, so this insert is attributed to nobody. "
              "Correct for the first user only.", file=sys.stderr)

    code = issue(args.display_name, issuer)
    print(f"\n  {args.display_name}\n  id code: {code}\n")
    print("They type this into the workstation once; the browser remembers it.")
    print("It is stored as-is in app_user.login, so anyone with database access "
          "can read it -\nrotate it rather than reusing one that has been shared.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
