"""Modular, provider-pluggable email-ingest subsystem.

Purpose
-------
Purchase receipts and order-confirmation emails are the most reliable source of
*itemized* spend detail (line items + amounts), which neither bank feeds nor the
PayPal statement PDFs contain. This package connects to a mailbox READ-ONLY,
pulls only receipt/order emails from a fixed allowlist of senders, and hands them
to vendor receipt parsers. The parsed line items ultimately feed the transaction
"split" primitive so a single payment (e.g. one Walmart order) can be broken into
per-item categories.

Design principles
-----------------
* **Provider-pluggable.** Gmail, Proton, and any future mailbox are subclasses of
  :class:`MailboxProvider` registered in a small registry - the same pattern the
  ``importers`` package uses for statement readers. Adding a provider means one
  new module; nothing else changes.
* **Read-only.** Providers only ever search and fetch. Nothing in this package
  deletes, sends, moves, or marks mail.
* **Sender-scoped.** We never scan the whole mailbox. Fetches are constrained to
  the receipt-sender allowlist (:data:`RECEIPT_SENDERS`), so only order/receipt
  mail is ever read.
* **Local + private.** Parsing is local, deterministic code. Email bodies are not
  sent to any third-party service. Credentials live in the Windows Credential
  Manager (via ``credential_store``), never in ``.env`` or git.
* **Standalone first.** Phase 1 develops and proves this subsystem through a CLI
  harness, decoupled from the app. It is intentionally NOT wired into the app's
  console/GUI until it is solid.

Nothing here is imported by the running app yet - this package stands alone.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Iterable

# --------------------------------------------------------------------------- #
# Shared config
# --------------------------------------------------------------------------- #

# Credential Manager target prefix for this subsystem. Each provider stores its
# own secret(s) under "<prefix>_<provider>[_<field>]" so nothing collides with
# the Plaid credentials already in the store.
CRED_PREFIX = "mortgage_dashboard_mail"


@dataclass(frozen=True)
class ReceiptSender:
    """A known receipt/order-email sender we are allowed to fetch from.

    `vendor` is the normalized vendor key the receipt maps to (matching the
    importers vendor registry we will build). `domains` and `addresses` are the
    From-header signals used to recognize the sender. `note` documents intent
    (e.g. distinguishing Apple Services subscriptions from Apple Pay purchases).

    A vendor's transactional mail is a mix of message types: the *order
    confirmation* (which carries the itemized line items + total we want) plus
    shipping/tracking/delivery notices and login codes (noise for itemization).
    `order_subject_hints` are lowercase substrings that identify the confirmation;
    `noise_subject_hints` identify mail to ignore even if it matches a hint.
    """

    vendor: str
    domains: tuple[str, ...] = ()
    addresses: tuple[str, ...] = ()
    note: str = ""
    order_subject_hints: tuple[str, ...] = ()
    noise_subject_hints: tuple[str, ...] = ()

    def matches_from(self, from_header: str) -> bool:
        low = (from_header or "").lower()
        if any(addr.lower() in low for addr in self.addresses):
            return True
        return any(f"@{d.lower()}" in low or f".{d.lower()}" in low for d in self.domains)

    def is_order_confirmation(self, subject: str) -> bool:
        """True if the subject looks like an itemized order confirmation.

        Noise hints win over order hints. If no order hints are configured for a
        vendor yet, returns False (we can't tell) rather than guessing.
        """
        low = (subject or "").lower()
        if any(n in low for n in self.noise_subject_hints):
            return False
        return any(h in low for h in self.order_subject_hints)


# The allowlist of receipt senders. Deliberately narrow: only order/receipt mail
# from the vendors the user itemizes. Extend as new vendors are added.
RECEIPT_SENDERS: tuple[ReceiptSender, ...] = (
    ReceiptSender(
        vendor="amazon",
        domains=("amazon.com",),
        addresses=("auto-confirm@amazon.com", "order-update@amazon.com",
                   "shipment-tracking@amazon.com"),
        note="Amazon order confirmations / shipment emails carry line items.",
    ),
    ReceiptSender(
        vendor="walmart",
        domains=("walmart.com",),
        addresses=("help@walmart.com",),
        note="Walmart transactional mail. The 'Thanks for your delivery order' "
             "message is the itemized confirmation; Shipped/Arrived/Delivered are "
             "tracking notices, and verification codes are login noise.",
        order_subject_hints=("thanks for your delivery order",
                             "thanks for your order",
                             "your order is confirmed"),
        noise_subject_hints=("shipped:", "arrived:", "delivered:", "should arrive",
                             "verification code", "package"),
    ),
    ReceiptSender(
        vendor="target",
        domains=("target.com", "targetnews.com", "em.target.com"),
        addresses=("orders@target.com",),
        note="Target order confirmations.",
    ),
    ReceiptSender(
        vendor="apple",
        domains=("apple.com", "email.apple.com"),
        addresses=("no_reply@email.apple.com",),
        note="Apple receipts. NOTE: Apple *Services* subs (single-category) vs "
             "Apple *Pay* purchases (a funding rail - real merchant is elsewhere).",
    ),
)


def sender_for(from_header: str) -> ReceiptSender | None:
    """Return the allowlisted sender matching a From header, or None."""
    for s in RECEIPT_SENDERS:
        if s.matches_from(from_header):
            return s
    return None


def is_order_confirmation(receipt: "ReceiptEmail") -> bool:
    """True if a fetched receipt is an itemized order confirmation (vs tracking/
    login noise), based on its vendor's subject hints."""
    for s in RECEIPT_SENDERS:
        if s.vendor == receipt.vendor:
            return s.is_order_confirmation(receipt.subject)
    return False


def all_sender_addresses() -> list[str]:
    """Flatten every allowlisted address/domain for building server-side queries."""
    out: list[str] = []
    for s in RECEIPT_SENDERS:
        out.extend(s.addresses)
        out.extend(s.domains)
    return out


# --------------------------------------------------------------------------- #
# Normalized receipt email
# --------------------------------------------------------------------------- #


@dataclass
class ReceiptEmail:
    """A fetched receipt/order email, normalized across providers.

    This is what a provider yields and what a vendor receipt parser consumes.
    Bodies are kept as text and/or HTML; the parser decides which it needs. We
    keep `message_id` so a receipt can be de-duplicated across fetches, and
    `provider`/`vendor` for routing and reporting.
    """

    message_id: str
    provider: str
    date: dt.date | None
    sender: str  # raw From header
    subject: str
    body_text: str = ""
    body_html: str = ""
    vendor: str | None = None  # resolved from the allowlist when known
    uid: str = ""  # provider-native IMAP uid (for addressing a specific message)

    @property
    def best_body(self) -> str:
        """Prefer text; fall back to HTML when only HTML is present."""
        return self.body_text or self.body_html


# --------------------------------------------------------------------------- #
# Provider interface
# --------------------------------------------------------------------------- #


@dataclass
class SearchCriteria:
    """Constraints for a receipt search. Providers translate these into whatever
    query language they speak (Gmail search, IMAP SEARCH, ...)."""

    since: dt.date | None = None
    until: dt.date | None = None
    senders: tuple[str, ...] = ()  # empty -> use the full allowlist
    limit: int = 100


class MailboxProvider:
    """Base class for a read-only mailbox provider.

    Lifecycle: ``connect()`` establishes a read-only session, ``search()`` finds
    receipt messages matching criteria (returning lightweight ids), ``fetch()``
    materializes selected ids into :class:`ReceiptEmail` objects, ``close()``
    tears down. Providers MUST NOT mutate the mailbox in any way.
    """

    #: Short stable identifier, also written to each ReceiptEmail.provider.
    name: str = "base"
    #: Human-friendly label for the CLI/UX.
    label: str = "Mailbox"

    def connect(self) -> None:
        """Open a read-only session. Raise on auth/connection failure."""
        raise NotImplementedError

    def search(self, criteria: SearchCriteria) -> list[str]:
        """Return provider-native message ids for receipts matching criteria."""
        raise NotImplementedError

    def fetch(self, message_ids: Iterable[str]) -> list[ReceiptEmail]:
        """Materialize message ids into normalized ReceiptEmail objects."""
        raise NotImplementedError

    def close(self) -> None:
        """Close the session. Safe to call multiple times."""
        return None


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #

_PROVIDERS: dict[str, type[MailboxProvider]] = {}


def register_provider(cls: type[MailboxProvider]) -> type[MailboxProvider]:
    """Register a provider class by its `name`. Usable as a decorator."""
    _PROVIDERS[cls.name] = cls
    return cls


def registered_providers() -> list[str]:
    """Names of all registered providers."""
    return sorted(_PROVIDERS)


def get_provider(name: str) -> MailboxProvider:
    """Instantiate a registered provider by name."""
    try:
        cls = _PROVIDERS[name]
    except KeyError:
        raise KeyError(f"no mailbox provider '{name}'. registered: {registered_providers()}")
    return cls()


# Register built-in providers. Imported at the bottom to avoid circular imports:
# provider modules import MailboxProvider/creds from this package.
from . import gmail as _gmail  # noqa: E402,F401  (registers GmailImapProvider)
from . import proton as _proton  # noqa: E402,F401  (registers ProtonBridgeProvider)
