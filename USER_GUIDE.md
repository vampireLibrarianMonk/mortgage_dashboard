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

The **Console** tab is an in-browser command line for pulling bank transactions and
categorizing them. Categorization is entirely user-driven — you decide what each
merchant means, and the app remembers your rules and re-applies them on every sync.

### How the console works

- There's a scrollback area (what's been typed and printed) and a prompt at the
  bottom. Type a command, press **Enter**, and the output prints below it.
- **Up/Down arrows** recall previous commands, like a normal shell.
- **`clear`** (or `cls`) wipes the scrollback; it doesn't touch your data.
- Commands and arguments are case-insensitive for keywords, but category names and
  match text are used as you type them. Quote nothing — everything after the command
  word is treated as the argument text.
- Every change is reversible with **`undo`** (one step), and rules can be listed and
  removed, so it's safe to experiment.

A typical working rhythm: **`sync`** to pull transactions → **`merchants`** to see
what's uncategorized → **`cat`/`set`** to categorize → **`summary`** to push the
totals to the dashboard.

---

### Command reference

Each command is shown with its syntax, what it does, and a worked example including
the kind of output the console prints back. Optional arguments are in `[brackets]`.

---

#### `help`

```
help
```

Prints the full command list and all valid category names. Use it as a quick
reminder of syntax and the categories you can assign.

---

#### `status`

```
status
```

Shows whether Plaid is configured, which banks are connected, how many transactions
are stored, how many are still uncategorized, and how many rules exist.

```
$ status
plaid configured: True
banks: XXXX, XXXX
transactions: 390 total, 12 uncategorized
rules: 41
```

---

#### `sync`

```
sync
```

Pulls new transactions from every linked bank and files them into the store. New
transactions that match an existing rule are categorized automatically on arrival;
the rest land as `Uncategorized`. Repeat syncs only fetch what's new.

```
$ sync
xxxx: fetched 190
xxxx: fetched 200
added 8 new, 382 already known.
12 uncategorized - use `list` then `cat <merchant> <Category>`.
```

If Plaid isn't configured, it prints
`plaid not configured (PLAID_CLIENT_ID/SECRET missing).` and does nothing.

---

#### `list`

```
list [uncategorized | <Category>]
```

Lists transactions, largest amount first. With no argument it lists the
**uncategorized** ones (your work queue). Give a category name to list what's in that
bucket instead.

```
$ list uncategorized
12 uncategorized transaction(s) (top 12 by amount):
  2026-09-14       $572.35  Lowe's Home Improvement
  2026-09-09       $214.34  DOMINION ENERGY BILLPAY
  2026-07-25         $5.00  XXXXX XXXXXX Colonial BeacVA

$ list Vehicle
5 Vehicle transaction(s) (top 5 by amount):
  2026-07-19        $38.78  Costco Gas
  2026-07-27        $32.86  Costco Gas
```

A transaction with a note shows it in angle brackets after the name, e.g.
`  2026-07-23       $246.99  FCWA PAYMENT  <Fairfax Water (FCWA)>`.

---

#### `merchants`

```
merchants [uncategorized]
```

Groups transactions by merchant with a count and running total per merchant, sorted
by dollar impact. This is the best triage view — it shows you where the money is so
you can knock out the biggest items first. Add `uncategorized` to see only merchants
that still need categorizing.

```
$ merchants uncategorized
3 merchant(s) (uncategorized):
    3x    $1,714.02  [Uncategorized]  Lowe's Home Improvement
    1x      $214.34  [Uncategorized]  DOMINION ENERGY BILLPAY
    1x        $5.00  [Uncategorized]  XXXXX XXXXXX Colonial BeacVA
```

Each row is `<count>x <total>  [<current category>]  <merchant>`.

---

#### `cat` — categorize and create a rule

```
cat <merchant text> <Category> [@mask]
```

Categorizes **every** transaction whose description contains `<merchant text>`
(case-insensitive) and **creates a rule** so future matching transactions are
categorized automatically on later syncs. Use it for anything recurring.

- `<merchant text>` can be several words; everything between the command and the
  category name is the match text.
- `<Category>` must be one of the valid categories (can itself be multiple words,
  e.g. `Home Improvement`).
- `@mask` (optional) scopes the rule to one account by its last-4 digits.

```
$ cat Costco Household
rule 'costco' -> Household; categorized 15 transaction(s).

$ cat Netflix Discretionary
rule 'netflix' -> Discretionary; categorized 3 transaction(s).

$ cat FUNDS TRANSFER Ignore @XXXX
rule 'funds transfer' on account XXXX -> Ignore; categorized 11 transaction(s).
```

---

#### `set` — one-off categorize, no rule

```
set <match text> <Category> [@mask] [$amount]
```

Categorizes the transactions matching **right now** but creates **no rule**, so
nothing is auto-applied on future syncs. Use it for generic descriptions or one-time
events you don't want a standing rule for.

- `@mask` scopes to one account (last-4).
- `$amount` restricts to an exact amount — useful when a generic description would
  otherwise match too much.

