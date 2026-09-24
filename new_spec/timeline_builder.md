# Spec: Timeline Builder

Status: **design complete, pre-implementation.** This captures the settled design
from the UI/UX back-and-forth so implementation can proceed without re-deciding.

## Purpose

A generic, forward-looking **planning** tool: place labeled cost "timelines" (with
start/end dates) on a shared time axis, model purchases with funding methods, apply
offsetting "adjustments," and project the **monthly leftover runway** over time so the
user can see when planned costs outrun their budget — and model how they'd cover it.

It is a **best-guess future capital-allocation** tool, not a ledger. It stays
deliberately decoupled from the live budget: the only real-data couplings are two
single numbers (see "Coupling," below), to avoid confusing bleedover.

## Location & navigation

- New **4th top-level tab**: `Dashboard | Console | Banks | Timeline` (extend the
  `page` union in `App.tsx`, add a `<button className="page-tab">` and a conditional
  `<main>` block — same pattern as Console/Banks).
- It is its own page (needs room for the builder + charts), not a Dashboard section.

## Page layout (top → bottom)

1. **Timelines table** — planned recurring costs & purchases.
2. **Adjustments list** — offsets (+save / −spend) to cover the plan.
3. **Span view** — each timeline as a bar on a shared year axis; ◆ markers for
   one-time purchase costs.
4. **Runway chart** — projected monthly leftover over time; **two lines**: solid =
   timelines only (raw), dashed = with adjustments applied. Zero line + warn/✔.
5. **Account-dip strip(s)** — for purchases funded from an account, that account
   drawing down from its latest synced balance.

## Data model (generic; lives on `CalculateRequest` so it persists via profiles)

### Timeline (a recurring planned cost, optionally a purchase)
```
Timeline {
  label:      str
  category:   str            # a budget category OR "Generic"
  start:      "YYYY-MM"      # date-picker; month granularity
  end:        "YYYY-MM" | null   # null = "ongoing"
  base:       float          # starting recurring amount
  unit:       "month" | "year"
  escalation_value: float    # applied once per year on the start anniversary; 0 = flat
  escalation_unit:  "percent" | "dollar"   # 3% compounding, OR +$50 flat per year
  purchase:   Purchase | null    # present when this timeline is a purchase
}
```

