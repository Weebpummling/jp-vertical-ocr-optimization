# Decision needed — how the workstation authenticates annotators

**Status: open.** Raised 1 Aug 2026, when the write side landed.
**Blocks:** the multi-user phase. Not the lead transcribing alone on their own
machine today.

## What is in place

Writes are **attributed but not authenticated**. The API takes an `X-Annotator`
header, looks the login up in `app_user`, refuses with 401 if it is missing or
unknown, and sets `app.user_id` for the transaction so the audit triggers record
who did it. Every `roster_cell` and `observation` written so far carries a real
actor in `audit_log`.

What it does *not* do is verify that the caller is who the header says. Anyone
who can reach the port can claim any login.

## Why it was left there

`app_user` in the frozen schema is `(user_id, login, display_name, role)`. There
is **no credential column** — no password hash, no token, no external-identity
reference. Authenticating properly means migrating an audited table, and the
schema was frozen 31 Jul 2026 with the rule that changes from there are
deliberate migrations. Picking a scheme unilaterally and adding columns to
`app_user` is exactly the kind of decision that should not arrive as a side
effect of building a form.

The current deployment also makes it survivable: one workstation, on the lead's
machine, with Postgres bound to `127.0.0.1` and the API served locally. The
header is honest identification between two people who trust each other.

It stops being survivable the moment the decisions record's point 3 happens —
undergraduate annotators joining for the labour phase. At that point
"reviewer ≠ author" is a claim the system cannot actually enforce, and the
audit log records assertions rather than facts.

## The options

| # | Approach | Migration | Fits |
|---|---|---|---|
| 1 | Password on `app_user` (argon2/bcrypt hash column) + session cookie | Add `password_hash`, `password_set_at` | Self-contained; no external dependency; the project owns the whole surface |
| 2 | Institutional SSO (university IdP, OIDC) | Add `external_subject` unique column | Undergraduates already have accounts; no password handling at all; depends on the institution |
| 3 | Per-user API tokens | Add a `user_token` table | Good for scripts and the Kanpō miner; poor as the only human login |
| 4 | Leave header identification, bind to localhost, never expose | None | Only tenable while the lead is the sole user |

Worth deciding together with two related questions:

- **Does the workstation ever leave `localhost`?** Decisions record point 2 says
  hosting is the lead's machine, with a small hosted VM acceptable later. Option
  4 dies the moment that VM exists.
- **What does `role` gate?** The column already distinguishes
  annotator/reviewer/adjudicator/admin, but nothing enforces it yet. Whichever
  option is chosen should land with role checks on the write endpoints, or the
  reviewer ≠ author rule stays advisory.

## Recommendation

**Option 1 now, option 2 when the undergraduates arrive.** A password column and
a signed session cookie is a small, well-understood migration that makes the
audit log mean what it says, and it does not block on anyone outside the
project. SSO is the better end state for a cohort of students, but it needs the
institution's cooperation and should not gate the labour phase starting.

Until this is decided, keep the API on `127.0.0.1` and treat `audit_log.actor`
as "the login the client claimed", not "the person who did it".
