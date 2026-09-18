# PayPal Transaction Ingestion — Requirements (future work)

Deferred. Captures what's needed to add PayPal as a data source so opaque
"PAYPAL PURCHASE" bank lines can be replaced with itemized detail.

## Why

Bank feeds show PayPal spend only as an opaque "PAYPAL PURCHASE" line (no
merchant, no category). PayPal's own API returns the underlying merchant/amount,
which would de-anonymize those transactions for accurate categorization. Plaid
does NOT reliably provide PayPal transaction-level data, so we go direct to PayPal.

Note: in the current sample, PayPal was only ~$128 across ~14 transactions, so the
budget impact is small. Revisit if PayPal spend grows.

## API

- **PayPal Transaction Search API v1**: `GET /v1/reporting/transactions`
  (https://developer.paypal.com/api/transaction-search/v1/search-get)
- Auth: OAuth 2.0 client-credentials (first-party access to your own account).
- Range: date-windowed; ~3 year lookback; data must be a few hours old.
- Returns transaction_info (amount, date, ids) + payer/payee + optional cart_info.

## Setup steps (to do later)

1. Create a PayPal Developer app at developer.paypal.com (Live, not Sandbox).
2. Enable the **Transaction Search** feature/scope on that app.
3. Obtain the app's `client_id` and `secret`.
4. Put them in the repo-root `.env` as `paypal_client_id` / `paypal_secret`, then
   store them in Windows Credential Manager (extend store-plaid-credentials.ps1),
   mirroring how Plaid/AWS secrets are handled. Never commit them.

## Build outline (mirrors the Plaid pipeline)

1. `paypal_ingest.py`: OAuth token, call `/v1/reporting/transactions` for the
   window (>= 2026-04-01), reduce to {date, year, month, name/merchant, amount},
   log counts only.
2. Feed into the SAME categorize -> store -> export flow.
3. **Double-count avoidance (critical):** when PayPal-direct data covers a period,
   EXCLUDE the bank feed's "PAYPAL PURCHASE" lines for that period, so the same
   money is not counted twice. The bank line is replaced by the itemized PayPal
   transactions.

## Privacy

Same model as the rest of the pipeline: descriptions may go to Bedrock for
categorization; stored data is aggregated month/year/category/amount only; no
raw PayPal transactions persisted or surfaced in the app.