### Purchase (funding for a one-time acquisition, e.g. the SUV)
```
Purchase {
  amount:      float
  method:      "pay_in_full" | "payment_plan" | "already_paid"
  # payment_plan:
  down_payment: float             # optional
  apr:          float             # annual %, for the financed remainder
  term_months:  int
  # (financed = amount - down_payment; monthly computed from apr/term)
  account:     str | null         # earmarked account (bank slug + mask), or "other/cash"
}
```
- `pay_in_full`: full `amount` draws `account` on `start` date; no ongoing cost from
  the purchase itself (ongoing upkeep/insurance = the timeline's own `base`).
- `payment_plan`: `down_payment` draws `account` on `start`; a computed monthly
  payment feeds the runway for `term_months` from `start`.
- `already_paid`: **excluded from projection** (recorded/labeled only).

### Adjustment (a flat offset applied across the WHOLE timeline horizon)
```
Adjustment {
  label:  str
  amount: float      # + = money freed up / saved ; - = new expense
  unit:   "month" | "year"
}
```
- No per-adjustment dates (applies across the whole horizon), no escalation.
- Mixed month/year units normalize to a common cadence for the runway math.

### Timeline settings (page-level)
```
TimelineSettings {
  starting_leftover: float        # the runway's starting line
  carry_over_leftover: bool       # if true, starting_leftover is filled from the
                                  # Dashboard's monthly_leftover (the ONE opt-in
                                  # budget coupling); else user-typed (generic)
  horizon_years: int              # how far to project (e.g. 10)
}
```

## Coupling (deliberately minimal — avoid bleedover)

Only two real-data couplings, both single numbers, both opt-in:
1. **Starting leftover** — optionally carried from the Dashboard's `monthly_leftover`
   (one number). Otherwise typed. The Timeline never edits the budget; if the runway
   goes negative it *warns* and the user adjusts the Dashboard themselves.
2. **Account latest balance** — for a purchase's funding account, seeded from that
   account's latest synced balance (see "Balance snapshot").

No category totals are pulled in. No live budget layering.

## Balance snapshot (new backend capability)

- Extend `sync` to also call `accounts_balance_get` **once per linked item** and
  persist each account's latest balance into a **single slot per account**:
  `{ account_id, mask, bank, balance, as_of }` — **overwritten** each sync. **No
  history** (explicitly not a time series).
- The funding UI reads this slot for the chosen account as the drawdown starting
  point and shows the `as_of` timestamp. A `⟳ refresh` can re-pull on demand.
- **Honesty:** the balance is real + timestamped for *today*; any figure projected
  forward to a future purchase date is a **planning estimate**, labeled as such in
  the UI. The account-dip line is **flat from today until an event** (we do not model
  intervening income/spend on the account in v1).

## Projection engine (backend)

A new function expands the timelines + adjustments into a per-period series over
`horizon_years`, monthly resolution internally, emitting per-year points for the
chart (mirror the amortization-schedule delivery pattern — return an array on
`CalculateResponse`, or a dedicated `/timeline` endpoint).

Per period, compute:
- **timeline cost**: for each active timeline (start ≤ period ≤ end), its escalated
  recurring amount (normalized to monthly) + any payment-plan monthly within term.
- **one-time spikes**: full purchase (pay_in_full) or down payment (payment_plan) on
  the purchase month → a spike in the runway that month and a step-down in the funding
  account's balance line.
- **adjustments**: net of all adjustments (normalized to monthly), + = adds to runway.
- **runway_raw** = starting_leftover − timeline_costs (no adjustments).
- **runway_adjusted** = runway_raw + adjustments.
- **first_negative_month**: earliest period where runway_adjusted < 0 (drives warn/✔).
- **account series**: per funded account, balance starting at latest snapshot, flat,
  stepping down on each draw (down payment / full purchase) dated to it.

Escalation: on each start-anniversary year, `percent` → base *= (1+value/100)
compounding; `dollar` → base += value. Applies to timeline recurring cost only (not
adjustments, not one-time amounts).

## Frontend (Recharts, mirrors AmortizationChart pattern)

- **Builder table**: add/remove timeline rows; per row: label, category dropdown,
  start/end date pickers (end→"ongoing"), base, unit toggle (month/year), escalation
  (number + %/$ toggle), and for purchases a `⚙ Funding` panel + one-time amount.
- **Funding panel**: method radios; payment-plan fields (down, apr, term → computed
  monthly shown); account dropdown (populated from linked banks by mask, + "other")
  with latest-balance display + `as_of` + `⟳ refresh`; planning-estimate note.
- **Adjustments list**: add/remove rows: label, amount (+save/−spend), unit toggle;
  show net normalized (/yr and ≈/mo).
- **Span view**: bars positioned by start/end on a year axis; ◆ one-time markers.
- **Runway chart**: two lines (solid raw, dashed adjusted), zero reference line,
  first-negative warning, one-time spike markers.
- **Account-dip strip**: per funded account; starts at latest balance (as_of),
  flat-until-event step-downs; estimate note.

## Out of scope (v1)

- Balance history / time series (single latest slot only).
- Modeling income/other spend on a funded account between now and an event (flat).
- Multi-phase single timeline (compose via multiple timelines/adjustments instead).
- Escalation on adjustments.
- Auto-editing the Dashboard budget from the Timeline (it only warns).

## Build order

1. Spec (this doc).
2. Backend models (+ frontend types).
3. Projection engine (+ emit on response).
4. Balance snapshot on sync.
5. Backend tests + full suite + pre-commit.
6. Frontend tab scaffold + state wiring.
7. Builder table + adjustments + funding panel.
8. Span view + runway chart + account-dip.
9. Build dist, verify end-to-end, bring up live via app.mortgage_dashboard.
