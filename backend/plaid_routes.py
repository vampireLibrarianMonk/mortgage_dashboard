"""Plaid integration endpoints (read-only: Transactions + Balances).

Flow:
  1. POST /plaid/link-token   -> link_token for the frontend to open Plaid Link
  2. POST /plaid/exchange     -> swap public_token for access_token; store it +
                                 an empty cursor in Credential Manager, keyed by
                                 a caller-provided slug (e.g. "chase")
  3. GET  /plaid/items        -> list connected banks (slug + display name)
  4. POST /plaid/sync         -> transactions/sync for one item using its cursor
  5. GET  /plaid/balances     -> current balances for one item

Secrets (access tokens, cursors) live only in Windows Credential Manager.
"""
from __future__ import annotations

import logging
import re

from fastapi import APIRouter, HTTPException
from plaid.model.accounts_balance_get_request import AccountsBalanceGetRequest
from plaid.model.country_code import CountryCode
from plaid.model.item_public_token_exchange_request import ItemPublicTokenExchangeRequest
from plaid.model.item_remove_request import ItemRemoveRequest
from plaid.model.link_token_create_request import LinkTokenCreateRequest
from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
from plaid.model.products import Products
from plaid.model.sandbox_public_token_create_request import SandboxPublicTokenCreateRequest
from plaid.model.transactions_sync_request import TransactionsSyncRequest
from pydantic import BaseModel

import credential_store as store
from plaid_client import PlaidConfigError, build_client, credentials_available, get_plaid_env

logger = logging.getLogger("plaid")
logging.basicConfig(level=logging.INFO)

router = APIRouter(prefix="/plaid", tags=["plaid"])


def _client():
    """Build the Plaid client or raise a clean 503 if not configured."""
    if not credentials_available():
        raise HTTPException(
            status_code=503,
            detail="Plaid is not configured. PLAID_CLIENT_ID / PLAID_SECRET are not set.",
        )
    try:
        return build_client()
    except PlaidConfigError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")
    return slug or "bank"


def _plaid_error_code(exc: Exception) -> str | None:
    """Best-effort extraction of Plaid's error_code from an ApiException.

    plaid-python raises ApiException with a JSON string in `.body`; the error
    code lives at top-level as `error_code`.
    """
    import json
    body = getattr(exc, "body", None)
    if not body:
        return None
    try:
        data = json.loads(body) if isinstance(body, str | bytes) else body
        return data.get("error_code")
    except (ValueError, AttributeError):
        return None


@router.get("/status")
def status():
    """Report whether Plaid is configured and which environment is active."""
    return {"configured": credentials_available(), "env": get_plaid_env()}


@router.get("/actuals")
def actuals():
    """Serve the aggregates-only budget-vs-actual data produced by the pipeline.

    Reads backend/plaid_actuals.json (per-month + yearly category totals only —
    no transactions, no balances). Returns an empty structure if the pipeline has
    not been run yet.
    """
    import json
    from pathlib import Path
    path = Path(__file__).resolve().parent / "plaid_actuals.json"
    if not path.exists():
        return {"available": False, "months": [], "years": []}
    data = json.loads(path.read_text())
    return {"available": True, **data}


class LinkTokenResponse(BaseModel):
    link_token: str


@router.post("/link-token", response_model=LinkTokenResponse)
def create_link_token():
    """Create a link_token for initializing Plaid Link in the browser.

    Read-only scope: we request Transactions only. Balances is available on any
    Item without a separate product, so it needs no extra scope here.
    """
    client = _client()
    req = LinkTokenCreateRequest(
        user=LinkTokenCreateRequestUser(client_user_id="mortgage-dashboard-user"),
        client_name="Mortgage Dashboard",
        products=[Products("transactions")],
        country_codes=[CountryCode("US")],
        language="en",
    )
    try:
        resp = client.link_token_create(req)
    except Exception as e:  # plaid.ApiException and friends
        logger.error("link_token_create failed (env=%s): %s", get_plaid_env(), e)
        raise HTTPException(status_code=502, detail="Plaid link_token_create failed; see server logs.") from e
    logger.info("link_token_create OK (env=%s, products=[transactions])", get_plaid_env())
    return LinkTokenResponse(link_token=resp["link_token"])


