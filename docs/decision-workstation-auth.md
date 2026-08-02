# Decision — how the workstation identifies annotators

**Status: decided by the lead, 2 Aug 2026.** Raised 1 Aug when the write side
landed.

## The decision

**Each worker is issued an id code. Entering it is how they identify themselves,
and that code is their unique identifier on the project.** No passwords, no SSO,
no session accounts, and **no roles** — `app_user.role` gates nothing and will
not be enforced.

The requirement this satisfies is stated plainly: *make sure their work is
recorded to them*. That is attribution, not access control. This is a two-person
project plus a small number of verifiers, and login is not a problem the project
is trying to solve.

The workstation may also leave this machine — whether it does depends on how
many human hours the remaining work is estimated to need, which is not settled
yet. The design therefore may not assume `localhost`.

## What that means concretely

- The id code goes in `app_user.login`. It **is** the identifier, so no schema
  change is needed: the column is already `UNIQUE NOT NULL`, and the API already
  resolves the `X-Annotator` header against it. The schema stays frozen.
- `display_name` carries the human name. `role` is set to `annotator` for
  everyone because the column is `NOT NULL` with a `CHECK`; it means nothing and
  no code reads it.
- Codes are **minted, not chosen** — `scripts/issue_access_code.py` generates
  ~59 bits from `secrets` in a no-ambiguous-characters alphabet
  (`JP-K7QP-3M2X-9WTD`). A guessable code like `verifier1` would be the whole
  security surface if the workstation is ever exposed; a random one makes online
  guessing irrelevant without asking anyone to remember a password.
- The code is a bearer secret, so it is kept out of responses and logs: `whoami`
  returns the display name, the observations listing attributes work to the
  display name rather than the code, and a bad code is refused without echoing
  what was sent.
- The browser stores the code in `localStorage` and sends it on every write. The
  worker types it once per machine.

## What this deliberately does not do

Anyone holding a worker's code can write as that worker. There is no
confirmation of who is at the keyboard, and a shared or leaked code is
indistinguishable from the real one. For attribution among people who are all on
the same project, that is the intended trade — the failure mode is a
mis-attributed row, not an outsider getting in, provided the codes stay random
and the deployment is not open to the world.

**If the workstation leaves this machine**, two things become load-bearing and
are conditions of that move, not suggestions:

1. **Serve it over TLS** (or a tunnel — Tailscale, an SSH forward, a reverse
   proxy with a certificate). A bearer code sent over plain HTTP on a shared
   network is readable in transit by anyone on the path.
2. **Do not put it on a public address without at least a network-level gate.**
   The codes make guessing impractical, but nothing else stands between the
   internet and the transcription database.

If those ever become inconvenient, the upgrade — not needed now — is to store a
hash of the code instead of the code itself (`access_code_hash`), keep `login`
as a plain handle, and rotate by re-issuing. That is a small migration and can
happen later without changing how a worker signs in: they still just type their
code.

## Consequences for the audit log

`audit_log.actor` now means "the holder of this id code", which is what the
project needs it to mean. The earlier caveat — read it as "the login the client
claimed" — is retired for the deployments described above.

`reviewer ≠ author` cannot be enforced by the system, because roles are not
enforced. That was accepted with this decision: verification is arranged between
people, not by the software.
