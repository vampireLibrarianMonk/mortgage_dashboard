# App / GUI follow-up work (deferred)

Captures features to build in the app when we return to GUI editing. All backend
categorization is done via the console; these are presentation / integration
items that surfaced during categorization.

## ATM Section (dashboard monitor)

Add a dedicated ATM panel that monitors three categories together so cash
activity is visible at a glance:

- **ATM Withdrawals** — cash pulled (outflow)
- **ATM Fees** — out-of-network surcharge fees (small, e.g. $1 each)
- **ATM Rebates** — bank refunds of ATM fees (negative / inflow)

Suggested display: the three totals side by side, plus a net line
(Fees minus Rebates = net ATM cost). These are tracked as three distinct
categories in the store (not netted) so each stays traceable; the GUI does the
netting for display only.

## Check images

Bank data gives check number + amount but NOT the payee or the check image
(Plaid does not expose images; they live in the bank portal). Feature: let the
user drop a downloaded check image into a local folder, associate it with a
check transaction by check number, and display it inline when categorizing.
Optional follow-on: OCR the image to auto-read payee/amount.

## Annual budget handling for one-off categories

"Other Home Costs" and "Home Improvement" hold annual / one-off spend
(contractor jobs, HVAC, appliances). Budget vs Actual currently treats every
category as monthly (multiplies by month count). These need annual treatment:
an annual budget input and non-monthly comparison so a once-a-year cost isn't
compared against a monthly target.

## Amazon (Chase card) + PayPal itemization

Chase card is mostly Amazon; bank feed shows only opaque "CHASE CREDIT CRD EPAY"
payment lines (no purchase detail). Same problem as PayPal ("PAYPAL PURCHASE").
Plan: rather than more API integrations, download transaction history from the
respective sites (Amazon, PayPal, Chase) and import. See PAYPAL_REQUIREMENTS.md
for the PayPal specifics. Until then these stay Uncategorized.

## New categories added during categorization

For reference, the categories added while categorizing real data (all live in
txn_store.CATEGORIES): Medical, Skill Improvement, Security, Insurance, Legal,
Home Improvement, College Savings, Investments, Other Home Costs, Review,
Reference, ATM Withdrawals, ATM Fees, ATM Rebates.

Budget vs Actual only aggregates the original monthly budget categories
(Mortgage, Household, Utilities, Vehicle, ChildCare, PetCare, Discretionary).
The newer categories are tracked in the store but are NOT yet wired into the
Budget vs Actual view — that wiring is future GUI work.
