# Spec: Reports — Household Financial Briefing

Status: **iterating in 5 deepening passes.** Pass 1 of 5 recorded below. Each pass
appends/refines; earlier decisions may be superseded by a later pass (noted inline).
Supersedes the initial single-pass draft.

Passes:
- **Pass 1 — Reframe & scope** ← current
- Pass 2 — The "on track" analytics (baseline vs. noise, verdict logic)
- Pass 3 — Category deep-dive ("how are we doing" per category)
- Pass 4 — Graphics architecture (chart/diagram generators; Bedrock scope)
- Pass 5 — Assembly, data contract, build order

---

## PASS 1 — Reframe & scope

### What changed from the initial draft (user steer)

1. **Actuals are the spine, not an optional section.** The briefing's **primary
   purpose** is answering *"are we on track spending-wise?"* using the synced Plaid
   data. Everything else is secondary.
2. **Audience: one, for now — "brief the spouse the way I'd brief myself."** No
   lender/self variants. Candid, no-spin, no falsely-rosy framing. The tone is exactly
   what the user would want if reviewing it alone.
3. **Demote "the plan ahead" (Timeline).** The budget is **not regular yet** — one-off
   new-house-purchase costs mean spend won't stabilize until **~January**. So:
   - The forward Timeline plan is **held off as the lead**; it may still appear as a
     later, clearly-secondary section, gated by the user's "deemed complete" toggle.
   - The **verdict logic must account for noise**: recent lumpy months cannot be
     treated as the recurring trend, or the "on track?" answer is wrong until January.
4. **Category "how are we doing" detail is acknowledged unrefined** — it is a *design
   problem to solve* (Pass 3), not just data to render.
5. **Graphics generation is a first-class requirement** — a real chart/diagram
   pipeline (PlantUML/Kroki-style, possibly a **Bedrock** integration), not only inline
   Recharts (Pass 4).

### Primary purpose (restated)

> **Are we on track with our spending?** — judged honestly against the reality that the
> last few months are distorted by one-time house costs. Then, in progressively finer
> detail: **how are we doing in each spending category**, and only then (optional,
> secondary) **what the forward plan looks like**.

Reader order now reflects this priority:

1. **Verdict: are we on track?** (spending reality vs. expectation, noise-aware)
2. **The overall picture** (income, obligations, what's left — with one-offs called out)
3. **Category-by-category: how are we doing** (the refined deep-dive — Pass 3)
4. **(Optional, secondary) The plan ahead** (Timeline; gated; clearly "forward estimate")
5. **Fine print** (sources, dates, "one-off costs excluded / included where noted")

### The noise problem (central design constraint, detailed in Pass 2)

- Synced actuals already exist **per-month** and **per-year** by the 7 budget
  categories, plus an `unbudgeted_outflow` bucket, with split transactions itemized
  into child categories (see `backend/actuals.py`, `export_actuals` /
  `BUDGET_CATEGORIES` / `UNBUDGETED`). **The raw material to separate noise is present.**
- We must distinguish **one-off / lumpy** spend (closing costs, furnishing, moving)
  from the **recurring baseline** so the "on track" verdict reflects normal life, not
  the move. Until ~January there may be too few clean months to trust a trend — the
  briefing must **say that** rather than fake confidence.

### Open decisions — carried as LABELED ASSUMPTIONS (confirm or veto)

These steer later passes; recorded now so Pass 1 isn't blocked. Working hypotheses:

- **[ASSUMPTION A — baseline]** "On track" is judged **both** against the **planned
  budget** (Dashboard categories) **and** a **recurring baseline derived from the
  actuals** (one-offs stripped). The honest headline verdict leans on the **recurring
  baseline**, with plan-vs-actual shown alongside. *(Pass 2 makes this precise. If the
  user prefers plan-only or actual-only, that simplifies Pass 2/3.)*
- **[ASSUMPTION B — graphics]** Three-tier, degrade-friendly:
  - **charts now** = client-side (Recharts, rendered print-ready like `PrintReport`);
  - **structured diagrams** (category trees, flow/statuses) = a **local diagram service**
    (Kroki/PlantUML/Graphviz style) the backend calls — no cloud dependency;
  - **Bedrock** = scoped **narrowly to narrative/commentary text** (turning the computed
    numbers into human sentences), **never** as the source of the core figures. Image
    generation via Bedrock is possible but parked unless the user wants it.
  *(Pass 4 designs this properly, including the "no service available" fallback.)*
- **[ASSUMPTION C — one-off handling]** One-off spend is identified via a combination
  of (i) the existing `unbudgeted_outflow` bucket, (ii) user-taggable "one-off" marks
  on transactions/categories, and (iii) simple statistical outlier flagging per
  category. *(Pass 2/3 decide the mechanism; may require a small backend addition.)*

### Location & navigation (unchanged from draft)

- New **5th top-level tab**: `Dashboard | Console | Banks | Timeline | Reports`, with a
  real `/reports` URL (extend `Page`, `PAGE_PATHS`, `pageFromPath` in `App.tsx`, add the
  tab button + `<main className="reports-page">` → `<ReportsPage>`).

### Audience & tone (locked for v1)

- **Single audience**: the spouse, briefed as the user would brief themselves.
- Candid and calibrated; **never falsely positive**. A tight or noisy situation is
  stated plainly. First-person plural, minimal jargon, headline numbers rounded.
- No audience/tone presets in v1 (was a v2 idea; now explicitly single-audience).

### Data sources (read-only; report edits nothing)

- **Actuals (spine)**: `plaidActuals()` → per-month/per-year category totals +
  `unbudgeted_outflow`. If Plaid unavailable, the briefing degrades to a plan-only
  snapshot and **says so** (no silent break).
- **Dashboard**: `CalculateResponse` + `CalculateRequest` (planned budget, mortgage
  outcomes) — as `PrintReport` already consumes.
- **Timeline (secondary/optional)**: `timeline_summary` (incl. `negative_windows`),
  `timeline_projection`, `timeline_plan` — only if the user toggles "include plan."

### Persistence (unchanged in principle)

- A `report_config` object on `CalculateRequest` (section toggles, the timeline
  "deemed complete" gate, editable notes/commentary/action-items), persisted on the
  profile like `timeline_plan`. Address is read-only (chosen on the Dashboard).

### Explicitly deferred / out of scope for now

- Leading with the forward plan (deferred until the budget stabilizes ~January;
  Timeline stays a gated secondary section).
- Lender/self audience variants.
- Bedrock **image** generation (narrative-text use is in scope per Assumption B).
- Any write-back to budget/timeline.

### Questions to confirm before Pass 2 (do not block Pass 1)

1. **Baseline (Assumption A)** — plan-vs-actual, recurring-baseline, or both? The
   honest headline should lean on which?
2. **Graphics (Assumption B)** — OK to do client charts + local diagram service now,
   and keep Bedrock to narrative text only? Or do you specifically want Bedrock image
   generation in scope?
3. **One-off tagging (Assumption C)** — are you willing to *mark* one-off transactions
   (in the Console categorizer) so the baseline is clean, or should we auto-detect
   one-offs only?

> **Next: Pass 2** will define the on-track analytics — recurring baseline computation,
> one-off isolation, the "not enough clean data yet" state, and the verdict thresholds —
> grounded in the per-month actuals shape above.


---

## PASS 2 — The "on track?" analytics

Confirmed steer from the user (locks earlier assumptions):
- **Baseline:** show plan-vs-actual **and** a recurring baseline; the **headline
  verdict leans on the recurring baseline**. (Assumption A confirmed.)
- **One-offs:** **manual tagging** in the Console categorizer is the clean path, **plus
  automated outlier detection** (build the auto-detector now, not just later).
  (Assumption C confirmed + expanded.)

This pass defines exactly how we decide "are we on track?" honestly, given the budget
is distorted by one-off house costs until ~January.

### What already exists (do not rebuild)

- **Actuals**: `export_actuals` writes per-month + per-year totals for the 7
  `BUDGET_CATEGORIES` plus an `unbudgeted_outflow` bucket; **splits are itemized** into
  child categories. (`backend/actuals.py`.)
- **Plan side**: `BudgetVsActual.tsx` already maps the profile's computed monthlies to
  the same 7 category names, with `Mortgage = planned_mortgage_outflow_monthly`. So
  **plan-vs-actual variance per category is already computable** from existing data.

Pass 2 adds: (a) **recurring baseline** from actuals with one-offs removed, (b) a
**one-off classification** mechanism (manual tag + auto-outlier), (c) a **confidence /
"not enough clean data yet" state**, and (d) the **verdict thresholds**.

### Core definitions

For each category `c` and month `m`, let `actual[c][m]` be the synced spend.

- **One-off amount** `oneoff[c][m]`: spend flagged as non-recurring (see mechanism).
- **Recurring actual** `rec[c][m] = actual[c][m] − oneoff[c][m]`.
- **Recurring baseline** `baseline[c]`: a robust central estimate of `rec[c][·]` across
  the **eligible months** (see "clean months"). Use the **median** (robust to the few
  remaining spikes), not the mean. Fallback to trimmed mean if <3 months.
- **Plan target** `plan[c]`: the profile's computed monthly for that category.

Two comparisons, both reported; headline leans on the first:

1. **Baseline vs. plan** (headline): `baseline[c] − plan[c]`. "Is our *normal* spending
   in line with what we budgeted?" One-offs excluded → fair even mid-move.
2. **Actual vs. plan** (context): raw `actual[c][m] − plan[c]` for the latest month and
   YTD. Shows the real cash that moved, one-offs included, clearly labeled as such.

### One-off classification (two mechanisms, combined)

A transaction's recurring/one-off status comes from **max(manual, auto)** — a manual
tag always wins; auto-detection fills the gaps.

**(1) Manual tag (clean path).** Add an optional `one_off: bool` (or a reserved
tag/flag) to a transaction in the **Console categorizer**. Requires:
- A categorizer UI affordance + a console command to set/clear the flag.
- `actuals.py` to read the flag and route flagged amounts into `oneoff[c][m]` (and/or a
  dedicated `one_off_outflow` bucket parallel to `unbudgeted_outflow`) instead of the
  recurring category total.
- Persisted with the transaction in the encrypted txn store.

**(2) Auto-outlier (build now).** Per category, over the available months, flag a
month's spend (or an individual large transaction) as a probable one-off when it is a
statistical outlier:
- Robust method: **median + MAD** (median absolute deviation). Flag points where
  `|x − median| > k · MAD` (start `k ≈ 3.5`; tune). MAD is outlier-resistant, unlike
  standard deviation, so a single huge furniture purchase doesn't inflate the threshold
  and hide itself.
- Also flag **single transactions** above a category-relative threshold (e.g. a txn >
  N× the category's median monthly total) even in a month that isn't otherwise an
  outlier.
- Auto-flags are **suggestions**: surfaced in the report ("we treated $X in Vehicle as
  one-off — confirm?") and ideally promotable to a manual tag. Never silently
  authoritative — transparency rule.
- Implemented in the backend (has the transaction-level data); exposed via the actuals
  aggregation so both the report and Budget-vs-Actual can use it.

### "Clean months" & confidence (the January problem, made explicit)

The verdict must not trust distorted months. Define eligibility + confidence:

- **Eligible month**: a fully-synced calendar month (not the current partial month)
  after removing one-offs. The move-in / closing months will still be eligible for the
  *recurring* comparison because one-offs are stripped — but if a category has too few
  recurring data points, confidence drops.
- **Confidence per category** (drives wording, not hiding):
  - **High**: ≥ 4 eligible months with low residual variance after one-off removal.
  - **Medium**: 2–3 eligible months, or higher variance.
  - **Low / "not enough clean data yet"**: ≤ 1 eligible month, or variance still high
    (the move is still dominating). → The briefing **says so**: "Too soon to call —
    spending is still settling after the move; expect a clear read by ~January."
- A category may be High while the household overall is Low (e.g. Mortgage is stable
  from day one; Household/Discretionary are still noisy). Report confidence
  **per category** and roll up an **overall confidence** = the weighted-by-spend min.

### Verdict logic (headline + per-category status)

Per category, compute variance ratio on the **baseline vs. plan** comparison:
`v[c] = (baseline[c] − plan[c]) / plan[c]` (guard `plan[c] = 0`).

Status bands (tune later; direction: over-plan spending is the concern):
- **On track**: `|v| ≤ 10%`.
- **Slightly over / under**: `10% < |v| ≤ 25%`.
- **Over / under**: `|v| > 25%`.
- **Unknown**: category confidence = Low → status is "still settling," not a number.

**Overall verdict sentence** (leaning on recurring baseline, honesty-first):
- If overall confidence Low → *"It's too early to say for sure — the move is still
  working through our numbers. Here's what we can see so far, and we'll have a clear
  read around January."*
- Else if all/most categories On track and total recurring ≤ plan → *"Our normal
  spending is on track with the budget."*
- Else if a few categories over → *"Mostly on track; [Vehicle, Discretionary] are
  running higher than planned — details below."*
- Else if broadly over / recurring > take-home → *"Our normal spending is running ahead
  of the budget — here's where and by how much."* (plain, not alarmist)
- Always: one-off totals are **called out separately** ("Plus ~$X in one-time move
  costs this period, which we expect to stop.").

### Numbers the report shows for "on track"

- **Overall**: recurring monthly spend vs. planned total; recurring leftover vs. planned
  leftover; one-off total for the period (separate line); confidence badge.
- **Per category**: plan, recurring baseline, variance (%/$), status, confidence, and
  the raw actual (latest month + YTD) as context. (The full deep-dive is Pass 3.)

### Likely backend additions (confirmed by this pass; finalized in Pass 5)

- Transaction-level `one_off` flag: storage (txn store), a console command to set/clear,
  and categorizer UI affordance.
- `actuals.py`: emit **recurring vs. one-off** split per category per month (extend the
  aggregates JSON with e.g. `categories_recurring`, `one_off_outflow`, and per-month
  one-off detail), plus the **auto-outlier** computation (median+MAD) with flags.
- A small **baseline/verdict module** (server-side, testable in isolation like the
  timeline engine) that, given the extended actuals + plan targets, returns per-category
  baseline, variance, status, confidence, and the overall verdict facts. The report
  frontend renders these; Bedrock (Pass 4) may phrase them, but the **numbers and status
  are computed here**, never by an LLM.

### Edge cases (Pass 2 scope)

- **No eligible months** (brand-new sync): overall = "not enough data yet"; show plan
  only; invite another sync after more history.
- **plan[c] = 0 but actual > 0**: category flagged "spending with no budget line" (a
  distinct status; ties into `unbudgeted_outflow`).
- **plan[c] > 0 but actual = 0**: "budgeted but nothing spent" (could be timing; low
  confidence).
- **Everything one-off** (pure move month): recurring baseline may be empty → Low
  confidence, verdict defers to January.
- **Auto-outlier disagreement**: if auto flags something the user later un-tags, manual
  wins; report reflects the manual decision.

> **Next: Pass 3** — the category deep-dive: for each of the 7 categories, what "how are
> we doing" actually shows (status, trend, drivers, plain-language read), and how it
> uses the baseline/one-off machinery defined here.


---

## PASS 3 — Category deep-dive ("how are we doing in each category")

The user flagged this area as "severely unrefined." The reason a naive version feels
unrefined: a uniform plan-vs-actual table treats all 7 categories identically, but each
behaves differently. Mortgage variance is almost always an error to investigate;
Utilities swing seasonally; Discretionary over-plan is a behavior signal; Vehicle is
inherently lumpy. This pass gives each category **its own read**, built on the
baseline/one-off/confidence machinery from Pass 2.

### The per-category card (uniform structure, category-specific brains)

Every category renders the same **card shape** so the briefing is scannable, but the
thresholds, expected-shape, and driver logic differ per category:

```
┌─ <Category>                              [status badge] [confidence badge] ─┐
│ Plain read:  one human sentence (the takeaway)                              │
│ Numbers:     plan  |  recurring baseline  |  variance (%/$)  |  latest actual │
│ Trend:       sparkline of recurring monthly spend (one-offs greyed)         │
│ Drivers:     top 1–3 merchants / subcategories moving the number            │
│ One-offs:    "$X treated as one-time this period" (+ confirm/annotate)      │
│ Note:        optional user commentary (free text)                           │
└─────────────────────────────────────────────────────────────────────────────┘
```

- **Status badge**: On track / Slightly over / Over / Under / Still settling / No
  budget line (from Pass 2 bands, but per-category thresholds below).
- **Confidence badge**: High / Medium / Low (Pass 2). Low → the plain read hedges.
- **Plain read**: the single most important line — generated from the numbers + the
  category's own rules (Bedrock may phrase it in Pass 4; the facts come from the
  backend module).
- **Trend sparkline**: recurring monthly spend across eligible months; one-off months
  shown but de-emphasized so the eye sees the baseline.
- **Drivers**: requires transaction/merchant-level detail (see "Data needs" below).

### Per-category intelligence

Each category defines: *expected shape*, *what's worth flagging*, *typical drivers*,
and *how to phrase over/under*.

1. **Mortgage** — *Expected: flat and exact.* This is a fixed obligation
   (`planned_mortgage_outflow_monthly`). Any material variance is an **anomaly to
   investigate**, not a spending habit: a missed/double payment, escrow adjustment, or
   an extra-principal payment landing in-category. Tight band (On track if within a few
   %). Over/under phrased as *"check this"*, not *"you overspent."* Drivers: usually a
   single servicer transaction; flag if count ≠ expected per month.

2. **Household** — *Expected: steady with grocery-driven wobble.* Groceries dominate
   and scale with life events (new baby, guests). Moderate band. Drivers: grocery
   merchants vs. one-off home goods (which during the move are heavy one-offs — this is
   a prime auto-outlier category). Phrase over as *"running higher — mostly groceries
   / mostly one-time home setup?"* and let the one-off split answer it.

3. **Utilities** — *Expected: seasonal.* Electricity/gas swing summer/winter, so a
   single month over plan may be seasonal, not overspending. Use a **wider band** and,
   where enough history exists, compare to the **same season** rather than a flat plan.
   With <12 months (our case), explicitly note *"limited history; seasonal read not yet
   possible."* Drivers: per-utility split (already itemized where categorized).

4. **Vehicle** — *Expected: lumpy.* Gas is recurring; tax, maintenance, insurance are
   periodic. A big maintenance bill is a **one-off**, not a trend — this category leans
   hard on one-off isolation. Band: judge on **recurring (gas + insurance)** vs. plan;
   report periodic items separately as "expected periodic costs." Phrase: *"day-to-day
   vehicle spend is on track; $X maintenance was a one-time hit."*

5. **ChildCare** — *Expected: contractual and stable, with known step-changes.* Daycare
   tuition is a fixed weekly/monthly figure (ties directly to the Timeline childcare
   rows and the tuition schedule the user shared). Variance is usually a **schedule
   change** (a child starting/ending, a sibling discount) — cross-reference the Timeline
   if included. Tight band. Drivers: the childcare provider merchant. Phrase step-changes
   as *"changed because [child started / discount applied]"* when the timeline explains
   it.

6. **PetCare** — *Expected: low and steady with vet spikes.* Small recurring (food) +
   occasional vet one-offs. Wide relative band (small absolute numbers make % swings
   look dramatic — report **$ variance prominently**, not just %). Drivers: vet vs.
   food/grooming.

7. **Discretionary** — *Expected: variable; this is the behavior dial.* Unlike the
   others, over-plan here is a genuine **choice signal**, not noise. Report it plainly
   and non-judgmentally (spouse-as-self tone): *"we spent $X more on discretionary than
   planned — here's the top of it,"* with drivers (dining, subscriptions, etc.). This is
   the category where the briefing is most likely to prompt a conversation, so drivers
   matter most here.

Plus the two **non-category buckets** from Pass 2, shown after the 7:

- **Unbudgeted outflow** (`unbudgeted_outflow`): real spend with no budget line
  (transfers the user kept). Shown as a transparency line: *"$X moved that isn't in any
  budget category."*
- **One-off / move costs** (`one_off_outflow`): the isolated one-time spend across all
  categories, totaled: *"$X in one-time costs this period (mostly the move), expected to
  stop."* This is what makes the "on track" verdict fair before January.

### Category ordering in the briefing

Order by **attention warranted**, not alphabetically: categories that are **Over** with
**High confidence** first (they need discussion), then Watch/Slightly-over, then
On-track, then Still-settling. Within a tier, largest $ variance first. This puts the
conversation-worthy items at the top where a spouse will actually read them.

### Data needs introduced by Pass 3 (drivers = transaction-level)

The **plain read**, **status**, and **variance** need only the aggregated
recurring/one-off totals from Pass 2. But **Drivers** (top merchants/subcategories) and
the **trend sparkline** need finer data than `plaid_actuals.json` currently exposes:

- **Drivers**: top-N merchants (or child subcategories from splits) per category for the
  period, with amounts. Requires either (a) extending the actuals export with a
  per-category top-merchants list, or (b) a new lightweight aggregation the report reads.
  Keep it **aggregated** (names + amounts), not raw transactions, to match the
  "aggregates-only" privacy posture of the existing pipeline.
- **Trend sparkline**: per-category recurring monthly series — a natural extension of the
  existing per-month totals (add the recurring split per month, already needed for
  Pass 2's baseline).

Both are backend aggregation additions (finalized in Pass 5), consistent with the
existing "compute aggregates server-side, render on the client" pattern.

### Progressive disclosure (keep it a briefing, not a ledger)

- **Default**: show the **plain read + status + the one hero number** per category.
- **Expand**: reveal numbers row, trend, and drivers on demand (screen); in print,
  include drivers only for **Over/Watch** categories to keep the briefing tight.
- On-track, high-confidence categories collapse to a single reassuring line each.

### Confidence honesty carries through

A category's deep-dive **cannot show a confident verdict at Low confidence.** At Low, the
card shows the plain read as *"still settling — [recurring so far] $X vs plan $Y, but
too few clean months to call,"* the trend sparkline with a "sparse data" note, and
suppresses the status badge (shows "Still settling" instead). This is the Pass 2 rule
applied at card level so no category can look more certain than the data supports.

### Edge cases (Pass 3 scope)

- **Category with no plan but real spend** → card titled "No budget line," shows actual
  + drivers, status = "not budgeted" (invite adding a Dashboard line).
- **Category with plan but no spend** → "budgeted, nothing spent yet" (timing/low
  confidence), no false "great, under budget!" if it's just early.
- **All-one-off category** (e.g. Household during move) → recurring baseline empty; card
  = "still settling," one-off total shown as the story.
- **Tiny-absolute categories** (PetCare) → lead with $ variance; suppress alarming % on
  small bases.

> **Next: Pass 4** — the graphics architecture: the **alpha loop** putting the three
> generation methods (client charts / local diagram service / Bedrock) in competition,
> and the **automated best-practices evaluator** that judges them. Pass 3's sparklines,
> category cards, and trend visuals are the concrete render targets that bake-off must
> satisfy.


### Pass 3 addendum — transaction-level review & the daily cadence (user steer)

Two clarifications from the user that extend Pass 3's scope:

**(A) Drill down to individual transactions, reviewed one by one.**
Pass 3 is not only aggregates and drivers — the category deep-dive is also where the
user **inspects the actual transactions assigned to a category, one at a time**, the
same review motion used in the Console categorizer. So each category card gains a
**"review transactions" drill-down**:

- Expanding a category lists its **individual transactions** for the period (date,
  merchant/name, amount, current category, split children if any, and the one-off flag).
- From this list the user can, per transaction, **confirm / recategorize / mark
  one-off / split** — reusing the existing categorizer actions rather than inventing a
  parallel flow (the Console already has recategorize/split/order-split commands; the
  report's drill-down should call the same backend operations).
- This closes the loop with Pass 2's one-off tagging: the cleanest place to *mark* a
  one-off is exactly here, while reviewing the category it landed in.
- **Privacy/posture note:** the top-line briefing stays aggregates-only (splits itemized,
  no raw txns) for the spouse-facing view; the **transaction-by-transaction drill-down
  is the working/review surface** (the "brief myself" mode). Keep the print/briefing
  output aggregate; keep the interactive review full-detail. (These can be the same page
  with the detail behind an expander that is excluded from print by default.)

Implication: the report frontend needs read access to the **categorized transactions**
per category+period (not just the aggregates JSON), and write access to the existing
categorizer operations. Finalize the endpoints in Pass 5 (likely: a
`transactions?category=&period=` read that returns aggregated-but-itemized rows, and
reuse of existing console recategorize/split/one-off commands).

**(B) Daily sync + checking cadence.**
The data behind all of this is refreshed on a **daily** rhythm, and part of the workflow
is a **daily check** of newly synced transactions:

- A **daily sync** pulls new transactions (and refreshes the per-account balance
  snapshot used by the Timeline). This is the same `sync` path already built; the new
  requirement is that it runs **on a schedule** (e.g. a Windows Scheduled Task like the
  app boot tasks, or a lightweight in-app scheduler) and that its recency is visible.
- The report surfaces a **freshness indicator**: "synced through <date>, N new since
  last review" so the user knows the read is current and how much is unreviewed.
- **Daily checking**: newly synced, still-uncategorized (or auto-categorized-but-
  unconfirmed) transactions are queued for the one-by-one review (A). The report can show
  a small **"needs review (N)"** badge and route into the drill-down. Confirming them
  keeps the baseline/one-off classification (Pass 2) accurate day to day.
- Interaction with **confidence (Pass 2)**: a daily cadence steadily grows the count of
  clean, reviewed months — so the "still settling → clear read by ~January" arc is
  literally driven by this review discipline. Confidence should reflect **reviewed**
  data, not just synced data (an unreviewed pile of new txns shouldn't inflate
  confidence). Consider weighting confidence by the reviewed/confirmed fraction.

Implications to finalize in Pass 5:
- A **scheduled daily sync** (mechanism: Scheduled Task vs. in-app timer — decide in
  Pass 5; the boot-task pattern already exists in `deploy/`).
- A **"last synced / last reviewed / new since" state** persisted and surfaced.
- A **review queue** concept (uncategorized + unconfirmed) exposed to the report.
- Confidence math (Pass 2) refined to key off **reviewed** months/transactions.

> These additions keep Pass 3 as the analytical + review heart: aggregates and per-
> category intelligence for the briefing, transaction-by-transaction review for keeping
> the underlying classification honest, on a daily cadence that also drives how quickly
> confidence rises toward a trustworthy January read.


---

## PASS 4 — Graphics architecture: the alpha loop & automated evaluator

User steer: do **not** pre-pick a graphics pipeline. Put the three methods in
**competition** (an "alpha loop"), judged by an **automated best-practices evaluator**.
So this pass specifies (1) the three competitors behind a common interface, (2) the
render targets they must satisfy, (3) the evaluator that scores them, and (4) the loop
that runs the bake-off and picks per-target winners.

### Design principle: renderers are interchangeable behind one contract

Every graphic in the briefing is described by a **RenderSpec** (data + intent), never by
a method. Any competitor consumes the same RenderSpec and emits an **artifact**
(SVG/PNG + metadata). This makes the bake-off fair and lets the winner be chosen
**per render-target**, and swapped later without touching the report.

```
RenderSpec {
  target:   "runway" | "category_trend_sparkline" | "category_bars" |
            "budget_vs_actual" | "one_off_split" | "category_tree" |
            "cashflow_flow" | ...          # the concrete visuals from Passes 2–3
  intent:   "compare" | "trend" | "composition" | "flow" | "status"
  data:     <normalized series/records for that target>   # from the backend analytics
  context:  { title, currency, print: bool, width, height, palette, a11y_labels }
}
Artifact {
  method:   "client" | "diagram_service" | "bedrock"
  mime:     "image/svg+xml" | "image/png"
  bytes/svg
  meta:     { render_ms, deterministic: bool, cost_estimate, warnings[] }
}
```

### The three competitors

1. **Client (Recharts / canvas → SVG/PNG).** In-process in the browser (and/or a
   headless render for print/PDF). Deterministic, free, offline, but limited to chart
   types we code. Strong for `runway`, `category_bars`, `budget_vs_actual`,
   `sparkline`. This is the **safe baseline** every target must beat to justify another
   method.

2. **Local diagram service (Kroki / PlantUML / Graphviz / Mermaid).** Backend shells out
   to (or HTTP-calls) a locally-run renderer. Deterministic, no cloud, great for
   **structured diagrams** the client can't easily do well: `category_tree`
   (budget → categories → drivers), `cashflow_flow` (income → obligations → leftover
   Sankey-ish), status maps. Cost = a local install/jar/container; must degrade if
   absent.

3. **Bedrock.** Two candidate roles, kept **separate and narrowly scoped**:
   - **3a. Narrative/commentary text** (in scope): turn the computed facts (Pass 2/3
     numbers + statuses) into human sentences (the "plain read"). **Never invents
     numbers** — it is given the exact figures and must only phrase them; the evaluator
     enforces this (see "faithfulness" below).
   - **3b. Image generation** (candidate, likely to *lose* for data viz): non-
     deterministic, can hallucinate axes/values → **disqualified for any data-bearing
     chart** by policy. May only compete for **decorative/illustrative** targets (e.g. a
     cover graphic), if at all. Included in the loop mainly so the evaluator can *prove*
     it's unsuitable for data, rather than us asserting it.

### Render targets (the bake-off's fixtures)

Concrete visuals from earlier passes that the loop must produce, each with a fixed
**test fixture** (canned input data + expected properties):

- `runway` — two-line raw/adjusted + zero line + negative-window shading (exists in
  `RunwayChart`; client is incumbent).
- `budget_vs_actual` — per-category plan vs. recurring baseline vs. actual (grouped
  bars).
- `category_trend_sparkline` — recurring monthly series, one-offs de-emphasized.
- `one_off_split` — recurring vs. one-off composition for a period.
- `category_tree` — budget → 7 categories → top drivers (structured; diagram-service
  territory).
- `cashflow_flow` — income → obligations → leftover (flow/Sankey; diagram-service
  territory).

Each fixture ships with **ground-truth values** so the evaluator can check the artifact
actually represents them (see faithfulness).

### The automated best-practices evaluator

Scores each artifact **0–100** on weighted criteria. Two classes of check: **hard gates**
(fail → disqualified for that target) and **scored heuristics**.

**Hard gates (pass/fail):**
- **Faithfulness / no-fabrication:** the artifact must encode the fixture's ground-truth
  values. For SVG (client/diagram), parse the DOM and assert the plotted values / labels
  match inputs within tolerance; for text (Bedrock narrative), extract every number and
  assert each appears in the input facts (no invented figures) and no contradiction of
  the computed status. **Bedrock image gen fails this for data targets by construction.**
- **Determinism:** render the same spec twice; artifacts must be identical (client,
  diagram) — required for any data chart. Non-deterministic methods are gated out of
  data targets.
- **Renders at all / valid mime / within size budget.**
- **Accessibility floor:** title + axis/label text present; color-contrast ≥ WCAG AA;
  not color-only encoding (has labels/patterns). (WCAG AA is checkable
  programmatically for contrast; full a11y still needs human/AT review — noted.)

**Scored heuristics (weighted, tunable):**
- **Data-ink / clarity** (Tufte-ish): proportion of ink encoding data vs. chrome;
  penalize clutter, gridline overload, redundant legends.
- **Legibility:** min font size, label overlap detection (bounding-box collisions),
  tick density vs. width.
- **Encoding appropriateness:** intent↔chart match (e.g. `composition` → stacked/part-
  to-whole, not a line; `trend` → line/area; `flow` → Sankey/graph). Mismatch penalized.
- **Print fidelity:** contrast/legibility at print DPI and in grayscale (briefings get
  printed).
- **Consistency:** palette + type scale match the app's tokens across targets.
- **Cost/latency:** `render_ms` and `cost_estimate` as tie-breakers (client ~free/fast;
  Bedrock slow/paid).

**Evaluator implementation notes:**
- Prefer **structural/programmatic** checks (parse SVG, measure boxes, compute contrast,
  diff renders) over subjective ones — these are reproducible and CI-able.
- The evaluator is a **standalone, testable module** (mirrors the timeline/verdict
  engine pattern) with its own fixtures and unit tests, so scores are stable and the
  bake-off is repeatable.
- Optional **LLM-as-judge** (Bedrock) as a *secondary, advisory* score for "does this
  read clearly?" — but it **cannot override hard gates or the structural score**, to
  avoid a non-deterministic judge picking a non-deterministic renderer. Kept advisory
  and logged, not authoritative.

### The alpha loop (bake-off runner)

```
for each render_target:
  for each competitor method that opts into this target:
     artifact = method.render(fixture.spec)
     result   = evaluator.score(artifact, fixture.ground_truth)
  rank surviving (gate-passing) artifacts by score
  winner[target] = top-ranked; record full scorecard + artifacts
emit: a report (per-target winners, scores, disqualifications, sample artifacts)
```

- Runs **offline / in CI**, not in the user's request path. Output is a **decision
  record** (which method wins which target, with evidence) — the report app then uses
  the **winning method per target** via the RenderSpec contract.
- Re-runnable when a renderer changes, a new target is added, or thresholds are tuned;
  regressions are visible (a method's score dropping) like a test suite.
- **Human-in-the-loop checkpoint:** the loop *proposes* winners with a visual
  contact-sheet of artifacts; the user can confirm/override (best-practices automation
  informs the decision, doesn't blindly rule).

### Runtime wiring (after the loop has chosen)

- The report requests graphics by **RenderSpec + target**; a small **renderer registry**
  maps each target to its chosen method, with an automatic **fallback chain** (chosen →
  client baseline) if the preferred method is unavailable (diagram service down, Bedrock
  not configured). So the briefing always renders *something* correct.
- **Print path:** whatever method wins, the artifact must be embeddable as static
  SVG/PNG in the print output (the client baseline guarantees this; diagram service
  returns SVG/PNG natively; Bedrock-narrative is text, not a graphic).

### Bedrock: scope, config, and guardrails

- **In scope:** narrative phrasing of already-computed facts (category "plain read,"
  overall verdict wording) — **behind a faithfulness gate** (every number must trace to
  an input fact; status must not be contradicted).
- **Config:** AWS creds via the existing environment/credential pattern; **feature-
  flagged off by default** so the app runs fully without it (client baseline + template
  sentences as the no-Bedrock fallback). Cost/latency budgeted; responses cached per
  (facts-hash) so identical inputs don't re-bill.
- **Out of scope (v1):** Bedrock as a source of any number, status, or data-bearing
  chart. Decorative image gen only if it clears the (non-data) gates and the user opts in.

### Degradation matrix (must always produce a valid briefing)

| Available            | Charts        | Diagrams            | Narrative        |
|----------------------|---------------|---------------------|------------------|
| Client only          | client        | client fallback      | template text    |
| Client + diagram svc | client        | diagram service      | template text    |
| + Bedrock            | client        | diagram service      | Bedrock (gated)  |

No configuration ever yields a broken graphic — the client baseline + template
sentences are the guaranteed floor.

### Deferred / out of scope (Pass 4)

- Bedrock image generation for data charts (**disallowed by policy**, not just deferred).
- A live, per-request renderer bake-off (the loop is offline/CI; runtime uses the
  chosen winners).
- Interactive/animated graphics in the printed briefing (static artifacts only for
  print).

> **Next: Pass 5** — assembly & build order: the full data contract (frontend types +
> backend modules for analytics, one-off flag, drivers, freshness/review state, the
> renderer registry + evaluator), persistence, print, edge cases, and the sequenced
> implementation plan tying Passes 1–4 together.


### Pass 4 addendum — code-to-image is deterministic; dependencies live in Docker

**Clarification the user raised: do we have code→image (SVG/UML), rather than asking an
LLM to "generate this"? — Yes.** This is a hard architectural rule, restated so it isn't
lost:

- **All data-bearing graphics are produced by deterministic code→image compilers, never
  by an LLM.**
  - **Client charts (Recharts):** code + data → SVG in the DOM (serialized for print, or
    rasterized to PNG). No LLM.
  - **Diagrams (PlantUML / Graphviz / Mermaid, via Kroki):** our code **emits the diagram
    source text** (DOT / PlantUML / Mermaid) *from the computed numbers*, and a
    deterministic renderer compiles it to SVG/PNG. Example: from budget facts our code
    builds a Graphviz/Mermaid string (`income → obligations → leftover`, category nodes
    with amounts) and the renderer draws it. Same input → same image, every time. This is
    a **compiler**, not generative AI.
- **The LLM (Bedrock), if enabled, only writes prose** around those images (the category
  "plain read," verdict wording) — given the exact figures, gated so it cannot invent a
  number or contradict a status. It **never** produces a chart, a diagram, an axis, or a
  value. Bedrock image-gen remains disqualified for data graphics by policy.
- So the canonical pipeline is:
  `analytics numbers → code generates chart config / diagram source → deterministic
  renderer → SVG/PNG`, with the LLM (optional) phrasing prose beside the artifact only.

**Rendering dependencies run in Docker — nothing scattered on the Windows host.**

To avoid installing Java (PlantUML), the Graphviz binary, and assorted tooling loose on
the Windows laptop, the diagram-renderer baseline dependencies are **containerized**:

- Use a **Docker-hosted diagram service** — **Kroki** is the fit: a single container
  (or a small compose stack) that fronts PlantUML, Graphviz, Mermaid, etc. behind **one
  HTTP endpoint**. The app POSTs diagram source, gets SVG/PNG back. The **only** host
  install is Docker itself; no jars/binaries "flying around."
- The backend's diagram-service competitor (Pass 4) targets this container's endpoint
  (configurable URL, default `http://localhost:<port>`). Health-checked; if the container
  is down, the renderer registry falls back to the client baseline (degradation matrix).
- **Mermaid nuance:** Mermaid can also render **client-side in-browser** (no container).
  It stays a competitor either way; the alpha-loop evaluator decides per target whether
  containerized Kroki or in-browser Mermaid wins (don't pre-assert). If a target's winner
  is client-side Mermaid, that target needs **no Docker** at all — a nice reduction.
- **Bedrock** is not containerized (it's a cloud API, feature-flagged off by default).
- Managing the container alongside the app: reuse the existing `deploy/` pattern
  (a compose file + a scheduled/boot task to bring the service up), decided concretely in
  Pass 5. The app must run **without** the container (client baseline floor) — Docker is
  an enhancement, not a hard dependency.

Net: deterministic compilers do the drawing; their dependencies are quarantined in
Docker; the LLM only phrases prose; and the app still produces a correct briefing if
neither Docker nor Bedrock is present.


---

## PASS 5 — Assembly, data contract & build order

Ties Passes 1–4 into a buildable plan: the data contract (frontend types + backend
modules), the Docker + scheduled-sync deploy decisions, persistence, print, edge cases,
and a sequenced build order. Grounded in the actual backend layout: `actuals.py`,
`txn_store.py`, `console_routes.py`, `plaid_routes.py`, `models.py`, `profiles_store.py`,
`calculations.py`.

### Architecture overview (data flow)

```
Plaid sync (daily, scheduled) ──▶ txn_store (encrypted txns, + one_off flag)
                                        │
                       actuals.py (extended) ──▶ aggregates JSON:
                         • categories (as today)
                         • categories_recurring   (one-offs removed)
                         • one_off_outflow         (isolated one-time spend)
                         • per-category drivers    (top merchants/subcats, aggregated)
                         • per-category monthly recurring series (sparklines)
                         • auto-outlier flags (median+MAD)  [suggestions]
                                        │
                    report_engine.py (NEW, server-side, testable) ──▶ per-category:
                         baseline, variance, status, confidence + overall verdict facts
                                        │
   /report/* endpoints  ◀───────────────┘   (+ review queue, freshness state)
                                        │
   ReportsPage (frontend)  ── renders verdict, category cards, drill-down review,
     graphics via RenderSpec → renderer registry (client | Kroki-in-Docker | Bedrock-prose)
```

**Principle preserved throughout:** numbers/status computed server-side (testable,
deterministic); client renders; graphics via deterministic compilers; LLM only phrases.

### Backend modules & changes

1. **`txn_store.py` — one-off flag.** Add an optional `one_off: bool` per transaction
   (default false). Read/write within the existing encrypted store; migration-safe
   (absent = false).
2. **`console_routes.py` — tagging + review ops.** Add console commands / endpoints to
   set/clear `one_off` on a txn (and reuse existing recategorize/split). Expose a
   **review read**: transactions by `category` + `period`, returned itemized-but-
   aggregatable (date, name, amount, category, split_children, one_off, confirmed).
3. **`actuals.py` — extended aggregation.** In addition to today's `categories` +
   `unbudgeted_outflow`, emit: `categories_recurring`, `one_off_outflow`, per-category
   **monthly recurring series**, per-category **drivers** (top-N merchant/subcat names +
   amounts, aggregated only), and **auto-outlier flags** (median+MAD per category; flags
   are suggestions). Keep the aggregates-only privacy posture.
4. **`report_engine.py` (NEW).** Pure, testable module (mirrors the timeline engine):
   input = extended actuals + plan targets (the 7 category monthlies +
   `planned_mortgage_outflow_monthly`) + reviewed-state; output = per-category
   `{ plan, baseline, actual_latest, actual_ytd, variance_pct, variance_dollar, status,
   confidence, drivers, recurring_series, one_off_total }` and overall
   `{ verdict_key, overall_confidence, recurring_leftover, planned_leftover,
   one_off_total, synced_through, reviewed_through, needs_review_count }`. **No LLM.**
5. **`report_routes.py` (NEW) or extend `plaid_routes.py`.** `GET /report/summary`
   (engine output), `GET /report/transactions?category=&period=` (review list),
   `POST /report/txn/{id}/one-off` (set/clear), and `GET /report/freshness`
   (synced/reviewed/new-since). Auth/posture consistent with existing routes.
6. **`models.py` — `ReportConfig`.** Optional model (all fields defaulted) added to
   `CalculateRequest` as `report_config: ReportConfig = ReportConfig()`, so it validates
   and round-trips on the profile (like `TimelinePlan`). No numeric constraints.
7. **Graphics: `render_engine` + `evaluator` (bake-off) modules.** The RenderSpec
   contract, the three competitors' adapters, the evaluator (structural checks +
   fixtures), and the offline alpha-loop runner. Lives backend-side for diagram/eval;
   client charts render in the frontend. Bake-off is CI/offline; runtime uses a
   **renderer registry** with fallback chain.

### `ReportConfig` (persists on the profile)

```
ReportConfig {
  include_timeline: bool = false        # the "deemed complete" gate (secondary section)
  sections: { [id]: bool }              # include/exclude per section (defaults on where
                                        # data exists)
  opening_note: str = ""
  closing_note: str = ""
  commentary: { [categoryOrSectionId]: str }
  action_items: str[] = []
}
```
Mirror the `timeline_plan` treatment across the stack: `types.ts` interface,
`useCalculation` initial state + `LOAD` backfill, `ProfileManager` empty defaults,
`CalculateRequest.report_config` in `models.py`. **Editing `report_config` must not do
useful work on `/calculate`** — it isn't a calc input; the recompute is harmless (cheap)
but confirm no flicker (Timeline established this pattern).

### Frontend components

- **`ReportsPage.tsx`** — the tab shell: freshness banner, readiness checklist, composer
  (section toggles + timeline gate + editable notes), and the preview.
- **Verdict + headline tiles** — from `/report/summary` (overall verdict, recurring
  leftover, one-off total, confidence badge).
- **`CategoryCard.tsx`** — the uniform card (Pass 3): plain read, numbers, trend
  sparkline, drivers, one-off line, status/confidence badges, optional commentary.
- **Transaction drill-down** — reuses categorizer actions (recategorize / split /
  one-off) against the review endpoints; excluded from print by default.
- **Graphics** — request via RenderSpec; registry routes to client / Kroki / Bedrock-
  prose with fallback.
- Reuse: `PrintReport.tsx` (print structure/CSS + static charts), `RunwayChart.tsx`
  (runway), `BudgetVsActual.tsx` (plan-side mapping already done).

### Deploy: Docker diagram service + scheduled daily sync

- **Kroki in Docker** (Pass 4 addendum): a compose file under `deploy/`; brought up by a
  boot/scheduled task like the existing app tasks. Configurable endpoint; health-checked;
  **app runs without it** (client baseline fallback). Only host install is Docker.
- **Scheduled daily sync**: a Windows **Scheduled Task** (reuse the `deploy/` task
  pattern) invoking the existing `sync` path daily; refreshes txns + balance snapshot.
  Persist + surface `synced_through` / `reviewed_through` / `new_since`. (In-app timer is
  a fallback option; Scheduled Task preferred for parity with the boot tasks.)

### Print / output

- Screen preview interactive; **Print** reuses the `window.print()` + print-stylesheet
  pattern. Filename `<date>_<address>_household_briefing`.
- Print = **aggregate/briefing view only**: verdict, category cards (drivers only for
  Over/Watch), optional timeline section. Transaction drill-down and the review queue are
  screen-only (excluded from print).
- Graphics embed as static SVG/PNG (client baseline guarantees embeddable; Kroki returns
  SVG/PNG; Bedrock output is prose, not a graphic).

### Testing

- **`report_engine`**: unit tests for baseline (median/MAD), one-off isolation, variance/
  status bands, confidence (incl. "still settling"), per-category rules, verdict keys,
  and every Pass 2/3 edge case. Fixture-driven (like the timeline tests).
- **`actuals.py` extension**: recurring/one-off split, drivers, outlier flags,
  splits-itemized correctness.
- **`evaluator`**: fixtures with ground truth; assert hard gates (faithfulness,
  determinism, a11y floor) and stable scores.
- Full suite + **pre-commit** (repo-root `.venv\Scripts\pre-commit`) green before commit;
  ruff import-sort on new files (known gotcha — run ruff `--fix` with
  `--config backend/pyproject.toml`).

### Consolidated edge cases (Passes 1–5)

- No income / empty budget → verdict "not enough entered"; tiles "—".
- Brand-new sync / no eligible months → "not enough data yet"; plan-only; invite re-sync.
- Negative leftover **today** → stated plainly (not future-only).
- All-one-off period (the move) → recurring baseline empty → "still settling → ~January".
- `plan=0, actual>0` → "spending with no budget line"; `plan>0, actual=0` → "budgeted,
  nothing spent" (low confidence).
- Plaid absent → actuals sections omitted, said so; briefing degrades to plan-only.
- Docker/Kroki down → diagrams fall back to client baseline.
- Bedrock off/unconfigured → template prose (default).
- Profile unsaved → banner nudge; Save uses Dashboard-selected address (disabled w/ hint
  if none — matches Timeline Save).
- Unreviewed pile of new txns → does **not** inflate confidence (confidence keys off
  reviewed data).

### Build order (sequenced; each step verify → tsc/tests/pre-commit)

1. **Spec** (this doc — done, 5 passes).
2. **`ReportConfig`** model + frontend types + state wiring (initial/LOAD/ProfileManager)
   + `models.py`; round-trip test. (No behavior yet — foundation, like timeline step 2.)
3. **Reports tab scaffold + `/reports` route** (5th tab; extend `Page`/`PAGE_PATHS`/
   `pageFromPath`) + `<ReportsPage>` shell reading/writing `report_config`.
4. **One-off flag**: `txn_store` field + `console_routes` set/clear command +
   categorizer affordance + tests.
5. **`actuals.py` extension**: recurring/one-off split, drivers, monthly recurring
   series, auto-outlier (median+MAD) + tests.
6. **`report_engine.py`** + `report_routes` (summary / transactions / one-off /
   freshness) + tests (the analytical heart).
7. **Frontend: verdict + headline tiles + category cards** (Pass 2/3 render) reading the
   engine output; progressive disclosure.
8. **Transaction drill-down review** (reuse categorizer ops) + review-queue/freshness UI.
9. **Graphics: RenderSpec contract + client baseline** wired into the cards/charts;
   **Kroki-in-Docker** service + registry + fallback; **evaluator + alpha-loop** (offline/
   CI) producing the winners decision record; optional **Bedrock-prose** behind a flag +
   faithfulness gate.
10. **Scheduled daily sync** (Windows task) + freshness surfacing.
11. **Print stylesheet + Save-as-PDF + Save-to-profile** wiring.
12. **Verify end-to-end** (tsc, backend suite, pre-commit), rebuild dist, bring up live
    via app.mortgage_dashboard (+ bring up the Kroki container/task).

### Suggested delivery milestones (usable increments)

- **M1 (steps 2–3):** tab exists, config persists — no analytics yet.
- **M2 (steps 4–7):** the real value — "are we on track?" verdict + category cards from
  live actuals, one-off aware. **This is the primary purpose delivered.**
- **M3 (step 8):** transaction-by-transaction review + daily-review workflow.
- **M4 (step 9):** graphics pipeline + bake-off + Docker diagram service.
- **M5 (steps 10–11):** scheduled sync automation + polished print/PDF briefing.

> **Spec complete (Passes 1–5).** Ready to implement starting at build step 2 (the
> `ReportConfig` foundation), or to adjust any pass before we start.
