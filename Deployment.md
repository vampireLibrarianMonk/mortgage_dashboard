# Deployment Blueprint: a local `app.*` cluster on Windows

An abstract, reusable pattern for running any number of local apps that each boot
automatically and are reachable at a friendly URL like `http://app.<name>/` — no
port numbers, no manually starting servers.

This document is **app-agnostic**. The mortgage dashboard is one concrete instance;
follow this to bring up a cluster of your own apps the same way.

---

## The model

```
Browser ──► http://app.<name>/            (clean URL, no port)
                  │
   Windows hosts file:  app.* ──► 127.0.0.1
                  │
        Caddy reverse proxy on :80
        routes by hostname (Host header):
            app.mortgage-dashboard ──► 127.0.0.1:9001
            app.notes              ──► 127.0.0.1:9002
            app.wiki               ──► 127.0.0.1:9003
                  │                          │
                  └── one high port per app ─┘
                              │
                     each app serves itself
                     (API + built UI, or static, or anything HTTP)
```

Three moving parts, each independent:

1. **A registry** — the single source of truth listing every app: its name,
   hostname, port, working directory, and start command.
2. **A reverse proxy (Caddy)** on port 80 that maps each `app.<name>` hostname to
   that app's loopback port. This is what lets many apps share port 80 while each
   keeps its own port.
3. **A boot mechanism (Task Scheduler)** that starts the apps and the proxy at
   startup, before login, running as SYSTEM (required so Caddy can bind :80).

### Why a reverse proxy

Browsers default `http://` to port 80. If each app has its own high port, you'd
normally type `app.notes:9002`. The proxy listens on 80 and dispatches by hostname,
so you get **both** friendly no-port URLs **and** one dedicated port per app.

---

## Design conventions

Adopt these once and every app in the cluster follows the same rules.

