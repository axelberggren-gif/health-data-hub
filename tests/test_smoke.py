"""Boot smoke test — the Python analog of the reference pipeline's `build` step.

Importing the app via TestClient runs the FastAPI lifespan (init_db, router wiring,
Settings validation). If the app can't import or boot, this fails — catching the
class of breakage that lint/typecheck/unit tests miss.
"""


def test_root_ok(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert resp.json()["app"]  # the app name is present


def test_health_ok(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
