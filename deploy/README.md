# Local boot-time hosting (`deploy/`)

Serve the mortgage dashboard (and future apps) at friendly local URLs like
`http://app.mortgage-dashboard/`, started automatically (the proxy at boot, the app
at your logon — see "How it works" for why they differ).

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
- **Task Scheduler** starts things automatically, but the app and the proxy run in
  **different accounts on purpose**:
  - **App (uvicorn on 9001)** runs **as your user, at logon**. It must, because the
    Plaid credentials *and* each linked bank's access token live in **your user's**
    Windows Credential Manager vault. SYSTEM has a *separate* vault without them, so a
    SYSTEM-run app silently falls back to Plaid **sandbox** ("no banks connected").
  - **Proxy (Caddy on :80)** runs **as SYSTEM, at startup**, which is what lets it bind
    port 80 before any login.

> **Boot vs. resume.** The proxy triggers *At startup* and the app *At your logon*, so a
> full **restart** (followed by signing in) brings everything back automatically.
> **Resume from sleep** is a different event that neither trigger re-fires on — but that
> is normally fine because the processes keep running through sleep. You only need to
> re-launch after a resume if something killed them (see the "site is down"
> troubleshooting entry below).

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

# 4. (admin) Register the tasks. The app registers to run AS YOU at logon (so it
#    reads your Plaid vault); the proxy runs as SYSTEM at startup (to bind :80).
#    Run this elevated, but it auto-detects your user for the app task.
#    Add -WithHealthCheck to also self-heal: a task (also run as you) that, at
#    logon AND every 5 minutes, checks the app and relaunches it if it is down.
powershell -ExecutionPolicy Bypass -File deploy\register-startup.ps1 -WithHealthCheck
```

> The app task runs as the user who invoked the register script (auto-detected).
> If you register from an admin shell running under a *different* account than the
> one that holds the Plaid credentials, pass `-AppUser "DOMAIN\that_user"`.

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
  The app restarts at your next logon; to pick up changes now, restart the app task:
  `Stop-ScheduledTask -TaskName MortgageDashboard-Apps; Start-ScheduledTask -TaskName
  MortgageDashboard-Apps` (Windows PowerShell 5.x has no `Restart-ScheduledTask`).
- **Backend code changes** are picked up on the next app restart / logon.

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
- **`http://app.mortgage-dashboard/` is down / nothing is listening**: first check
  whether the tasks are registered —
  `Get-ScheduledTask -TaskName MortgageDashboard-*`. **Run this check from an
  elevated (Administrator) prompt** — the SYSTEM proxy task may not be visible to a
  standard session (the app/health-check run as your user and usually are), so an
  empty result in a normal shell is not proof they're
  missing; confirm elevated before concluding they need to be registered.
  - **No tasks returned (confirmed in an elevated shell)** → the one-time setup
    (step 4) was never run, so nothing starts the app on boot. Run it once,
    elevated: `deploy\register-startup.ps1`, then `Start-ScheduledTask -TaskName
    MortgageDashboard-Apps` and `-Proxy`. This is the durable fix — it survives
    every restart.
  - **Tasks exist but nothing is listening** (`Get-NetTCPConnection -LocalPort 80,9001
    -State Listen` is empty) → start them: `Start-ScheduledTask -TaskName
    MortgageDashboard-Apps` / `-Proxy` (admin), or just reboot.
  - **Stopgap (no admin handy):** `deploy\start-apps.ps1` launches the backend on
    9001 without elevation; Caddy on :80 usually needs an elevated shell. A stopgap
    launch is session-scoped and will NOT survive a restart — register the tasks for
    a permanent fix.
  - **Self-heal:** register with `-WithHealthCheck` so a scheduled task (run **as
    you**, the app user) executes `health-check.ps1 -AppsOnly` at logon and every
    5 minutes — it relaunches the app if it is down, so a mid-session crash recovers
    on its own. To check or force a heal now: `Start-ScheduledTask -TaskName
    MortgageDashboard-HealthCheck`, or run `deploy\health-check.ps1` directly.
    Recent actions are in `deploy\logs\health-check.log`.
- **Banks page shows "sandbox / No banks connected" (but you linked real banks):**
  the app is running in the **wrong account**. Plaid creds + each bank token live in
  the vault of the user who linked them; if the app runs as a different account
  (classically **SYSTEM** from an old boot task), it can't see them and falls back to
  sandbox. Confirm with the console `plaid status` (`environment:` line). Fix: make
  the app run as the user that holds the creds — re-register elevated with
  `deploy\register-startup.ps1` (auto-uses your account for the app task), then
  `Stop-ScheduledTask`/`Start-ScheduledTask -TaskName MortgageDashboard-Apps`. If a
  stray app process is holding :9001, kill it first (`Get-NetTCPConnection -LocalPort
  9001 -State Listen`), then start the task. Do **not** leave a SYSTEM-run
  health-check registered alongside a user-run app — it will relaunch a sandbox
  instance and fight the real one (the current `register-startup.ps1` registers the
  health check as the user to avoid this).

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
| `health-check.ps1` | Checks the app (and, without `-AppsOnly`, the proxy) and relaunches whatever is down (idempotent; safe on a schedule). **Run as the app user.** Logs to `deploy\logs\health-check.log`. |
| `register-startup.ps1` | (admin) Registers/removes the tasks: **app as the user at logon**, **proxy as SYSTEM at startup**. `-WithHealthCheck` adds a self-heal task (as the user, at logon + every 5 min). `-AppUser` overrides the app account. `-Remove` undoes all. |

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
  - To (re)store them from a repo-root `.env`, run **as the same account the app
    runs as** (see the callout below):
    `powershell -ExecutionPolicy Bypass -File deploy\store-plaid-credentials.ps1`
    (The script accepts either `client_id` or `production_client_id` in `.env`.)
- **Per-bank access tokens and sync cursors** are created when a bank is linked and
  stored as `plaid_item_<slug>_access_token` / `plaid_item_<slug>_cursor`, with a
  JSON index of connected banks in `plaid_items`. These never appear in any file.

> **⚠ Same-account rule (this bites hard).** Windows Credential Manager vaults are
> **per-account**. Every Plaid secret — API keys *and* each bank's access token — is
> stored in the vault of whoever created them (normally you, linking banks in the
> app). The app process therefore **must run as that same account**, which is why the
> app task runs as your user, not SYSTEM. A SYSTEM (or other-account) app can't read
> your vault and silently falls back to **sandbox** ("no banks connected"). If you
> ever want the app under SYSTEM, you must copy the API creds *and every*
> `plaid_item_<slug>_access_token` / `_cursor` into SYSTEM's vault too.

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
