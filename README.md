# 🏠 Mortgage Dashboard

A personal finance tool for understanding the true monthly cost of owning a home —
not just the mortgage payment, but everything around it: taxes, insurance,
utilities, groceries, car costs, childcare, savings, and more. It shows how much
you have left each month, lets you model extra-payment "what if" scenarios, and can
pull your real bank transactions (read-only) to compare actual spending against your
budget.

It runs entirely on your own machine.

---

## Documentation

- **[User Guide](USER_GUIDE.md)** — using the app: the budget calculator, saving
  scenarios, exporting a PDF, and the transaction-categorization console.
- **[Developer Guide](DEVELOPER_GUIDE.md)** — setup, running, tests, security
  scans, the Plaid secret-rotation procedure, and architecture.
- **[deploy/README.md](deploy/README.md)** — always-on local hosting at
  `http://app.mortgage-dashboard/` (Caddy + Task Scheduler).
- **[deploy/SECURITY_REVIEW.md](deploy/SECURITY_REVIEW.md)** — security review and
  threat model.
- **[Deployment.md](Deployment.md)** — the reusable local `app.*` cluster blueprint.

---

## What it does, briefly

- **Full picture of homeownership cost** — mortgage P&I, escrow (tax, insurance,
  PMI, HOA), and all living expenses in one place.
- **Extra-payment modeling** — recurring or lump-sum extra principal, with payoff
  and interest-savings comparisons.
- **Affordability check** — total monthly obligations vs. take-home pay, with a
  color-coded leftover.
- **Scenarios & PDF export** — save comparisons by address; export a dated report.
- **User-driven categorization** — a command-line console pulls bank transactions
  (via Plaid, read-only) and lets you categorize them with merchant rules you
  control, then compares actual spending against your budget.

---

## How it works

All calculations and categorization happen on a local Python (FastAPI) backend, so
there is one source of truth; the React frontend renders the results. In production
the backend also serves the built frontend, so the whole app runs on a single local
port behind a Caddy proxy.

```
Browser (React SPA) ──JSON──► FastAPI backend (all math + categorization)
```

## Quick start

See the **[Developer Guide](DEVELOPER_GUIDE.md)** for full setup. In short:

```powershell
# Backend
cd backend
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn main:app --reload --port 9001

# Frontend (second terminal)
cd frontend
npm install
npm run dev        # http://localhost:5173
```

---

## License

Personal project. Fork and adapt for your own planning needs.
