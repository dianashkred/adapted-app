from fastapi.testclient import TestClient

from app.main import app


def test_health_runs_as_application_role():
    body = TestClient(app).get("/health").json()
    assert body == {"status": "ok", "db_user": "adapted_app"}
