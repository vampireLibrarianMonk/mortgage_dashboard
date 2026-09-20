# Developer Guide — Order-Details Itemization (Transaction Splitting)

How the app turns retailer "Order details" PDFs into per-item budget splits, and
what still blocks full "atomicity" (every purchase itemized).

> Companion to the main [Developer Guide](DEVELOPER_GUIDE.md). The email-ingest
> effort is documented separately in
> [DEVELOPER_GUIDE_MAILBOX.md](DEVELOPER_GUIDE_MAILBOX.md) (paused).

---

## Why this exists

A bank/card feed shows one lumpy line ("AMAZON MKTPL* $75.57"). A budget wants to
know *what* that was — groceries vs. a tool vs. a toy. The retailer's saved
"Order details" PDF has the per-item breakdown, so we parse it and **split** the
matching transaction into categorized child items.

## Pipeline (drop → parse → file → match → split)

1. **Drop** order PDFs into `dump/` (mixed vendors OK).
2. **Parse** — a per-vendor `OrderReader` (`importers/orders_walmart.py`,
   `orders_amazon.py`, `orders_target.py`) extracts order#, dates, line items
   (name/qty/price), and totals (subtotal, shipping, tax, tip, discounts,
   rewards). Content-sniffing dispatch picks the reader (`orders.read_order`).
3. **File** — `orders.process_order_file` moves each into
   `processed_document/<slug>/` (`slug = date-vendor-<units>items-total`), raw +
   renamed, skipping pre-`DATA_START` orders. `processed_document/` is gitignored.
4. **Match** — `order_service.plan_split` finds the stored transaction that
   carries the charge (see matching rules below).
