# Developer Guide — Mailbox (Email Receipt Ingest)

Living design + troubleshooting doc for the **mailbox subsystem**: the modular,
provider-pluggable email-ingest layer that pulls purchase-receipt / order emails
(read-only) so a single payment can be itemized and split into per-item budget
categories.

> **Status: Phase 1 — standalone.** The subsystem is being developed and proven
> through a CLI harness *before* it is wired into the app's console/GUI. Nothing
> in `mailbox/` is imported by the running FastAPI app yet.

This file is updated as we hit and fix real issues. See the
[Troubleshooting log](#troubleshooting-log) at the bottom.

---

## Why this exists

Bank feeds and PayPal statement PDFs only give a payment **total** and a merchant.
A single Walmart/Amazon/Target order is really a basket that can cross budget
categories (groceries + a phone case + motor oil). The itemized detail lives in
the **order-confirmation / receipt emails** already sitting in the user's inbox.

So the plan is: connect to the mailbox **read-only**, pull only receipt mail from
a fixed sender allowlist, parse it **locally** into line items, and feed those
into a transaction **split** primitive (parent payment becomes an excluded
container; categorized children carry the money and sum to the parent).

PayPal and Apple Pay are **funding rails**, not merchants — the real merchant is
downstream (Target, etc.). The email receipt is what reveals that real merchant.

---

## Design principles (locked)

- **Read-only.** Providers only `SEARCH`/`FETCH`. Folders are opened with IMAP
  `EXAMINE` (readonly). Nothing deletes, moves, flags, or sends mail.
- **Sender-scoped.** We never scan the whole mailbox — searches are constrained
  to the receipt-sender allowlist (`RECEIPT_SENDERS`).
- **Local + private.** Parsing is local, deterministic Python. Email bodies are
  never sent to any third-party service. Credentials live in the Windows
  Credential Manager, never in `.env` or git.
- **Provider-pluggable.** Gmail, Proton, and future mailboxes are `MailboxProvider`
  subclasses in a registry (same pattern as the `importers` package). Adding a
  provider = one module.
- **Standalone first.** Prove it via the CLI harness, then integrate.

---

## Package layout

```
backend/mailbox/
├── __init__.py       # skeleton: config, allowlist, models, provider interface, registry
├── creds.py          # encrypted credential storage (wraps credential_store / Credential Manager)
├── _imapbase.py      # shared read-only IMAP logic (search/fetch/parse) reused by providers
├── gmail.py          # Gmail provider(s) (IMAP + app password) - gmail + gmail2
├── proton.py         # Proton provider (Proton Mail Bridge, localhost IMAP)
├── cli.py            # standalone dev harness: python -m mailbox.cli ...
└── _samples/         # (gitignored) dumped .eml samples for parser development
```

### Core building blocks (`__init__.py`)

- **`RECEIPT_SENDERS`** — the allowlist. Each `ReceiptSender(vendor, domains,
  addresses, note)` maps From-header signals to a normalized vendor key.
  Currently: `amazon`, `walmart`, `target`, `apple`.
- **`sender_for(from_header)`** — resolve a From header to an allowlisted sender.
- **`ReceiptEmail`** — normalized fetched email (`message_id`, `provider`, `date`,
  `sender`, `subject`, `body_text`, `body_html`, `vendor`; `best_body` prefers text).
- **`SearchCriteria`** — `since` / `until` / `senders` / `limit`.
- **`MailboxProvider`** — interface: `connect()`, `search(criteria) -> [uid]`,
  `fetch(uids) -> [ReceiptEmail]`, `close()`. Read-only.
- **Registry** — `register_provider`, `registered_providers()`, `get_provider(name)`.

### Shared IMAP base (`_imapbase.py`)

Gmail (SSL:993) and Proton Bridge (STARTTLS:1143) both speak IMAP, so the search
query construction, message parsing, and body extraction are shared here.
`ImapProviderBase` implements `connect/close/search/fetch/fetch_raw/_to_receipt`;
each provider only implements `_open()` (connect + login + `EXAMINE` a folder
read-only).

### Credentials (`creds.py`)

Wraps `credential_store` (native Windows Credential Manager via ctypes — the same
store Plaid tokens and the Fernet key use). Targets are namespaced
`mortgage_dashboard_mail_<provider>_<field>`. Secrets are JSON blobs. **Never**
written to `.env`, files, or git.

---

## CLI harness

Run from `backend/` with the venv active:

```
.\venv\Scripts\python.exe -m mailbox.cli <command>
```

| Command | What it does |
|---------|--------------|
| `providers` | list registered providers |
| `status` | show which providers have stored credentials |
| `setup <provider>` | store credentials (secure `getpass` prompt; nothing echoed) |
| `clear <provider>` | delete stored credentials |
| `test <provider>` | connect read-only + disconnect (proves auth + read-only) |
| `search <provider> [--since --until --limit --vendor --orders-only]` | list matching receipt emails; `--orders-only` keeps just itemized confirmations |
| `dump <provider> [--vendor --limit --orders-only] [--uid U ...]` | save raw `.eml` samples to `_samples/` for parser dev |

The `search` output tags each message `ORDER` (an itemized order confirmation) or
blank (tracking/login noise), and shows the IMAP `uid` you can pass to `dump --uid`.

### Message-type filtering

A vendor's transactional mail is a mix: the itemized **order confirmation** plus
Shipped/Arrived/Delivered tracking notices and login verification codes. Only the
confirmation carries line items + a total. Each `ReceiptSender` therefore has
`order_subject_hints` (identify the confirmation) and `noise_subject_hints`
(exclude tracking/login even if a hint matches). `is_order_confirmation(receipt)`
applies them; `--orders-only` filters `search`/`dump` down to confirmations.

Typical first run:

```
python -m mailbox.cli setup gmail
python -m mailbox.cli test gmail
python -m mailbox.cli search gmail --since 2026-06-18
python -m mailbox.cli dump gmail --vendor walmart --limit 1
```

---

## Provider setup

### Gmail (IMAP + app password)

- **IMAP is always on** for personal Gmail (Google removed the enable/disable
  toggle in January 2025). There is no setting to flip.
- Auth requires a **16-char app password**, *not* your account password and *not*
  a passkey. App passwords require **2-Step Verification** to be enabled.
- Generate at **`myaccount.google.com/apppasswords`** (go there directly — the
  link is often hidden from the Security menu in the new UI). Name it e.g.
  `mortgage dashboard`. Paste the 16 chars into `setup gmail` (spaces are fine;
  they are stripped).
- Stored encrypted as JSON `{address, app_password}` under
  `mortgage_dashboard_mail_gmail_imap`.

#### A second Gmail account (`gmail2`)

Multiple Gmail mailboxes are supported as separate providers that share identical
IMAP logic but distinct credential slots, so both can be configured and queried
side by side (no swapping/overwriting):

```
python -m mailbox.cli setup gmail2     # store the 2nd account's app password
python -m mailbox.cli status           # shows gmail + gmail2 separately
python -m mailbox.cli test gmail2
python -m mailbox.cli search gmail2 --orders-only --since 2026-07-01
```

`gmail2` stores its secret under `mortgage_dashboard_mail_gmail2_imap`, fully
isolated from `gmail`. Both are subclasses of the same `_GmailImapProviderBase`;
adding a third account is one more `@register_provider` subclass with a new
`name`. The credential helpers in `gmail.py` take a `provider=` argument
(defaulting to `"gmail"` for back-compat).

### Proton (Proton Mail Bridge)

- Proton has **no public mail API**. The only supported programmatic access is
  **Proton Mail Bridge**, a desktop app that decrypts the mailbox and re-serves it
  as IMAP on localhost. Bridge must be installed and **running**.
- Connection: `127.0.0.1:1143`, **STARTTLS** (not SSL-on-connect), self-signed
  cert on loopback (TLS verification relaxed for localhost only).
- Password is the **Bridge-generated** password from the Bridge app, *not* the
  Proton account password.
- Stored encrypted as JSON `{address, password, host, port}` under
  `mortgage_dashboard_mail_proton_bridge`.

---

## Auth decision matrix (Gmail)

| Account type | App password works? | Path |
|--------------|--------------------|------|
| Personal `@gmail.com` | Yes (with 2FA on) | IMAP + app password (current) |
| 2FA = security keys / passkeys only | App-password option hidden | Add a phone/authenticator factor, then it appears |
| Google Workspace (managed / custom domain) | **No** — disabled since May 1, 2025 | Would require an OAuth provider (not yet built) |

The registry design means an OAuth-based Gmail provider can be added later as a
second provider without disturbing the IMAP one.

---

## Security notes

- Credentials: Windows Credential Manager only. Verify with
  `python -m mailbox.cli status`. Remove with `clear <provider>`.
- Dumped `.eml` samples in `_samples/` contain real email content and are
  **gitignored** (`backend/mailbox/_samples/`). Do not commit them.
- Read-only is enforced at the protocol level (`EXAMINE`), not by convention.
- Proton Bridge TLS verification is disabled **only** for the loopback connection
  (self-signed cert); this is not a remote connection.

---

## Roadmap / open items

- [ ] Live-verify Gmail `test` + `search` against the real inbox (in progress).
- [ ] Confirm the sender allowlist matches the user's real receipt senders
      (Amazon/Walmart/Target/Apple sometimes send from addresses not yet listed).
- [ ] Proton: confirm the user runs Bridge; live-verify.
- [ ] Per-vendor receipt parsers (need a real sample `.eml` per vendor).
- [ ] The **split primitive** (parent `Split` category excluded from actuals;
      `split_children` summing to the parent; split-aware `export_actuals`) — the
      still-unbuilt foundation the parsed line items feed into.
- [ ] App integration (console + GUI) — only after Phase 1 is proven.

---

## Troubleshooting log

Running record of real issues and fixes. Add to this as we go.

| Date | Symptom | Cause | Fix |
|------|---------|-------|-----|
| 2026-09 | "Enable IMAP" setting not found in Gmail | Google removed the IMAP toggle (Jan 2025); IMAP is always on for personal Gmail | Nothing to enable — the issue is always authentication, not the setting |
| 2026-09 | Confusion: is the credential a passkey? | App password ≠ passkey. Passkeys are for interactive browser login; IMAP can't use them | Use an **app password** (16 chars), which requires 2FA |
| 2026-09 | App passwords option not visible in Security menu | New Google UI hides the link; also hidden if 2FA is keys-only | Go directly to `myaccount.google.com/apppasswords`; account had phone + prompt factors so it was available |
| 2026-09 | First `search gmail` returned 10 Walmart mails, but most were Shipped/Arrived/Delivered/verification-code noise, not order confirmations | Sender allowlist matched Walmart's whole transactional stream | Added `order_subject_hints` / `noise_subject_hints` to `ReceiptSender` + `is_order_confirmation()` + `--orders-only`. Walmart order = "Thanks for your delivery order". 3 of 10 are real orders |
| 2026-09 | CLI `uid` column showed a chunk of the sender domain, not a usable id | `_uid_of` sliced the RFC Message-ID; IMAP uid wasn't preserved on `ReceiptEmail` | Added `uid` field to `ReceiptEmail`, threaded the IMAP uid through `_to_receipt`; CLI now prints the real uid |
| 2026-09 | Only Walmart appeared (no Amazon/Target/Apple) in the 6/18+ window | Either no purchases from them, or their receipts come from un-allowlisted senders | Walmart is the heaviest vendor -> build its parser first; confirm other vendors' senders later |
| 2026-09 | **Walmart confirmation email has NO per-item prices** | Walmart's "Thanks for your delivery order" email is a *summary*: it carries the order total (printed twice), order date, order number (`#2000000-...`), and item count only. Item names/prices live behind the "See all" link on walmart.com, not in the email. Verified across 3 samples (4-item $78.82, 1-item $13.48). | Email is a strong **match/label** signal (total + order#), not a full itemizer. Single-item orders auto-categorize from the email; multi-item orders need per-item amounts supplied by the user (paste breakdown) and the split primitive. Do NOT scrape walmart.com (auth/ToS). |

### Vendor itemization capability (what each email source can/can't give)

| Vendor | Email carries | Per-item prices? | Itemization strategy |
|--------|---------------|------------------|----------------------|
| Walmart | total, order#, date, item **count**, first item name (truncated) | ❌ No | Auto-categorize single-item orders; user supplies breakdown for multi-item + split primitive |
| Amazon | TBD (no sample yet) | TBD | Amazon confirmations historically DO list items + prices - confirm with a sample |
| Target | TBD | TBD | Confirm with a sample |
| Apple | subscription receipts (Services) | ✅ usually itemized | Single-category mostly |

Key realization: the email's real value is **reliable matching** (order total + order
number tie a payment to a specific order with confidence, better than fuzzy
amount+date) plus **labeling** (merchant + item names). The per-item *price*
breakdown for multi-item orders is not always in the email; that gap is filled by
the split primitive (user-supplied amounts) rather than by scraping the retailer.

