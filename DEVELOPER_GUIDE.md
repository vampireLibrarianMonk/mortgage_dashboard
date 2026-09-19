# Developer Guide

Everything needed to set up, run, test, secure, and deploy the Mortgage Dashboard.
If you just want to *use* the app, see the [User Guide](USER_GUIDE.md) instead.

> **Subsystem guides:**
> - Order-details itemization (transaction splitting) + atomicity gaps:
>   [DEVELOPER_GUIDE_ORDERS.md](DEVELOPER_GUIDE_ORDERS.md).
> - Email receipt-ingest effort (Gmail/Proton), paused:
>   [DEVELOPER_GUIDE_MAILBOX.md](DEVELOPER_GUIDE_MAILBOX.md).

---

## Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.10, FastAPI + Uvicorn, Pydantic |
| Frontend | React 19 + TypeScript, Vite, Recharts |
| Encryption | `cryptography` (Fernet), Windows Credential Manager (native ctypes) |
| Bank data | Plaid (`plaid-python`), read-only Transactions + Balances |
| Tests | pytest |
| Lint / scan | ruff, bandit, pip-audit, detect-secrets, ESLint |
| Local hosting | Caddy reverse proxy + Windows Task Scheduler |

---

## Repository layout

```
mortgage_dashboard/
├── backend/                    # FastAPI server (Python)
│   ├── main.py                 # App wiring: routers, CORS, SPA static serving, /calculate, /profiles, /healthz
│   ├── models.py               # Pydantic request/response schemas
│   ├── calculations.py         # Mortgage math engine (amortization, totals, payoff)
│   ├── profiles_store.py       # Save/load scenarios as JSON, keyed by address
│   ├── txn_store.py            # Encrypted transaction + merchant-rule store; the categorization engine
│   ├── console_routes.py       # POST /console command processor (the console page's backend)
│   ├── actuals.py              # Budget-vs-actual aggregation (writes plaid_actuals.json)
│   ├── plaid_routes.py         # Plaid REST endpoints (connect/exchange/sync/balances/actuals)
│   ├── plaid_client.py         # Plaid client factory (reads creds from env)
│   ├── credential_store.py     # Windows Credential Manager access (Plaid tokens + Fernet key)
│   ├── requirements.txt        # Runtime dependencies
│   ├── requirements-dev.txt    # Dev/scan tooling (bandit, ruff, pip-audit, detect-secrets, pytest)
│   ├── pyproject.toml          # ruff / bandit / pytest config
│   └── tests/                  # pytest suite (calculations, txn_store, console, security)
├── frontend/                   # React + Vite SPA (TypeScript)
│   └── src/
│       ├── App.tsx             # Dashboard + Console page toggle
│       ├── api.ts              # Backend calls (calculate, profiles, plaidActuals, runConsole)
│       ├── components/
│       │   ├── Console.tsx     # In-browser terminal (categorization console)
│       │   ├── ProfileManager.tsx
│       │   ├── inputs/         # Left-panel form sections
│       │   └── results/        # Right-panel results + amortization chart + PDF report
│       └── hooks/useCalculation.ts
├── deploy/                     # Local always-on hosting (Caddy + Task Scheduler)
│   ├── scan.ps1                # Runs all security/quality scans
│   ├── SECURITY_REVIEW.md      # Adversarial security review + findings
│   └── ...                     # apps.json, Caddyfile, PowerShell setup scripts
├── Deployment.md               # Abstract, reusable local app-cluster blueprint
├── USER_GUIDE.md               # For people using the app
└── DEVELOPER_GUIDE.md          # This file
```

### Architecture at a glance

All math and categorization happen on the backend, so there is one source of
truth; the frontend renders results. In production, FastAPI serves the built
frontend and the API on a single port (same-origin behind Caddy). The
categorization data lives in an encrypted local store; bank credentials live in
Windows Credential Manager, never in files.

