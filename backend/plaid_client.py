"""Plaid API client factory.

Reads credentials from the environment (PLAID_CLIENT_ID / PLAID_SECRET), which the
deploy startup script populates from Windows Credential Manager so secrets never
live in code or files. The API version is pinned to 2020-09-14 to match the
account default, and the environment defaults to Sandbox. Going to Production is
just a matter of swapping the secret and setting PLAID_ENV=production.
"""
import os

import plaid
from plaid.api import plaid_api

# Pin the Plaid API version to the account default so responses stay stable
# regardless of any future account-level default change.
PLAID_API_VERSION = "2020-09-14"

# Map our env name to the Plaid host. Sandbox is the safe default.
_HOSTS = {
    "sandbox": plaid.Environment.Sandbox,
    "production": plaid.Environment.Production,
}


class PlaidConfigError(RuntimeError):
    """Raised when Plaid credentials are not available in the environment."""


def get_plaid_env() -> str:
    return os.environ.get("PLAID_ENV", "sandbox").lower()


def credentials_available() -> bool:
    return bool(os.environ.get("PLAID_CLIENT_ID") and os.environ.get("PLAID_SECRET"))


def build_client() -> plaid_api.PlaidApi:
    """Build a PlaidApi client from environment credentials.

    Raises PlaidConfigError if the credentials are missing, so callers (the API
    endpoints) can return a clear 503 rather than a stack trace.
    """
    client_id = os.environ.get("PLAID_CLIENT_ID")
    secret = os.environ.get("PLAID_SECRET")
    if not client_id or not secret:
        raise PlaidConfigError(
            "Plaid credentials not found in the environment. Ensure PLAID_CLIENT_ID "
            "and PLAID_SECRET are set (the startup script reads them from Windows "
            "Credential Manager)."
        )

    env = get_plaid_env()
    host = _HOSTS.get(env)
    if host is None:
        raise PlaidConfigError(f"Unknown PLAID_ENV '{env}'. Use 'sandbox' or 'production'.")

    configuration = plaid.Configuration(
        host=host,
        api_key={
            "clientId": client_id,
            "secret": secret,
            "plaidVersion": PLAID_API_VERSION,
        },
    )
    api_client = plaid.ApiClient(configuration)
    return plaid_api.PlaidApi(api_client)
