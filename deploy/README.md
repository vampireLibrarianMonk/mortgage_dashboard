# Local boot-time hosting (`deploy/`)

Serve the mortgage dashboard (and future apps) at friendly local URLs like
`http://app.mortgage-dashboard/`, started automatically on every Windows boot.

## How it works

```
Browser  ──►  http://app.mortgage-dashboard/          (no port needed)
                     │
   hosts file maps app.* ──► 127.0.0.1
                     │
              Caddy on :80  ── routes by hostname ──►  127.0.0.1:9001
                                                          │
                                                   FastAPI (uvicorn)
                                                   serves the built SPA + API
```

- **`apps.json`** is the single source of truth: each app has a `name`, `hostname`
  (`app.<name>`), a high `port` (9000s band), a `working_dir`, and a `start_command`.
- **Caddy** listens on port 80 and reverse-proxies each hostname to that app's port,
  so you get a clean URL with no port number while each app stays on its own port.
- **FastAPI** serves the compiled frontend (`frontend/dist`) and the API on one port,
  so the whole app is same-origin behind the proxy.
- **Task Scheduler** starts the apps and Caddy at boot, before login, running as SYSTEM
  (which is what lets Caddy bind port 80).

Ports are reserved in the **9000s** band to avoid clashing with common dev servers
(3000/5173/8000/8080) and the Windows ephemeral range (49152+). The mortgage app is
`9001`; give each new app the next free port (`9002`, `9003`, …).

## Prerequisites

- Python venv already set up in `backend\venv` (the app's normal setup).
- **Caddy**: either drop `caddy.exe` into this `deploy\` folder, or install it on PATH:
  ```powershell
  winget install CaddyServer.Caddy
  ```

## One-time setup

Run these from the repo root. Steps marked **(admin)** need an elevated PowerShell
(right-click PowerShell → Run as administrator).

```powershell
# 1. Build the frontend into frontend/dist (FastAPI serves this)
powershell -ExecutionPolicy Bypass -File deploy\build.ps1

# 2. Generate the Caddyfile from apps.json
powershell -ExecutionPolicy Bypass -File deploy\generate-caddyfile.ps1

# 3. (admin) Add app.* -> 127.0.0.1 entries to the Windows hosts file
powershell -ExecutionPolicy Bypass -File deploy\update-hosts.ps1

# 4. (admin) Register the boot tasks (apps + proxy, run at startup as SYSTEM)
powershell -ExecutionPolicy Bypass -File deploy\register-startup.ps1
```

Then either reboot, or start now without rebooting (**admin**):

```powershell
Start-ScheduledTask -TaskName MortgageDashboard-Apps
Start-ScheduledTask -TaskName MortgageDashboard-Proxy
```

Open **http://app.mortgage-dashboard/**.

## Everyday use

- **After changing the frontend**, rebuild so the served files update:
  ```powershell
  powershell -ExecutionPolicy Bypass -File deploy\build.ps1
  ```
  The app auto-restarts on reboot; to pick up changes now, restart the app task
  (admin): `Restart-ScheduledTask -TaskName MortgageDashboard-Apps`.
- **Backend code changes** are picked up on the next app restart / reboot.

## Adding another app

1. Add an entry to `apps.json` with the next free port, e.g.:
   ```json
   { "name": "notes", "hostname": "app.notes", "port": 9002,
     "working_dir": "..\\notes\\backend",
     "start_command": "venv\\Scripts\\uvicorn.exe main:app --host 127.0.0.1 --port 9002",
     "health_path": "/healthz" }
   ```
   (`working_dir` is resolved relative to this repo root; use a relative path to
   another repo if the app lives elsewhere.)
2. Regenerate + re-register:
   ```powershell
   powershell -ExecutionPolicy Bypass -File deploy\generate-caddyfile.ps1
   powershell -ExecutionPolicy Bypass -File deploy\update-hosts.ps1        # admin
   powershell -ExecutionPolicy Bypass -File deploy\register-startup.ps1    # admin
   ```

## Teardown

```powershell
powershell -ExecutionPolicy Bypass -File deploy\register-startup.ps1 -Remove   # admin
powershell -ExecutionPolicy Bypass -File deploy\update-hosts.ps1 -Remove       # admin
```

## Troubleshooting

- **Port 80 already in use**: something else (IIS, Skype, another proxy) holds it.
  Find it with `Get-NetTCPConnection -LocalPort 80`. Either stop that service or
  change `proxy.http_port` in `apps.json` (you'll then use `http://app.<name>:<port>/`).
- **`app.mortgage-dashboard` doesn't resolve**: the hosts step didn't run elevated.
  Re-run `deploy\update-hosts.ps1` as admin; check the managed block exists in
  `C:\Windows\System32\drivers\etc\hosts`.
- **App unhealthy at boot**: check Task Scheduler history for `MortgageDashboard-Apps`,
  and confirm `backend\venv` exists. Test the launcher manually:
  `powershell -ExecutionPolicy Bypass -File deploy\start-apps.ps1`.

## Files

| File | Purpose |
|------|---------|
| `apps.json` | Registry of apps (name, hostname, port, start command). Source of truth. |
| `Caddyfile` | Generated proxy config. Do not edit by hand. |
| `generate-caddyfile.ps1` | Regenerates `Caddyfile` from `apps.json`. |
| `update-hosts.ps1` | (admin) Adds/removes `app.*` hosts entries. `-Remove` to undo. |
| `build.ps1` | Builds the frontend into `frontend/dist`. |
| `start-apps.ps1` | Launches each app on its port; polls health. |
| `start-proxy.ps1` | Runs Caddy with the generated `Caddyfile`. |
| `register-startup.ps1` | (admin) Registers/removes the boot tasks. `-Remove` to undo. |

## Plaid bank sync (read-only)

The app pulls transactions and balances from linked banks via Plaid, read-only.
All bank interaction is driven from the **Console page** in the app (there is no
Plaid GUI panel) — see the [User Guide](../USER_GUIDE.md) for the `sync` and
`plaid` console commands.

### How credentials are stored

- **Plaid API keys** live in Windows Credential Manager, never in files or printed.
  `start-apps.ps1` reads them at startup and passes them to the backend as
  `PLAID_CLIENT_ID` / `PLAID_SECRET` env vars. Credential targets:
  `plaid_client_id`, `plaid_sandbox_secret`, `plaid_production_client_id`,
  `plaid_production_secret`.
  - To (re)store them from a repo-root `.env`, run as the account the app runs as
    (LocalMachine scope needs an **admin** shell):
    `powershell -ExecutionPolicy Bypass -File deploy\store-plaid-credentials.ps1`
- **Per-bank access tokens and sync cursors** are created when a bank is linked and
  stored as `plaid_item_<slug>_access_token` / `plaid_item_<slug>_cursor`, with a
  JSON index of connected banks in `plaid_items`. These never appear in any file.

### Environment (sandbox vs. production)

Set `PLAID_ENV` (`sandbox` or `production`) in the startup environment. Sandbox
connects only to Plaid's fake test banks; production connects to real accounts and
requires production keys plus Plaid app approval. The client is environment-agnostic
— switching is a matter of the secret and `PLAID_ENV`.

### Rotating the production secret

If the production secret may have been exposed, or on a routine schedule, rotate it.
The full procedure (regenerate at Plaid → update `.env` → run
`store-plaid-credentials.ps1` as admin → restart) is in the
[Developer Guide](../DEVELOPER_GUIDE.md#rotating-the-plaid-production-secret).

### API version

The Plaid client is pinned to API version **2020-09-14** (the account default) via
`plaid_client.py`, so responses stay stable regardless of account-level changes.
