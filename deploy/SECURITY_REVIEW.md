# Adversarial security review — mortgage_dashboard backend

Date: 2026-09-18. Scope: FastAPI backend (`backend/`), its file-serving and
console/Plaid surfaces. Context: single-user, localhost-only app served by FastAPI
behind a local Caddy reverse proxy (`app.mortgage-dashboard` on :80 → 127.0.0.1:9001).
No public exposure by design; no per-request auth by design.

Threat model considered: (a) another local process or user on the same machine;
(b) a malicious web page in the user's browser issuing cross-origin/`fetch`
requests to `http://127.0.0.1:9001` (DNS-rebinding / drive-by localhost attacks);
(c) a future change that exposes the port beyond localhost.

---

## FINDINGS

### F1 — Path traversal in SPA catch-all → secret disclosure  [CRITICAL] [FIXED]
`main.py` `_serve_spa(full_path)` built `candidate = _DIST_DIR / full_path` and
served it if `candidate.is_file()`, with no containment check.

**Confirmed exploit** (raw HTTP, bypassing client URL normalization):
`GET /..%2F..%2F.env` returned **HTTP 200 with the live `.env`**, leaking
`client_id` and `production_secret`. Starlette normalizes single `../` and some
encodings, but double-encoded `..%2F..%2F` reached the handler as literal
`../../` and escaped `dist/`.

Impact: read any file the server process can read (Plaid production secret,
source, etc.) — full credential disclosure.

Fix: resolve the candidate and verify it is contained within `_DIST_DIR`
(`os.path.commonpath` / `Path.is_relative_to`) before serving; fall back to
index.html otherwise. See mitigation in `main.py`.

### F2 — Unauthenticated privileged endpoints  [MEDIUM, by-design; hardened]
`/console` (mints Plaid link tokens, reads balances, bulk-recategorizes, undo)
and all `/plaid/*` have no auth. Acceptable for a localhost single-user tool, BUT
combined with permissive CORS this widens the browser-based threat (see F3).
Mitigations applied: tighten CORS (F3); document that the port must never be
bound beyond 127.0.0.1 and must stay behind Caddy. No auth added (out of scope
for a single-user local tool; would be the next step if multi-user/exposed).

### F3 — CORS + host binding  [LOW; hardened]
CORS allowed only `localhost:5173/5174` (dev), which is fine. Confirmed the app
should only ever bind `127.0.0.1` (startup scripts do). Left CORS dev-only;
added an explicit note. A malicious page still cannot read cross-origin JSON
responses without a matching CORS origin, so F2's browser vector is limited to
unreadable "fire-and-forget" POSTs — the traversal (F1) was the real browser risk
and is now fixed.

### F4 — Error messages leak upstream (Plaid) detail  [LOW; hardened]
Several handlers did `HTTPException(detail=f"...: {e}")`, surfacing raw Plaid
exception text (which can include request IDs / internal messages) to the client.
Low risk locally, but poor hygiene. Mitigation: keep a generic client-facing
message and log the full error server-side (already logged via `logger.error`).

### F5 — Secrets at LocalMachine persistence  [INFO / accepted]
`credential_store` stores Plaid tokens and the Fernet key as Windows Credential
Manager Generic creds with `CRED_PERSIST_LOCAL_MACHINE`. Any process running as
an account able to read LocalMachine creds can retrieve them, and the Fernet key
lives alongside the data it decrypts (so the at-rest encryption protects against
file theft, not against a local process running as the user). Accepted for a
single-user desktop tool; documented so it is a conscious choice.

### F6 — console_history.log content  [INFO / accepted]
Raw console commands (may include merchant text, amounts) are appended to
`console_history.log`. It is gitignored and local. Accepted.

### NON-ISSUES (checked, no action)
- profiles_store `load/delete_profile`: gate on `profile_id in index` (server-
  generated uuid keys) BEFORE building any path → no traversal.
- No `eval`/`exec`/`os.system`/`subprocess`/`shell=True` anywhere in app code.
- Console parsing uses `shlex.split` + a static dispatch dict; rule "patterns"
  are plain lowercase substring (`in`) matches, not regex/`re` — no injection.
- Plaid `/exchange` stores the access token to Credential Manager and never
  returns it to the client; `/sandbox-link` is gated to the sandbox env.
- Fernet is authenticated encryption (tamper-evident) for the txn store.

---

## Operational recommendations (not code)
- Keep the app bound to `127.0.0.1` only; never `0.0.0.0`. Keep it behind Caddy.
- The working-tree `.env` holds live Plaid secrets. After the deploy script moves
  them into Credential Manager, scrub `.env` (or keep it, knowing F1 is fixed).
  Consider rotating the Plaid `production_secret` given F1 exposed it locally.
- Run `deploy/scan.ps1` (or the pre-commit hooks) before each commit.
