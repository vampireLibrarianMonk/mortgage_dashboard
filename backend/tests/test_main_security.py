"""Security regression tests for the FastAPI app (main.py).

Focus: the SPA static-file catch-all must not serve files outside the built
`frontend/dist` directory (path traversal -> secret disclosure). This locks in
the fix for finding F1 in deploy/SECURITY_REVIEW.md.
"""
import pytest
from starlette.testclient import TestClient

import main


@pytest.fixture
def client():
    # Do not follow redirects; we want to see exactly what each path returns.
    return TestClient(main.app)


# Traversal payloads that must NOT escape dist. The double-encoded one is the
# variant that previously leaked the real .env (Plaid production secret).
TRAVERSAL_PATHS = [
    "/..%2F..%2F.env",
    "/..%2F..%2F..%2F.env",
    "/%2e%2e%2f%2e%2e%2f.env",
    "/..%2F..%2Fbackend/main.py",
    "/....//....//.env",
]

SECRET_MARKERS = ("PLAID", "client_id", "production_secret", "sandbox_secret",
                  "from fastapi", "import ")


@pytest.mark.skipif(not main._DIST_DIR.is_dir(),
                    reason="frontend/dist not built; SPA serving inactive")
@pytest.mark.parametrize("path", TRAVERSAL_PATHS)
def test_spa_traversal_does_not_leak(client, path):
    resp = client.get(path)
    # Either the request is rejected, or it safely falls back to index.html.
    # Critically, the body must never contain secret/source markers.
    body = resp.text
    for marker in SECRET_MARKERS:
        assert marker not in body, f"{path} leaked marker {marker!r}"


@pytest.mark.skipif(not main._DIST_DIR.is_dir(),
                    reason="frontend/dist not built; SPA serving inactive")
def test_spa_serves_index_for_unknown_route(client):
    resp = client.get("/some-client-side-route")
    assert resp.status_code == 200
    assert "<!doctype html>" in resp.text.lower() or "<html" in resp.text.lower()


def test_healthz_ok(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
