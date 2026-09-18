# plaid_pipeline (superseded — see the in-app Console)

The standalone pipeline that used to live here (ingest → Bedrock categorization →
encrypted store → report → export) has been **replaced by a user-driven console
inside the app**. Categorization is no longer automatic or LLM-based; the user
categorizes transactions with terminal commands and those decisions are remembered
as merchant rules.

## Where the functionality now lives

- **Bank sync + ingest** → `POST /console` command `sync` (backend/console_routes.py),
  reusing the existing Plaid tokens in Windows Credential Manager.
- **Encrypted transaction + merchant-rule store** → `backend/txn_store.py`
  (AES/Fernet, key in Credential Manager, `backend/txn_data/`).
- **Categorization** → user-driven console commands (`list`, `merchants`, `cat`,
  `rule`), no Bedrock.
- **Aggregate export / report** → console `summary` command writes
  `backend/plaid_actuals.json` (aggregates only), consumed by the app's
  "Budget vs Actual" view.

## What remains here

- `PAYPAL_REQUIREMENTS.md` — deferred future work to pull PayPal transactions via
  PayPal's own Transaction Search API (Plaid does not reliably provide them).

## Note

Bedrock is no longer used for categorization. `boto3` may remain installed in the
venv but is not required by the app.