```
Browser (React SPA) ──JSON──► FastAPI
   Dashboard  ── /calculate, /profiles ──► calculations.py, profiles_store.py
   Console    ── /console ──────────────► console_routes.py ──► txn_store.py (encrypted)
   BudgetVsActual ── /plaid/actuals ────► actuals.py (reads plaid_actuals.json)
                                          plaid_routes.py ──► Plaid API (bank sync)
                                          credential_store.py ──► Windows Credential Manager
```

---

## Local development setup

Prerequisites: **Python 3.10+**, **Node.js 18+** (with npm).

### Backend

```powershell
cd backend
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install -r requirements-dev.txt   # lint/scan/test tooling (optional but recommended)
```

Run the dev server (auto-reloads on edit):

```powershell
uvicorn main:app --reload --port 9001
```

Plaid is optional for local dev. Without `PLAID_CLIENT_ID` / `PLAID_SECRET` set,
the calculator and console still work; only the bank `sync`/`plaid` console
commands report "not configured". To enable Plaid locally, set the env vars from
Credential Manager the same way the deploy script does (see the startup scripts in
`deploy/`), or export them manually in your shell for the session.

### Frontend

In a second terminal:

```powershell
cd frontend
npm install
npm run dev          # dev server at http://localhost:5173
```

The Vite dev server proxies API calls to the backend. In production the backend
serves the built SPA, so the frontend always calls the API with relative paths.

---

## Tests

The suite covers the math engine, the encrypted transaction store + categorization
engine, the console command processor, and a security regression test for the SPA
static-file path-traversal fix.

```powershell
cd backend
.\venv\Scripts\python.exe -m pytest -q
```

Test isolation is important: `tests/conftest.py` redirects the transaction store to
a temporary directory and stubs the Fernet key, so tests **never** touch the real
encrypted data or the Windows Credential Manager.

---

## Linting & security scans

All scanners run from one script (needs `requirements-dev.txt` installed and, for
the frontend checks, `npm install`):

```powershell
powershell -ExecutionPolicy Bypass -File deploy\scan.ps1
# backend only:
powershell -ExecutionPolicy Bypass -File deploy\scan.ps1 -SkipFrontend
```

It runs: **detect-secrets** (against `.secrets.baseline`), **ruff** (lint +
security rules), **bandit** (Python SAST), **pip-audit** (dependency CVEs),
**npm audit**, and **ESLint**. It prints a per-tool PASS/FINDINGS summary and exits
non-zero on any finding.

### Pre-commit hooks (optional)

To run the same checks automatically on every commit:

```powershell
.\backend\venv\Scripts\pip install pre-commit
.\backend\venv\Scripts\pre-commit install
```

Config is in `.pre-commit-config.yaml`. Run on demand across all files with
`pre-commit run --all-files`.

---

## Security

See **[deploy/SECURITY_REVIEW.md](deploy/SECURITY_REVIEW.md)** for the full
adversarial review and threat model. Key points for developers:

- **Bind to `127.0.0.1` only.** The app is a single-user, localhost tool behind
  Caddy. Never bind `0.0.0.0` or expose the port publicly. There is no per-request
  auth by design.
- **Static file serving is traversal-safe.** `main.py`'s SPA catch-all resolves
  each requested path and confirms it stays inside `frontend/dist` before serving,
  so requests like `/..%2F..%2F.env` cannot read files outside the build. There is
  a regression test for this in `tests/test_main_security.py` — keep it green.
- **Secrets never touch files or the command line.** Plaid API keys, per-bank
  access tokens, and the transaction-store Fernet key all live in Windows
  Credential Manager. The `.env` at the repo root is gitignored; it is only a
  staging area for `store-plaid-credentials.ps1` to read from.

---

## Rotating the Plaid production secret

Do this if the secret may have been exposed, or on a routine schedule. It is a
two-part process: rotate at Plaid first, then update the local machine.

