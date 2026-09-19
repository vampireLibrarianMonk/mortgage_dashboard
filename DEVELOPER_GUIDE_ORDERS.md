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

## Current status (as of this writing)

- **109 orders** processed (105 Amazon, 3 Walmart, 1 Target), dates 2026-06-19 →
  2026-09-18.
- **101 applied** as splits (117 child items, all sums reconcile).
- **8 remain un-itemized** — see the gap inventory below.

## Atomicity gaps — what blocks the remaining purchases

| Order | Amount | Blocker | Category |
|-------|--------|---------|----------|
| Dehumidifier (07-29) | $0.00 | 100% paid by Amazon reward points — no card charge exists | **Rewards (100%)** |
| Printer Stand (07-31) | $0.00 | 100% points — no card charge | **Rewards (100%)** |
| Vtopmart drawers (08-01) | $75.57 cash / $138.83 consumed | Partly points ($63.26) + multi-shipment; grand total ≠ any single charge | **Rewards (partial)** |
| Whole Foods (08-19) | $16.67 → charged $16.84 | Charge is named "Whole Foods" not Amazon; grocery weight/substitution drift | **Grocery** |
| Whole Foods (08-21) | $37.75 → charged $36.10 | Same | **Grocery** |
| Whole Foods ice cream (08-28) | $34.87 | Charge not yet in synced data | **Data gap (sync)** |
| Goo Gone Walmart (09-17) | $13.48 | PayPal-funded; charge not posted to USAA yet | **Data gap (sync/PayPal)** |
| Pampers (09-18) | $31.79 | Ordered 09-18, charge not posted yet | **Data gap (sync)** |

### Gap categories and their fixes

1. **Grocery (Whole Foods / Amazon Fresh)** — the charge posts under a *different*
   merchant name ("Whole Foods") and the final amount *drifts* from the PDF
   estimate (substitutions, weight-priced produce). Fix: treat Whole Foods as an
   Amazon-family vendor alias, allow a small amount tolerance, guard with an exact
   date match, and scale the split children to the **actual charge**. *(Planned —
   task #6.)*

2. **Rewards points** — orders paid partly or fully with Amazon Visa reward
   points. The card charge (grand total) is less than what was consumed. Fix: the
   **rewards funding model** — record the full consumed value as the spend, with
   points recorded as a second funding/income stream (per card program: NFCU,
   USAA, Chase). Track *redeemed* points only (derivable from the PDF), not a
   points balance. 100%-points orders have no card charge and need a standalone
   record. *(Planned — task #7.)*

3. **Data gaps (unposted / un-synced)** — the charge simply isn't in the store
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