class ExchangeRequest(BaseModel):
    public_token: str
    name: str  # human-readable bank name, used to derive the storage slug


class ExchangeResponse(BaseModel):
    slug: str
    name: str


@router.post("/exchange", response_model=ExchangeResponse)
def exchange_public_token(body: ExchangeRequest):
    """Exchange a public_token for an access_token and persist it (by slug)."""
    client = _client()
    slug = _slugify(body.name)
    try:
        resp = client.item_public_token_exchange(
            ItemPublicTokenExchangeRequest(public_token=body.public_token)
        )
    except Exception as e:
        logger.error("token exchange failed (env=%s): %s", get_plaid_env(), e)
        raise HTTPException(status_code=502, detail="Plaid token exchange failed; see server logs.") from e

    access_token = resp["access_token"]
    store.save_item(slug, access_token)
    store.save_cursor(slug, "")  # empty cursor -> first sync pulls everything
    store.add_to_index(slug, body.name.strip())
    return ExchangeResponse(slug=slug, name=body.name.strip())


class SandboxLinkRequest(BaseModel):
    name: str  # display label for the test bank
    institution_id: str = "ins_109508"  # First Platypus Bank (standard sandbox test institution)


@router.post("/sandbox-link", response_model=ExchangeResponse)
def sandbox_quick_link(body: SandboxLinkRequest):
    """Sandbox-only: create a test item without the Link popup.

    Uses /sandbox/public_token/create to mint a public_token against a test
    institution, then runs the normal exchange + storage path. This bypasses the
    Link UI (and its phone/Layer flow) for fast local testing. Rejected outside
    the sandbox environment.
    """
    if get_plaid_env() != "sandbox":
        raise HTTPException(status_code=400, detail="sandbox-link is only available in the sandbox environment.")
    client = _client()
    slug = _slugify(body.name)
    try:
        pt_resp = client.sandbox_public_token_create(
            SandboxPublicTokenCreateRequest(
                institution_id=body.institution_id,
                initial_products=[Products("transactions")],
            )
        )
        exchange = client.item_public_token_exchange(
            ItemPublicTokenExchangeRequest(public_token=pt_resp["public_token"])
        )
    except Exception as e:
        logger.error("sandbox link failed (env=%s): %s", get_plaid_env(), e)
        raise HTTPException(status_code=502, detail="Plaid sandbox link failed; see server logs.") from e

    store.save_item(slug, exchange["access_token"])
    store.save_cursor(slug, "")
    store.add_to_index(slug, body.name.strip())
    return ExchangeResponse(slug=slug, name=body.name.strip())


@router.get("/items")
def list_items():
    """List connected banks (slug + display name). No secrets returned."""
    return store.list_items()


@router.delete("/items/{slug}")
def delete_item(slug: str):
    """Disconnect a bank: remove the Item at Plaid, then delete local secrets.

    Calling /item/remove ends Plaid's per-Item subscription billing and frees the
    item toward any plan cap. We attempt the Plaid removal first but still clear
    local secrets even if it fails (e.g. token already invalid), so the UI never
    gets stuck with an un-removable entry.
    """
    access_token = store.get_access_token(slug)
    plaid_removed = False
    plaid_error = None
    if access_token:
        try:
            client = _client()
            client.item_remove(ItemRemoveRequest(access_token=access_token))
            plaid_removed = True
        except Exception as e:
            plaid_error = str(e)

    store.delete_item(slug)
    return {"ok": True, "plaid_removed": plaid_removed, "plaid_error": plaid_error}


class SyncRequest(BaseModel):
    slug: str


