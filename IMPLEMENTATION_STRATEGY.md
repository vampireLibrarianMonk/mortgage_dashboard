# Mortgage Dashboard — Implementation Strategy

## Technology Stack

| Layer | Choice | Rationale |
|-------|--------|-----------|
| Frontend | React + Vite + TypeScript | Hooks model maps cleanly to derived state; strong charting/PDF ecosystem |
| Backend | Python + FastAPI | Already in PyCharm; Pydantic validates business rules natively |
| Charting | Recharts | Lightweight, React-native amortization visualization |
| PDF Export | WeasyPrint (backend) | Server-side HTML→PDF; no browser dependency |
| Persistence | SQLite (via SQLAlchemy) | Zero-config, file-based, good for single-user tool |

---

## Project Structure

```
mortgage_dashboard/
├── backend/
│   ├── main.py               # FastAPI app, CORS, route registration
│   ├── models.py             # Pydantic input/output schemas
│   ├── calculations.py       # All mortgage math
│   ├── pdf_export.py         # HTML template → PDF
│   ├── db.py                 # SQLite save/load
│   └── tests/
│       └── test_calculations.py
├── frontend/
│   ├── src/
│   │   ├── App.tsx
│   │   ├── types.ts          # Mirrors backend schemas
│   │   ├── api.ts            # Fetch wrapper for /calculate, /save, /export
│   │   ├── hooks/
│   │   │   └── useCalculation.ts
│   │   └── components/
│   │       ├── inputs/       # Left panel sections
│   │       │   ├── HousePurchase.tsx
│   │       │   ├── LoanTerms.tsx
│   │       │   ├── TaxAndCost.tsx
│   │       │   ├── HouseholdExpenses.tsx
│   │       │   ├── VehicleExpenses.tsx
│   │       │   ├── CollegeSavings.tsx
│   │       │   ├── AdditionalExpenses.tsx
│   │       │   ├── TakeHomePay.tsx
│   │       │   └── ExtraPrincipal.tsx
│   │       ├── results/      # Right panel sections
│   │       │   ├── MonthlySummaryBanner.tsx
│   │       │   ├── PurchaseAndLoan.tsx
│   │       │   ├── LifetimeOutcomes.tsx
│   │       │   ├── ExtraPrincipalEffects.tsx
│   │       │   └── CashToClose.tsx
│   │       └── AmortizationChart.tsx
│   └── package.json
├── requirements.txt
└── IMPLEMENTATION_STRATEGY.md
```

---

## Phases

### Phase 1 — Calculation Engine (Backend)

**Goal:** All mortgage math working and tested, independent of UI.

1. Define Pydantic models for every input section
2. Implement `calculations.py`:
   - Standard amortization (P&I, schedule)
   - Extra principal simulation (recurring + lump sum)
   - Monthly normalization (weekly → monthly, annual → monthly)
   - Cash-to-close (low/high prepaids estimate)
   - Affordability summary (planned housing total vs take-home)
3. Expose `POST /calculate` — accepts all inputs, returns all outputs
4. Unit tests covering edge cases (0% down, no extra principal, short terms)

**Deliverable:** Working API you can hit with curl or Postman.

---

### Phase 2 — Input UI (Frontend)

**Goal:** All form inputs wired up with local state.

1. Scaffold React app (`npm create vite@latest frontend -- --template react-ts`)
2. Build left-panel form components matching spec sections
3. Implement percent/dollar toggle component (reusable)
4. Add/edit/delete rows for Additional Expenses and Take Home Pay logs
5. `useReducer` for centralized form state
6. Debounced API call to `/calculate` on any input change

**Deliverable:** Full input form that sends valid payloads to backend.

---

### Phase 3 — Results & Visualization (Frontend)

**Goal:** Right panel displays all calculated outputs.

1. Summary banner (required payment, planned outflow, take-home, leftover)
2. Result card components for each summary section
3. Amortization chart (Recharts area — principal vs interest over loan life)
4. Conditional display of extra principal effects (only when configured)
5. Responsive two-column layout (inputs left, results right)

**Deliverable:** Full working dashboard matching the ASCII layout spec.

---

### Phase 4 — Persistence & Export

**Goal:** Save scenarios and generate reports.

1. `POST /save` — persist current inputs to SQLite
2. `GET /scenarios` — list saved scenarios
3. `GET /load/{id}` — restore a saved scenario
4. `POST /export/pdf` — generate PDF report matching screen grouping
5. Frontend: Save button, Load dropdown, Download PDF button

**Deliverable:** Complete feature set per requirements doc.

---

## API Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/calculate` | Run all calculations, return results |
| POST | `/save` | Persist scenario |
| GET | `/scenarios` | List saved scenarios |
| GET | `/load/{id}` | Load a saved scenario |
| POST | `/export/pdf` | Generate and return PDF |

---

## Key Design Decisions

1. **All math lives in the backend** — single source of truth, testable without UI, reusable for PDF
2. **Frontend is stateless regarding calculations** — sends inputs, receives outputs
3. **Closing costs** — default to financed into loan; add a toggle for "pay at closing"
4. **Monthly leftover** — includes ALL budget categories (housing + household + vehicle + college + additional)
5. **PDF layout** — mirrors screen grouping exactly

---

## Business Rules Enforcement

| Rule | Where Enforced |
|------|----------------|
| No negative percentages/dollars | Pydantic validators (backend) + input constraints (frontend) |
| Percent ≤ 100 where applicable | Pydantic `le=100` constraint |
| Extra principal within loan term | Backend validation in calculation |
| Lump sum > 0 | Pydantic `gt=0` constraint |
| Required vs planned payment distinction | Separate output fields, labeled clearly |

---

## Getting Started (When You Return)

```bash
# Backend
cd backend
pip install fastapi uvicorn pydantic sqlalchemy weasyprint pytest
uvicorn main:app --reload

# Frontend
cd frontend
npm install
npm run dev
```

Then we build Phase 1 first — the calculation engine is the foundation.