| Concern | Convention |
|---------|-----------|
| Hostname | `app.<name>` (lowercase, dashes). Mapped to `127.0.0.1` in the hosts file. |
| Port band | Reserve **9000–9999** for apps. Common dev ports (3000/5173/8000/8080) and the Windows ephemeral range (49152+) are avoided. Assign sequentially: 9001, 9002, … |
| Bind address | Each app binds **127.0.0.1** (loopback only). Only the proxy is public-facing (and only on the local machine). |
| Single origin per app | Each app serves its own UI **and** API on its one port, so it's same-origin behind the proxy (no CORS, no second port). |
| Health endpoint | Each app exposes `GET /healthz` returning 200, so startup can be verified. |
| Proxy scheme | Use `http://` in the Caddyfile so Caddy does **not** attempt automatic HTTPS (local `.<tld>` names can't get real certificates). |

---

## Two ways to run a cluster

### A. Central cluster (recommended for many apps)

One dedicated location owns the registry, the proxy, and the boot tasks. Every app
is just an entry in the registry. Best when you have several apps.

```
C:\Users\<you>\local-cluster\
├── apps.json              # every app in the cluster
├── Caddyfile              # generated from apps.json
├── caddy.exe              # the proxy binary (self-contained)
├── generate-caddyfile.ps1
├── update-hosts.ps1       # (admin) writes all app.* hosts entries
├── start-apps.ps1         # launches every app on its port
├── start-proxy.ps1        # runs Caddy
└── register-startup.ps1   # (admin) one Apps task + one Proxy task at boot
```

Each app repo stays independent; the registry points at each app's working
directory and start command (absolute or relative paths are both fine).

### B. Per-repo (what this repo does)

The scripts live inside a single app repo under `deploy/`. Good for one app, or as
the template you copy into the central cluster. To grow into a cluster, either move
the `deploy/` folder out to a central location (option A) or add more entries to
this repo's `apps.json` pointing at sibling repos.

Either way the scripts and file formats below are identical.

---

## The registry: `apps.json`

The contract every script reads. One entry per app.

```json
{
  "proxy": { "http_port": 80 },
  "apps": [
    {
      "name": "mortgage-dashboard",
      "hostname": "app.mortgage-dashboard",
      "port": 9001,
      "working_dir": "backend",
      "start_command": "venv\\Scripts\\uvicorn.exe main:app --host 127.0.0.1 --port 9001",
      "health_path": "/healthz"
    },
    {
      "name": "notes",
      "hostname": "app.notes",
      "port": 9002,
      "working_dir": "..\\notes",
      "start_command": "node server.js",
      "health_path": "/healthz"
    }
  ]
}
```

Field meanings:

- **name** — short identifier; also used to derive task/log names.
- **hostname** — the friendly URL host (`app.<name>`).
- **port** — the app's dedicated high port (9000s). Must be unique in the cluster.
- **working_dir** — where `start_command` runs (relative to the registry file, or absolute).
- **start_command** — how to launch the app on its port, bound to `127.0.0.1`.
- **health_path** — a path that returns 200 when the app is ready (optional but recommended).

**Any stack works.** The start command can be uvicorn, `node server.js`, a Go
binary, `dotnet run`, a static file server — anything that listens on the port.

---

## Making an app "cluster-ready"

For each app you add:

1. **Serve UI + API on one port, on 127.0.0.1.**
   Prefer having the backend serve the compiled frontend so it's a single origin.
   (Example: FastAPI mounts the built SPA and serves the API on the same port; the
   frontend calls the API with **relative** paths so it works behind the proxy.)
2. **Add a `GET /healthz`** returning `{"status":"ok"}`.
3. **Pick the next free port** in the 9000s and add an `apps.json` entry.
4. **Build any static assets** the app serves (e.g. `npm run build`).

That's the whole per-app checklist.

---

## The scripts (abstract responsibilities)

These are stack-independent — they only read `apps.json`. Reference
implementations live in this repo's `deploy/` folder; copy them into your central
cluster unchanged.

| Script | Responsibility | Elevation |
|--------|----------------|-----------|
| `generate-caddyfile.ps1` | Read registry → write `Caddyfile` (one `http://<hostname>:80 { reverse_proxy 127.0.0.1:<port> }` block per app). | no |
| `update-hosts.ps1` | Read registry → add/replace a managed block of `127.0.0.1  app.<name>` lines in the hosts file. Idempotent; `-Remove` to undo. | **admin** |
| `start-apps.ps1` | Read registry → launch each app's `start_command` from its `working_dir`; poll `health_path`. | no |
| `start-proxy.ps1` | Locate Caddy (prefer a local `caddy.exe`, else PATH) → run it with the generated `Caddyfile`. | see note |
| `register-startup.ps1` | Register two "At startup" scheduled tasks (Apps + Proxy) as SYSTEM. Idempotent; `-Remove` to undo. | **admin** |

---

## One-time setup (per machine)

Run from the cluster/registry folder. Steps marked **(admin)** need an elevated
PowerShell.

```powershell
# 0. Install the proxy once, and make it self-contained (see the SYSTEM note below)
winget install CaddyServer.Caddy
# then copy caddy.exe next to the scripts so the SYSTEM boot task can find it:
Copy-Item "$env:LOCALAPPDATA\Microsoft\WinGet\Packages\CaddyServer.Caddy_*\caddy.exe" .\caddy.exe

# 1. Build each app's static assets as needed (app-specific), e.g. npm run build

# 2. Generate the proxy config from the registry
powershell -ExecutionPolicy Bypass -File .\generate-caddyfile.ps1

# 3. (admin) Map the hostnames locally
powershell -ExecutionPolicy Bypass -File .\update-hosts.ps1

# 4. (admin) Register the boot tasks
powershell -ExecutionPolicy Bypass -File .\register-startup.ps1

# 5. Start now without rebooting (admin)
Start-ScheduledTask -TaskName <Cluster>-Apps
Start-ScheduledTask -TaskName <Cluster>-Proxy
```

Open `http://app.<name>/`.

---

## Adding an app to a running cluster

```powershell
# 1. Add an entry to apps.json (next free 9000s port, unique hostname)
# 2. Regenerate + remap + re-register:
powershell -ExecutionPolicy Bypass -File .\generate-caddyfile.ps1
powershell -ExecutionPolicy Bypass -File .\update-hosts.ps1        # admin
powershell -ExecutionPolicy Bypass -File .\register-startup.ps1    # admin
# 3. Start it (admin), or reboot:
Start-ScheduledTask -TaskName <Cluster>-Apps
Start-ScheduledTask -TaskName <Cluster>-Proxy
```

No collisions occur as long as each app owns a unique port and hostname.

---

## Critical gotchas (learned the hard way)

- **The boot proxy runs as SYSTEM, which does NOT see your user's PATH.** A
  `winget`-installed Caddy lands in a per-user path SYSTEM can't resolve, so the
  proxy task silently exits and nothing listens on :80. **Fix: keep a copy of
  `caddy.exe` next to the scripts** and have `start-proxy.ps1` prefer that local
  binary. This is the single most common failure.
- **Querying/starting SYSTEM tasks needs elevation.** From a normal shell,
  `Get-ScheduledTask`/`schtasks` on these tasks returns "Access is denied" — that
  does not mean registration failed; check from an elevated prompt.
- **Port 80 conflicts.** IIS, Skype, or another proxy may already hold :80. Check
  `Get-NetTCPConnection -LocalPort 80`. Either free it or set `proxy.http_port` to a
  high port (then URLs become `http://app.<name>:<port>/`).
- **HTTPS.** Don't let Caddy auto-provision TLS for local names — use the `http://`
  site prefix. If you want HTTPS locally, use Caddy's `tls internal` with its local
  CA and trust it, but plain HTTP is simplest for a private machine.
- **Hostname resolution.** If `app.<name>` doesn't resolve, the hosts step didn't
  run elevated; confirm the managed block exists in
  `C:\Windows\System32\drivers\etc\hosts`.
- **Rebuild after UI changes.** If the backend serves a built frontend, rebuild and
  restart that app's task to pick up changes.

---

## Teardown

```powershell
powershell -ExecutionPolicy Bypass -File .\register-startup.ps1 -Remove   # admin
powershell -ExecutionPolicy Bypass -File .\update-hosts.ps1 -Remove       # admin
```

Removes the boot tasks and the managed hosts block; leaves your app code untouched.

---

## Reference implementation

This repo's `deploy/` folder is a working, per-repo instance of this blueprint
(app `mortgage-dashboard`, port 9001). Use it as the template you copy into a
central cluster folder, or extend its `apps.json` to point at sibling repos. See
`deploy/README.md` for the concrete, mortgage-specific commands.