@router.post("/sync")
def sync_transactions(body: SyncRequest):
    """Pull new/modified/removed transactions for one item via transactions/sync.

    Uses the stored cursor and advances it, so repeat calls only return the delta.
    """
    client = _client()
    access_token = store.get_access_token(body.slug)
    if access_token is None:
        raise HTTPException(status_code=404, detail=f"No connected item '{body.slug}'")

    start_cursor = store.get_cursor(body.slug) or ""
    added, modified, removed = [], [], []
    cursor = start_cursor

    # Plaid can return TRANSACTIONS_SYNC_MUTATION_DURING_PAGINATION when the
    # underlying data changes mid-pagination (common right after linking while the
    # initial history is still ingesting). The documented fix is to restart
    # pagination from the cursor we began this call with. Retry a bounded number
    # of times before giving up.
    MAX_ATTEMPTS = 5
    for attempt in range(1, MAX_ATTEMPTS + 1):
        cursor = start_cursor
        added, modified, removed = [], [], []
        has_more = True
        try:
            while has_more:
                kwargs = {"access_token": access_token}
                if cursor:
                    kwargs["cursor"] = cursor
                resp = client.transactions_sync(TransactionsSyncRequest(**kwargs))
                added.extend(resp["added"])
                modified.extend(resp["modified"])
                removed.extend(resp["removed"])
                cursor = resp["next_cursor"]
                has_more = resp["has_more"]
            break  # completed a full, consistent pagination pass
        except Exception as e:
            code = _plaid_error_code(e)
            if code == "TRANSACTIONS_SYNC_MUTATION_DURING_PAGINATION" and attempt < MAX_ATTEMPTS:
                logger.info(
                    "sync for '%s': data mutated during pagination (attempt %d), restarting",
                    body.slug, attempt,
                )
                continue
            if code == "PRODUCT_NOT_READY":
                logger.info("sync for '%s': PRODUCT_NOT_READY (initial pull still processing)", body.slug)
                return {
                    "status": "not_ready",
                    "message": "Plaid is still preparing this bank's initial data. This can take a minute on first connect.",
                    "added": [], "modified": [], "removed": [],
                    "counts": {"added": 0, "modified": 0, "removed": 0},
                }
            logger.error("transactions_sync failed for '%s': %s", body.slug, e)
            raise HTTPException(status_code=502, detail="Plaid transactions_sync failed; see server logs.") from e

    store.save_cursor(body.slug, cursor)
    logger.info(
        "sync for '%s': added=%d modified=%d removed=%d",
        body.slug, len(added), len(modified), len(removed),
    )

    def _txn(t) -> dict:
        return {
            "transaction_id": t["transaction_id"],
            "date": str(t["date"]),
            "name": t["name"],
            "amount": t["amount"],
            "category": list(t["category"]) if t.get("category") else [],
        }

    return {
        "status": "ok",
        "message": None,
        "added": [_txn(t) for t in added],
        "modified": [_txn(t) for t in modified],
        "removed": [{"transaction_id": t["transaction_id"]} for t in removed],
        "counts": {"added": len(added), "modified": len(modified), "removed": len(removed)},
    }


@router.get("/balances/{slug}")
def get_balances(slug: str):
    """Return current balances for each account in one item (read-only)."""
    client = _client()
    access_token = store.get_access_token(slug)
    if access_token is None:
        raise HTTPException(status_code=404, detail=f"No connected item '{slug}'")
    try:
        resp = client.accounts_balance_get(AccountsBalanceGetRequest(access_token=access_token))
    except Exception as e:
        logger.error("accounts_balance_get failed for '%s': %s", slug, e)
        raise HTTPException(status_code=502, detail="Plaid accounts_balance_get failed; see server logs.") from e

    accounts = []
    for a in resp["accounts"]:
        bal = a["balances"]
        accounts.append({
            "account_id": a["account_id"],
            "name": a["name"],
            "type": str(a["type"]),
            "subtype": str(a["subtype"]) if a.get("subtype") else None,
            "current": bal["current"],
            "available": bal["available"],
        })
    return {"slug": slug, "accounts": accounts}
