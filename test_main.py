import os
import sqlite3
import subprocess
import sys
from pathlib import Path


def test_health_and_database_startup(tmp_path):
    database = tmp_path / "broker.db"
    subprocess.run(
        [
            sys.executable,
            "-c",
            """
from fastapi.testclient import TestClient
from app.main import app

with TestClient(app) as client:
    response = client.get("/health")
    assert response.status_code == 200
    portal = client.get("/portal")
    assert portal.status_code == 200
    assert portal.headers["content-type"].startswith("text/html")
    assert '<html lang="fa" dir="rtl">' in portal.text
    assert response.json() == {"status": "ok", "mode": "simulation"}
    endpoint = "/api/demo/requests"
    assert client.post(endpoint, json={"service": "claim", "reference": "invalid"}).status_code == 422
    claim_code = None
    for service in ("claim", "map", "certificate"):
        reference = claim_code if service == "certificate" else "DEMO-101"
        draft = client.post(endpoint, json={"service": service, "reference": reference})
        assert draft.status_code == 201, draft.text
        assert draft.json()["events"] == ["registered"]
        code = draft.json()["code"]
        if service == "claim":
            claim_code = code
            premature = client.post(endpoint, json={"service": "certificate", "reference": code})
            assert premature.status_code == 409
        url = f"{endpoint}/{code}"
        result = client.post(f"{url}/submit").json()
        assert result["status"] == "completed"
        assert result["result"].startswith(f"SIM-{service.upper()}-")
        assert result["events"] == ["registered", "submitted", "simulation_response", "result_recorded"]
        assert client.post(f"{url}/submit").json() == result
        assert client.get(url).json() == result
""",
        ],
        env={**os.environ, "BROKER_DATABASE_URL": f"sqlite:///{database}"},
        cwd=Path(__file__).resolve().parent,
        check=True,
    )
    with sqlite3.connect(database) as connection:
        rows = connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        assert {"users", "audit_logs"} <= {name for (name,) in rows}


def test_authenticated_services(tmp_path):
    subprocess.run(
        [sys.executable, "-c", """
from unittest.mock import patch
from fastapi.testclient import TestClient
from tenacity import wait_none
from app.auth import passwords
from app.database import SessionLocal
from app.main import app
from app.models import AuditLog, User
from app.routers.services import call_mock_registry

with TestClient(app) as client:
    with SessionLocal() as db:
        hashed = passwords.hash("test password only")
        db.add_all(User(username=name, hashed_password=hashed) for name in ("alice", "bob"))
        db.commit()
    def login(username):
        reply = client.post("/auth/token", data={"username": username, "password": "test password only"})
        assert reply.status_code == 200, reply.text
        return {"Authorization": "Bearer " + reply.json()["access_token"]}

    payload = {"national_id": "0123456789", "claim_type": "demo"}
    assert client.post("/services/claims", json=payload).status_code == 401
    alice = login("alice")
    bob = login("bob")
    assert client.post("/services/claims", headers=alice, json={**payload, "national_id": "12"}).status_code == 422
    call_mock_registry.retry.wait = wait_none()
    with patch("app.routers.mock_registry.random", side_effect=[0, 0, 1]) as mock:
        claim = client.post("/services/claims", headers=alice, json=payload)
        assert claim.status_code == 201, claim.text
        assert mock.call_count == 3
    assert claim.json()["status"] == "success"
    url = "/services/track/" + claim.json()["tracking_code"]
    assert client.get(url, headers=alice).json() == claim.json()
    assert client.get(url, headers=bob).status_code == 404
    with patch("app.routers.mock_registry.random", return_value=0) as mock:
        failed = client.post("/services/claims", headers=alice, json=payload)
        assert failed.status_code == 503, failed.text
        assert mock.call_count == 3
    assert failed.json()["status"] == "failed"
    assert client.get("/services/track/" + failed.json()["tracking_code"], headers=alice).json() == failed.json()
    maps = [client.post("/services/maps", headers=alice, files={"file": ("demo.txt", b"test")}) for _ in range(2)]
    assert all(reply.status_code == 201 for reply in maps), [reply.text for reply in maps]
    assert maps[0].json()["tracking_code"] != maps[1].json()["tracking_code"]
    with SessionLocal() as db:
        assert {row.action for row in db.query(AuditLog)} == {"LOGIN", "CLAIM_SUCCESS", "CLAIM_FAILED", "REQUEST_MAP"}
"""],
        cwd=Path(__file__).resolve().parent,
        env={**os.environ, "BROKER_DATABASE_URL": f"sqlite:///{tmp_path / 'phase4.db'}",
             "BROKER_JWT_SECRET": "test-only-secret-not-for-deployment-000000"},
        check=True,
    )