1. **Regenerate at Plaid.** Log into the [Plaid Dashboard](https://dashboard.plaid.com/)
   → Team Settings → Keys → rotate/regenerate the **Production** secret. Copy the
   new value. Rotating invalidates the old secret (that is the point — a leaked
   secret stops working).

2. **Update the local machine.** Edit the repo-root `.env` and replace the
   `production_secret=...` line with the new value (edit in your editor, not on the
   command line, so it never enters shell history). Then, in an **admin PowerShell**
   (the credential is stored at LocalMachine scope, which requires elevation):

   ```powershell
   powershell -ExecutionPolicy Bypass -File deploy\store-plaid-credentials.ps1
   ```

   This reads the new secret from `.env` and writes it to Windows Credential Manager
   under `plaid_production_secret` without ever printing the value. It prints only
   the target names it stored.

3. **Restart so the app picks up the new secret** (admin PowerShell):

   ```powershell
   Get-NetTCPConnection -LocalPort 9001 -State Listen | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }
   Start-Sleep -Seconds 2
   Start-ScheduledTask -TaskName "MortgageDashboard-Apps"
   ```

4. **(Optional) Scrub `.env`.** Once the secret is in Credential Manager the running
   app no longer reads `.env` (the startup script pulls from Credential Manager).
   You may blank out the `production_secret` value in `.env` to minimize plaintext
   copies on disk. `.env` is gitignored regardless.

The same procedure applies to the other keys — `store-plaid-credentials.ps1` maps
`.env` keys `client_id`, `sandbox_secret`, `production_client_id`,
`production_secret` to Credential Manager targets `plaid_client_id`,
`plaid_sandbox_secret`, `plaid_production_client_id`, `plaid_production_secret`.

---

## Deployment (always-on local hosting)

The app auto-starts on boot at `http://app.mortgage-dashboard/` via a Caddy reverse
proxy and Windows Task Scheduler. Two references:

- **[deploy/README.md](deploy/README.md)** — the concrete, mortgage-specific setup,
  everyday use (rebuild/restart), and troubleshooting.
- **[Deployment.md](Deployment.md)** — the abstract, reusable blueprint for running
  a cluster of local `app.*` services with the same pattern.

Quick reference for the common operations:

```powershell
# Rebuild the frontend after UI changes, then restart to serve it
powershell -ExecutionPolicy Bypass -File deploy\build.ps1
Restart-ScheduledTask -TaskName MortgageDashboard-Apps   # admin

# Restart the app (also needed to pick up backend code or dependency changes)
Get-NetTCPConnection -LocalPort 9001 -State Listen | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }
Start-ScheduledTask -TaskName "MortgageDashboard-Apps"   # admin
```

---

## API endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/calculate` | Send all inputs, get calculated results + amortization schedule |
| `GET` | `/profiles` | List saved profiles |
| `POST` | `/profiles` | Save a profile (by address) |
| `GET` | `/profiles/{id}` | Load a profile |
| `DELETE` | `/profiles/{id}` | Delete a profile |
| `POST` | `/console/` | Run a console command; returns output lines |
| `GET` | `/plaid/actuals` | Aggregates-only budget-vs-actual data for the dashboard |
| `GET` | `/plaid/status`, `/plaid/items`, `/plaid/balances/{slug}` | Plaid diagnostics/read |
| `POST` | `/plaid/link-token`, `/plaid/exchange`, `/plaid/sandbox-link`, `/plaid/sync` | Bank connect + sync |
| `GET` | `/healthz` | Liveness probe used by the proxy/startup |

Interactive API docs are available at `/docs` when the backend is running.

---

## Future work

Deferred items are tracked in `plaid_pipeline/APP_TODO.md` (ATM section GUI, check
images, annual-budget handling for one-off categories, Amazon/PayPal transaction
import) and `plaid_pipeline/PAYPAL_REQUIREMENTS.md`.
