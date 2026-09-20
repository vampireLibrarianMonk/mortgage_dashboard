"""Shared IMAP building blocks for mailbox providers.

Gmail (SSL on 993) and Proton Bridge (STARTTLS on 127.0.0.1:1143) both speak
IMAP, so the search-query construction, message parsing, and body extraction are
identical - only the connection setup, folder name, and credential source differ.
That common logic lives here so each provider stays small and there is one place
to fix IMAP parsing bugs.

Everything here is READ-ONLY: callers open folders with ``EXAMINE`` (readonly) and
only issue ``SEARCH``/``FETCH``.
"""

from __future__ import annotations

import datetime as dt
import email
import imaplib
from collections.abc import Iterable
from email.header import decode_header, make_header
from email.message import Message
from email.utils import parsedate_to_datetime

from . import RECEIPT_SENDERS, MailboxProvider, ReceiptEmail, SearchCriteria, sender_for

# --------------------------------------------------------------------------- #
# Query construction
# --------------------------------------------------------------------------- #


def all_from_terms() -> list[str]:
    """One FROM term per allowlisted sender - explicit addresses when known, else
    the domain (IMAP FROM is a substring match, so a domain works too)."""
    terms: list[str] = []
    for s in RECEIPT_SENDERS:
        if s.addresses:
            terms.extend(s.addresses)
        else:
            terms.extend(s.domains)
    return terms


def date_terms(since: dt.date | None, until: dt.date | None) -> list[str]:
    terms: list[str] = []
    if since:
        terms += ["SINCE", since.strftime("%d-%b-%Y")]
    if until:
        terms += ["BEFORE", until.strftime("%d-%b-%Y")]
    return terms


def imap_str(value: str) -> str:
    """IMAP quoted string for a search argument (drops embedded quotes)."""
    return '"' + value.replace('"', "") + '"'


# --------------------------------------------------------------------------- #
# Message parsing
# --------------------------------------------------------------------------- #


def decode_hdr(raw: str) -> str:
    try:
        return str(make_header(decode_header(raw)))
    except Exception:
        return raw


def msg_date(msg: Message) -> dt.date | None:
    raw = msg.get("Date")
    if not raw:
        return None
    try:
        return parsedate_to_datetime(raw).date()
    except Exception:
        return None


def extract_bodies(msg: Message) -> tuple[str, str]:
    """Return (text_plain, text_html), walking multipart and skipping attachments."""
    text_parts: list[str] = []
    html_parts: list[str] = []
    if msg.is_multipart():
        for part in msg.walk():
            if part.is_multipart():
                continue
            disp = str(part.get("Content-Disposition") or "")
            if "attachment" in disp.lower():
                continue
            ctype = part.get_content_type()
            if ctype == "text/plain":
                text_parts.append(_part_text(part))
            elif ctype == "text/html":
                html_parts.append(_part_text(part))
    else:
        if msg.get_content_type() == "text/html":
            html_parts.append(_part_text(msg))
        else:
            text_parts.append(_part_text(msg))
    return "\n".join(text_parts).strip(), "\n".join(html_parts).strip()


def _part_text(part: Message) -> str:
    try:
        payload = part.get_payload(decode=True)
        if payload is None:
            return ""
        charset = part.get_content_charset() or "utf-8"
        return payload.decode(charset, errors="replace")
    except Exception:
        return ""


# --------------------------------------------------------------------------- #
# Shared read-only IMAP session
# --------------------------------------------------------------------------- #


class ImapProviderBase(MailboxProvider):
    """Common read-only IMAP session: search + fetch + parse.

    Subclasses implement :meth:`_open` (return a logged-in ``imaplib`` client with
    the target folder EXAMINE'd read-only) and set ``name``/``label``. Everything
    else - query building, fetch, receipt normalization - is inherited.
    """

    def __init__(self) -> None:
        self._imap: imaplib.IMAP4 | None = None

    # subclasses provide the connection + read-only folder selection
    def _open(self) -> imaplib.IMAP4:
        raise NotImplementedError

    def connect(self) -> None:
        self._imap = self._open()

    def close(self) -> None:
        if self._imap is not None:
            for step in ("close", "logout"):
                try:
                    getattr(self._imap, step)()
                except Exception:
                    pass
            self._imap = None

    def search(self, criteria: SearchCriteria) -> list[str]:
        if self._imap is None:
            raise RuntimeError("not connected")
        senders = criteria.senders or all_from_terms()
        dts = date_terms(criteria.since, criteria.until)
        uids: list[str] = []
        seen: set[str] = set()
        for frm in senders:
            typ, data = self._imap.uid("SEARCH", None, "FROM", imap_str(frm), *dts)
            if typ != "OK" or not data or not data[0]:
                continue
            for uid in data[0].split():
                u = uid.decode()
                if u not in seen:
                    seen.add(u)
                    uids.append(u)
        uids.sort(key=int, reverse=True)
        return uids[: criteria.limit]

    def fetch(self, message_ids: Iterable[str]) -> list[ReceiptEmail]:
        if self._imap is None:
            raise RuntimeError("not connected")
        out: list[ReceiptEmail] = []
        for uid in message_ids:
            typ, data = self._imap.uid("FETCH", uid, "(RFC822)")
            if typ != "OK" or not data or not isinstance(data[0], tuple):
                continue
            msg = email.message_from_bytes(data[0][1])
            out.append(self._to_receipt(uid, msg))
        return out

    def fetch_raw(self, uid: str) -> bytes | None:
        """Return the raw RFC822 bytes for one uid (for saving .eml samples)."""
        if self._imap is None:
            raise RuntimeError("not connected")
        typ, data = self._imap.uid("FETCH", uid, "(RFC822)")
        if typ != "OK" or not data or not isinstance(data[0], tuple):
            return None
        return data[0][1]

    def _to_receipt(self, uid: str, msg: Message) -> ReceiptEmail:
        sender = decode_hdr(msg.get("From", ""))
        text, html = extract_bodies(msg)
        matched = sender_for(sender)
        return ReceiptEmail(
            message_id=msg.get("Message-ID", uid) or uid,
            provider=self.name,
            date=msg_date(msg),
            sender=sender,
            subject=decode_hdr(msg.get("Subject", "")),
            body_text=text,
            body_html=html,
            vendor=matched.vendor if matched else None,
            uid=uid,
        )