```
$ set Transfer to Checking Utilities @XXXX $70.04
set 1 transaction(s) matching 'transfer to checking' (account XXXX, amount 70.04) -> Utilities (no rule created).
```

---

#### `label` — attach a note

```
label <match text> = <label> [@mask] [$amount]
```

Attaches a human-readable note to matching transactions. Labels are informational
only — they don't change the category or any totals; they just help you remember what
something was. An empty label (`label <match text> =`) removes an existing note.

```
$ label FCWA = Fairfax Water (FCWA)
labeled 1 transaction(s) as 'Fairfax Water (FCWA)'.

$ label Paid Check = AUMC daycare $318.00
labeled 1 transaction(s) as 'AUMC daycare'.
```

---

#### `rule` — manage rules

```
rule ls
rule rm <pattern>
```

`rule ls` lists every merchant rule (pattern, optional account scope, and target
category). `rule rm <pattern>` removes the rule with that exact pattern; any
transactions it had categorized are re-evaluated against the remaining rules, falling
back to `Uncategorized` if nothing else matches.

```
$ rule ls
  costco -> Household
  costco gas -> Vehicle
  funds transfer @XXXX -> Ignore
  netflix -> Discretionary

$ rule rm netflix
removed.
```

---

#### `summary` — totals and refresh the dashboard

```
summary [year]
```

Prints per-category totals and **regenerates the aggregates the Budget vs Actual view
on the Dashboard reads**. Run it after a round of categorizing to push your numbers
to the dashboard. Give a year to scope the totals.

```
$ summary
per-category totals (also refreshed Budget vs Actual):
  2026:
    Mortgage       $17,843.55
    Household      $10,354.27
    Utilities      $621.47
    Vehicle        $153.77
    ChildCare      $1,255.00
    (unbudgeted)   $2,954.35
```

---

#### `undo` — revert the last change

```
undo
```

Reverts the most recent change (a `cat`, `set`, `label`, `rule rm`, or `sync`). One
step of history.

```
$ undo
reverted last change.
```

---

#### `plaid` — diagnostics

```
plaid [status | items | balances [slug] | link]
```

Read-only Plaid diagnostics. `status` shows config and connected banks; `items` lists
each linked bank with its token/cursor state; `balances [slug]` shows current account
balances (all banks, or one by its slug); `link` mints a link token to confirm the
Plaid auth path is reachable.

```
$ plaid status
configured: True
environment: production
connected banks: XXXX, XXXX

$ plaid balances
xxxx (XXXX):
  XXXX Checking                  [checking]           $3,008.29
  XXXX Savings                   [money market]      $53,579.17
xxxx (XXXX):
  XXXX Checking                  [checking]             $229.26
```

---

### `cat` vs `set` — which to use

- **`cat`** creates a **rule**: it categorizes everything matching now *and* keeps
  categorizing new matching transactions on every future sync. Use it for recurring
  merchants (Costco, Netflix, your utilities, your mortgage).
- **`set`** is a **one-off**: it categorizes the transactions matching right now and
  creates **no rule**. Use it for a generic description or a one-time event you don't
  want a standing rule for (e.g. a specific `Transfer to Checking` that was actually a
  one-time bill).

### Scoping matches (`@mask` and `$amount`)

Both `cat` and `set` accept optional narrowing so a rule touches exactly what you
mean:

- **`@mask`** — restrict to one account by its last-4 digits, e.g. `@0000`. An
  account-scoped rule always wins over a plain text rule for the same merchant.
- **`$amount`** — restrict to an exact amount, e.g. `$70.04`.

More specific rules win over broader ones. For example, a `costco gas` rule sends fuel
to Vehicle while a plain `costco` rule sends warehouse purchases to Household — the
longer, more specific pattern takes precedence for the transactions it matches.

### A full example session

```
$ sync
xxxx: fetched 190
xxxx: fetched 200
added 5 new, 385 already known.
5 uncategorized - use `list` then `cat <merchant> <Category>`.

$ merchants uncategorized
3 merchant(s) (uncategorized):
    3x    $1,714.02  [Uncategorized]  Lowe's Home Improvement
    1x      $214.34  [Uncategorized]  DOMINION ENERGY BILLPAY
    1x        $5.00  [Uncategorized]  XXXXX XXXXXX Colonial BeacVA

$ cat Lowe's Home Improvement
rule 'lowe's' -> Home Improvement; categorized 3 transaction(s).

$ cat Dominion Energy Utilities
rule 'dominion energy' -> Utilities; categorized 1 transaction(s).

$ set Lucas Valdez Discretionary $5.00
set 1 transaction(s) matching 'lucas valdez' (amount 5.0) -> Discretionary (no rule created).

$ summary
per-category totals (also refreshed Budget vs Actual):
  2026:
    Utilities      $214.34
    Discretionary  $5.00
    Home Improvement $1,714.02

$ status
plaid configured: True
banks: XXXX, XXXX
transactions: 390 total, 0 uncategorized
rules: 43
```

Then open the **Dashboard → Budget vs Actual** to see the categorized spend compared
against your budget.

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
