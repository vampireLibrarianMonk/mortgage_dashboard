# User Guide

How to use the Mortgage Dashboard: the budget calculator, saving scenarios,
exporting reports, and the transaction-categorization console.

If you're setting up or developing the app, see the
[Developer Guide](DEVELOPER_GUIDE.md) instead.

---

## What the app does

The dashboard shows the true monthly cost of owning a home — not just the mortgage
payment, but everything around it: taxes, insurance, utilities, groceries, car
costs, childcare, savings, and more. It tells you how much you have left each month
and lets you explore "what if" scenarios like extra principal payments. It can also
pull your real bank transactions (read-only) and compare your actual spending
against your budget.

The app has two pages, switched with the tabs in the header:

- **Dashboard** — the budget calculator and results.
- **Console** — a command-line page for syncing banks and categorizing transactions.

---

## Dashboard

### Choosing your mode

At the top of the inputs panel, toggle between:

- **New Purchase** — buying a home. Enter home price, down payment (percent or
  dollars), closing costs, and earnest money.
- **Existing Mortgage** — you already own. Enter your outstanding balance and home
  value.

### Entering expenses

Each section collects a category of costs:

- **Tax & Cost** — property tax (percent of value or flat dollars), homeowner's
  insurance, PMI, HOA.
- **Household** — groceries, general upkeep, and similar.
- **Utilities** — internet/cable, phone, electric, gas, water.
- **Vehicle** — car tax, gas, maintenance, insurance.
- **Child Care**, **Pet Care**, **Discretionary** — as applicable.
- **Additional Expenses** — add as many custom line items as you need (monthly or
  annual).

Many lines have an inline **M/D toggle** to mark them Mandatory or Discretionary,
which feeds the mandatory-vs-discretionary split in the results.

### Adding income

In **Take Home Pay**, add each income source. Enter monthly or annual amounts — the
app normalizes everything to monthly for comparison.

### Extra principal payments

Model paying down the loan faster:

- **Recurring** — an extra amount on a schedule (monthly, quarterly, semi-annual,
  annual), with a start year and an optional end year (or "until payoff").
- **Lump sums** — one-time payments in specific years.

The results show how much time and interest these save.

### Reading the results

The right panel updates as you type:

- Monthly payment (principal & interest, plus escrow), total planned housing outflow
- Standard vs. accelerated payoff date, months saved, interest saved
- An amortization chart (principal vs. interest by year)
- Affordability: total monthly obligations vs. take-home pay, with a color-coded
  leftover (green = within budget, red = over)

### Saving scenarios

Click **Save** to store the current scenario, keyed by street address, so you can
compare different properties. Load any saved profile to restore all its values.

### Exporting a PDF

With results on screen, click **📄 Export PDF** in the header. This uses your
browser's print dialog — choose "Save as PDF". The filename is pre-filled with the
date and address for easy filing. (Make sure pop-ups aren't blocked.)

---

## Console (bank sync & categorization)

The **Console** tab is a command-line interface for pulling bank transactions and
categorizing them. Categorization is entirely user-driven — you decide what each
merchant means, and the app remembers your rules.

Type a command and press Enter. Use the up/down arrows to recall previous commands.
Type `help` at any time for the full list.

### Commands

| Command | What it does |
|---------|--------------|
| `help` | Show all commands and the category list |
| `status` | Connected banks, transaction counts, rule count |
| `sync` | Pull new transactions from all linked banks |
| `list [uncategorized\|<Category>]` | List transactions (defaults to uncategorized), largest first |
| `merchants [uncategorized]` | Group by merchant with counts and totals (best triage view) |
| `cat <merchant text> <Category> [@mask]` | Categorize every matching transaction and **create a rule** so future ones match too |
| `set <match text> <Category> [@mask] [$amount]` | One-off categorize specific transactions **without** creating a rule |
| `label <match text> = <label> [@mask] [$amount]` | Attach a human note to matching transactions |
| `rule ls` / `rule rm <pattern>` | List or remove merchant rules |
| `summary [year]` | Per-category totals; also refreshes the Budget vs Actual view |
| `undo` | Revert the last change |
| `plaid [status\|items\|balances\|link]` | Plaid diagnostics |

### `cat` vs `set` — the important distinction

- **`cat`** creates a **rule**. It categorizes everything matching now *and* keeps
  categorizing new matching transactions on future syncs. Use it for recurring
  merchants (Costco, Netflix, your utilities).
- **`set`** is a **one-off**. It categorizes the specific transactions that match
  right now and creates **no rule**, so nothing is auto-applied later. Use it when a
  description is generic or the transaction is a one-time event you don't want a
  standing rule for.

### Scoping matches

Both `cat` and `set` accept optional narrowing so a rule only touches what you mean:

- `@mask` — restrict to one account by its last-4 digits, e.g. `@0000`. An
  account-scoped rule always wins over a plain text rule for the same merchant.
- `$amount` — restrict to an exact amount, e.g. `$70.04`.

More specific rules win over broader ones. For example, a `costco gas` rule sends
fuel to Vehicle while a plain `costco` rule sends warehouse purchases to Household —
the longer, more specific pattern takes precedence.

### Examples

```
sync
merchants uncategorized
cat Costco Household
cat Costco Gas Vehicle
cat Netflix Discretionary
cat USAA FUNDS TRANSFER Ignore @0000
set Transfer to Checking Utilities @0003 $70.04
label FCWA = Fairfax Water (FCWA)
rule ls
summary
undo
```

### Categories

`Mortgage`, `Household`, `Utilities`, `Vehicle`, `ChildCare`, `PetCare`,
`Discretionary`, `Medical`, `Skill Improvement`, `Security`, `Insurance`, `Legal`,
`Home Improvement`, `College Savings`, `Investments`, `ATM Withdrawals`,
`ATM Fees`, `ATM Rebates`, `Other Home Costs`, `Income`, `Transfer`, `Ignore`,
`Review`, `Reference`, `Uncategorized`.

A few have special meaning:

- **Ignore** — internal transfers and money movement that isn't real spending or
  income (e.g. moving money between your own accounts, credit-card payments whose
  purchases you already track). Excluded from budget totals.
- **Income** — paychecks, dividends, interest, refunds, and other money in.
- **Review** — a holding area for anything you want to revisit; kept visible and
  excluded from budget totals.
- **Reference** — informational, zero-dollar entries (e.g. $0 autopay confirmations)
  kept on record without affecting any totals.
- **Other Home Costs** — annual/one-off home expenses (contractor work, appliances).
  A reimbursement filed here (a negative amount) nets the cost down.

### How categorized data reaches the dashboard

Running `summary` regenerates the aggregates the **Budget vs Actual** view on the
Dashboard reads. So the flow is: `sync` your banks → categorize with
`cat`/`set` → run `summary` → open the Dashboard to compare actual spending against
your budget.

---

## Troubleshooting

**Results show "Calculating…" forever or an error** — the backend isn't reachable.
If you're running it yourself, make sure the server is up (see the Developer Guide).

**A console command says "plaid not configured"** — Plaid credentials aren't set in
the current environment. Bank sync needs them; the calculator and manual
categorization still work without.

**PDF export doesn't work** — it uses the browser's print dialog; allow pop-ups and
choose "Save as PDF".

**A rule categorized too much (or too little)** — use `rule ls` to see your rules,
`rule rm <pattern>` to remove one, and re-add a more specific pattern or add a
`@mask`/`$amount` scope. `undo` reverts the last change.
