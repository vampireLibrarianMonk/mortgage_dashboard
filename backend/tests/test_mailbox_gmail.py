"""Multi-account Gmail provider: two Gmail accounts must have isolated
credential slots and both register as distinct providers.

Isolation: patch credential_store's generic secret store with an in-memory dict
so nothing touches the real Windows Credential Manager.
"""

import pytest

import credential_store as cred
from mailbox import gmail, get_provider, registered_providers


@pytest.fixture(autouse=True)
def fake_cred_store(monkeypatch):
    store: dict[str, str] = {}
    monkeypatch.setattr(cred, "set_secret",
                        lambda target, secret, username="x": store.__setitem__(target, secret))
    monkeypatch.setattr(cred, "get_secret", lambda target: store.get(target))
    monkeypatch.setattr(cred, "delete_secret",
                        lambda target: (store.pop(target, None) is not None))
    return store


def test_both_gmail_providers_registered():
    names = registered_providers()
    assert "gmail" in names and "gmail2" in names
    assert get_provider("gmail").name == "gmail"
    assert get_provider("gmail2").name == "gmail2"


def test_two_gmail_accounts_have_isolated_credentials():
    gmail.save_credentials("first@gmail.com", "aaaa bbbb cccc dddd", provider="gmail")
    gmail.save_credentials("second@gmail.com", "eeee ffff gggg hhhh", provider="gmail2")

    assert gmail.load_credentials("gmail") == ("first@gmail.com", "aaaabbbbccccdddd")
    assert gmail.load_credentials("gmail2") == ("second@gmail.com", "eeeeffffgggghhhh")


def test_clearing_one_account_leaves_the_other(fake_cred_store):
    gmail.save_credentials("first@gmail.com", "aaaabbbbccccdddd", provider="gmail")
    gmail.save_credentials("second@gmail.com", "eeeeffffgggghhhh", provider="gmail2")

    assert gmail.clear_credentials("gmail") is True
    assert gmail.credentials_available("gmail") is False
    assert gmail.credentials_available("gmail2") is True  # untouched


def test_default_provider_is_first_account():
    # Back-compat: calling without a provider name targets "gmail".
    gmail.save_credentials("first@gmail.com", "aaaabbbbccccdddd")
    assert gmail.load_credentials() == ("first@gmail.com", "aaaabbbbccccdddd")
    assert gmail.credentials_available("gmail2") is False