5. **Split** — the matched transaction becomes a `Split` parent with per-item
   children (categories from the merchant-rule engine on item name, else the
   parent's category, else Uncategorized). `actuals.py` distributes a Split
   parent's children into their budget categories.

## Matching rules (the discernible, repeatable pairing)

A charge matches an order when ALL hold:
- **Same amount** (|charge| == order total, ±$0.01), on a
- **vendor-named** row (the bank descriptor contains the vendor), with the
- **charge date inside the span [order_date .. delivery_date]**, padded 1 day
  before (pre-auth) and 3 after (settlement lag).

Key refinements (each added measurable coverage):
- **authorized_date** is used as the charge date (swipe/ship time), not the
  posted date (which lags 1–3 days). This disambiguates same-priced repeat
  purchases (two $8.47 Amazon orders → each pins to its own charge).
- **Delivery date** is extracted ("Delivered/Arriving <date>") because retailers
  bill at ship time; the charge can land weeks after the order (Subscribe & Save,
  slow ship). The match window spans order→delivery, so a charge at either end
  matches.
- **Collision guard** (`resolve_batch`): each charge is claimed by at most one
  order; the closer-dated order wins, the other is set aside for manual pairing —
  never double-split.
- **Exclusions**: payment/transfer/deposit rows and netted PayPal purchases are
  never split.
- Amount+date-only matches (generic, non-vendor-named row) are `needs-confirm`,
  not auto-applied. `plan_manual_split(order, txn_id)` forces a specific pairing.

Fee handling: shipping + tax − discounts split **equally** per line item;
children sum exactly to the order value (last child absorbs rounding).

**Goods + separate tip charge (grocery/Fresh delivery).** A delivery tip is
*sometimes* bundled into the one order charge (then the single-charge split above
already spreads it across items like tax) and *sometimes* billed as its own
charge named "Amazon Tips". When separate, no single charge equals the order
total, so `plan_split` returns no-match and `plan_grocery_tip_split(order)` takes
over: it pairs the order with a **goods charge** (`total − tip`, grocery drift
allowed) **and** a separate **"Amazon Tips" charge whose amount equals
`order.tip` to the cent**, both inside the charge window. Each charge becomes its
own Split parent (children sum to its own amount), and the tip is distributed
across the **same item categories** as the goods (proportionally) so it lands
like tax, not as a standalone line. Both parents are stamped with the `order_no`
so neither is re-matched. The exact tip-amount + "Amazon Tips" name identity is
what keeps the extra date-residual pairing safe. The console `orders` command
falls back to this path automatically; a bundled tip does not trigger it.

## Current status (as of this writing)

- **109 orders** processed (105 Amazon, 3 Walmart, 1 Target), dates 2026-06-19 →
  2026-09-18.
- **108 applied** as splits (all child sums reconcile, 0 mismatches): 101 direct
  card-charge matches + 2 Whole Foods grocery matches + 2 synthetic
  points-purchases ($0 card, 100%-points) + 1 small marketplace order + 1 grocery
  order billed as goods + a separate tip (two Split parents).
- **Remaining un-itemized** — 1 partial-points/multi-shipment edge case (Vtopmart,
  its cash is already captured as fragment rows) and a couple of pure data gaps
  awaiting a `sync`. See the gap inventory below.

## Atomicity inventory — the originally-blocked purchases

Of the 8 orders that couldn't be matched by the first pass, 4 are now resolved
(grocery + points-purchase) and 4 remain (1 edge case, 3 data gaps).

| Order | Amount | Blocker | Status |
|-------|--------|---------|--------|
| Dehumidifier (07-29) | $0.00 | 100% Amazon reward points — no card charge | **✅ Resolved — synthetic $0 points-purchase** |
| Printer Stand (07-31) | $0.00 | 100% points — no card charge | **✅ Resolved — synthetic $0 points-purchase** |
| Whole Foods (08-19) | $16.67 → charged $16.84 | Charge named "Whole Foods" not Amazon; grocery drift | **✅ Resolved — grocery alias + drift, scaled to charge** |
| Whole Foods (08-21) | $37.75 → charged $36.10 | Same | **✅ Resolved — grocery alias + drift, scaled to charge** |
| Vtopmart drawers (08-01) | $75.57 cash / $138.83 consumed | Partly points ($63.26) + multi-shipment; grand total ≠ any single charge — cash already captured as fragment rows ($33.18 + $42.39) | **Left un-itemized (edge case)** |
| Whole Foods ice cream (08-28) | $34.87 = goods $29.87 + tip $5.00 | Billed as two charges (goods + a separate "Amazon Tips" tip); no single $34.87 charge | **✅ Resolved — goods+tip split, tip spread across item categories** |
| Goo Gone Walmart (09-17) | $13.48 | PayPal-funded; charge not posted to USAA yet | **Data gap (sync/PayPal)** |
| Pampers (09-18) | $31.79 | Ordered 09-18, charge not posted yet | **Data gap (sync)** |

### Gap categories and their fixes

1. **Grocery (Whole Foods / Amazon Fresh)** — ✅ *implemented.* The charge posts
   under a *different* merchant name ("Whole Foods") and the final amount *drifts*
   from the PDF estimate (substitutions, weight-priced produce). The reader
   (`orders_amazon._GROCERY_RE`) flags these orders (`OrderDetail.grocery=True`)
   and sets `match_names` aliases. The matcher then allows a small amount
   tolerance for grocery orders only (`_GROCERY_DRIFT_PCT=0.08`,
   `_GROCERY_DRIFT_ABS=$3.00`), **guarded** by an exact authorized-date match and
   the vendor/alias name check so the loose amount can't false-match. Split
   children are **scaled to the actual charge** (`plan_split` sets
   `target_total = charge amount`) so they reconcile to the real bank amount.

2. **Rewards points** — ✅ *implemented (funding model).* Orders paid partly or
   fully with Amazon Visa reward points: the card charge (grand total) is less
   than what was consumed. The reader separates points (`OrderDetail.rewards_points`)
   from real discounts (`savings`) and exposes `consumed_value`. The split records
   the **full consumed value** across item children plus a **negative "Rewards"
   child** equal to the points, so the children sum to the card charge and the
   budget shows true consumption plus a rewards funding line.
   - **100%-points orders** ($0 card charge, no bank row): `plan_points_purchase`
     / `apply_points_purchase` create a **synthetic $0 transaction** (stable id
     `points_<vendor>_<order#>`, `source='points_purchase'`, `bank='rewards'`;
     re-runs dedupe via upsert) whose children still sum to $0. Applied for the
     Dehumidifier ($317.99) and Printer Stand ($117.33).
   - **actuals** is unchanged and correct: item children land in their budget
     categories (true consumption); the "Rewards" child is excluded from spend
     because "Rewards" is not a budget/unbudgeted category. *(A visible
     rewards-income total is not surfaced in actuals output — possible future
     enhancement.)*
   - **NFCU / USAA cash-back:** due-diligence finding — these programs redeem
     rewards as a *separate account credit* (statement credit or deposit), **not**
     applied at the point of purchase. So they surface as their own redemption
     transaction tagged "Rewards" — no per-order logic needed. Only Amazon/Chase
     points appear at-purchase (from the order PDF).
   - **Edge case — Vtopmart (08-01):** partial points *and* multi-shipment, so the
     grand total matches no single card charge; the cash portion is already
     captured as the fragment rows ($33.18 + $42.39). Creating a synthetic row
     would double-count, so this order is left un-itemized by design.

3. **Goods + separate tip charge** — ✅ *implemented.* A grocery/Fresh delivery
   tip is sometimes billed as its own "Amazon Tips" charge, so the order settles
   as *two* charges (goods + tip) and matches no single charge.
   `plan_grocery_tip_split` / `apply_grocery_tip_split` pair both charges (goods ≈
   `total − tip` with grocery drift; tip charge amount == `order.tip` exactly),
   split each as its own parent, and spread the tip across the same item
   categories as the goods (like tax). See the matching-rules section above.

4. **Data gaps (unposted / un-synced)** — the charge simply isn't in the store
   yet (recent order, PayPal settlement lag, or the account hasn't been synced
   since). Fix: a fresh `sync` (and, for PayPal, the monthly statement — PayPal
   only publishes a month's statement after month-end, ~Oct 1 for September).
   No code change; these resolve as data arrives.

### Vendors without readers yet

- **Costco** — if Costco provides an itemized order/receipt PDF, a
  `orders_costco.py` reader (same `OrderReader` interface) would add it. Not yet
  confirmed whether Costco exposes per-item order docs.
- Any other retailer follows the same one-module pattern.

## Known limitations

- **Amazon bank descriptors carry a payment-reference code, not the order
  number**, so there is no exact order↔charge key. Matching relies on amount +
  vendor + the order→delivery date span. This is why same-priced repeats need the
  authorized-date/delivery-date signals to disambiguate.
- **Multi-shipment + points orders** (e.g. Vtopmart) fragment into several card
  charges that don't sum to the grand total; these can't be matched 1-to-1 and
  need the rewards model or manual handling.