#### Walmart email deep-dive (verified across all message types)

Checked confirmation, Shipped, Arrived, and Delivered emails for one 4-item order
(`#2000000-00000002`, $78.82):

- **No email type lists the order's per-item names+prices.** Confirmation has the
  total (twice), order#, date, item count. Shipped/Arrived/Delivered have order#,
  date, item count, and **seller name** (e.g. "LIRUA Living Store", "Ballucci"),
  but no `/ip/` product links, no item prices, thumbnail alt-text is just
  `preview-img`.
- **TRAP:** the Arrived email's "Recently viewed items" / "Explore more savings"
  block lists product names (TUSHY bidet, Chemical Guys kit, ...) that are
  **marketing recommendations, NOT the order's items**. Parsing them would
  mis-categorize entirely. Never treat that block as line items.
- The real itemized breakdown is only behind the authenticated
  `walmart.com/orders/<num>` page. We do **not** scrape it (requires the user's
  login session, against ToS, brittle).
- Useful signals to harvest: canonical **order number** (same across all emails,
  and in the "View order" link -> strong join key to the PayPal txn), order
  **date**, **total** (confirmation), **item count**, **seller name**.

#### Order-dossier approach (group emails by order number)

Instead of one-email-in-isolation, **group every email sharing an order number**
(confirmation + each shipment + each arrival + delivered) into one order record.
Verified on the 3 sample orders:

| Order # | Total (from confirmation) | Item names recovered | Count |
|---------|--------------------------|----------------------|-------|
| 200000000000002 | $78.82 | "Under Bed Storage, Bel…" (truncated) | 4 |
| 200000000000003 | $44.51 | "Ballucci 36\" Floating…" (truncated) | 1+ |
| 200000000000001 | $13.48 | "Goo Gone Latex Paint R…" | 1 |

$44.51 and $78.82 match the imported Walmart PayPal transactions exactly, so the
dossier reliably links **PayPal charge -> Walmart order -> total + partial item
name(s) + count + seller**. This is the real value: automatic detective work on an
opaque charge.

**Still-open limitations (email cannot overcome):**
1. Item names are **truncated** in subjects ("…"), full names not in the email.
2. **No per-item prices** in any email type.
3. Order-number extraction was **fragile** in the probe (4/10 emails returned no
   order#, incl. a Shipped email that had the number in an un-matched spot).
   A production dossier builder needs robust order-id extraction (handle `#NNNNNNN-
   NNNNNNNN`, bare `NNNNNNNNNNNNNNNNN`, and `/orders/<id>` links).

Conclusion: order-dossier grouping is the right structure for the mailbox side -
it maximizes what email can give (match + label). The per-item price split still
comes from the user via the split primitive.
