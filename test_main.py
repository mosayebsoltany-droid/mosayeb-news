import sys
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, inspect, select
from sqlalchemy.orm import sessionmaker
from tenacity import wait_none

import app.create_user as account_cli
import app.main as application
from app.auth import passwords
from app.database import enable_foreign_keys, get_db
from app.models import AuditLog, User
from app.registry_breaker import RegistryBreaker
from app.routers import services

PASSWORD = "test password only"
CLAIM = {"national_id": "0123456789", "claim_type": "demo"}


@pytest.fixture
def broker(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    event.listen(engine, "connect", enable_foreign_keys)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)

    def test_db():
        with sessions() as db:
            yield db

    monkeypatch.setenv("BROKER_JWT_SECRET", "test-only-secret-not-for-deployment-000000")
    monkeypatch.setenv("BROKER_MOCK_FAILURE_RATE", "0.2")
    monkeypatch.setattr(application, "engine", engine)
    monkeypatch.setattr(application, "SessionLocal", sessions)
    monkeypatch.setattr(account_cli, "engine", engine)
    monkeypatch.setattr(account_cli, "SessionLocal", sessions)
    monkeypatch.setitem(application.app.dependency_overrides, get_db, test_db)
    monkeypatch.setattr(services, "registry_breaker", RegistryBreaker())
    monkeypatch.setattr(services.call_mock_registry.retry, "wait", wait_none())
    with TestClient(application.app) as client:
        yield client, sessions


@pytest.fixture
def accounts(broker):
    client, sessions = broker
    with sessions() as db:
        hashed = passwords.hash(PASSWORD)
        db.add_all(User(username=name, hashed_password=hashed) for name in ("alice", "bob"))
        db.commit()
    return client, sessions


def login(client, username):
    response = client.post("/auth/token", data={"username": username, "password": PASSWORD})
    assert response.status_code == 200, response.text
    assert response.json()["token_type"] == "bearer"
    return {"Authorization": "Bearer " + response.json()["access_token"]}


def test_health_and_portal(broker):
    client, sessions = broker
    expected = {"status": "ok", "mode": "simulation"}
    for path in ("/", "/health"):
        response = client.get(path)
        assert response.status_code == 200
        assert response.json() == expected
    portal = client.get("/portal")
    assert portal.status_code == 200
    assert '<html lang="fa" dir="rtl">' in portal.text
    with sessions() as db:
        assert {"users", "audit_logs", "document_requests"} <= set(inspect(db.bind).get_table_names())


def test_cli_account_creation_and_login(broker, monkeypatch):
    client, sessions = broker
    monkeypatch.setattr(sys, "argv", ["create_user", "test_broker"])
    monkeypatch.setattr(account_cli, "getpass", lambda _: PASSWORD)
    account_cli.main()
    with pytest.raises(SystemExit) as duplicate:
        account_cli.main()
    assert duplicate.value.code == 1
    assert client.post("/auth/token", data={
        "username": "test_broker", "password": "wrong password",
    }).status_code == 401
    login(client, "test_broker")
    with sessions() as db:
        user = db.scalar(select(User).where(User.username == "test_broker"))
        assert user.hashed_password != PASSWORD
        assert db.scalar(select(AuditLog.action)) == "LOGIN"


def test_protected_routes_require_a_valid_token(broker):
    client, _ = broker
    assert client.post("/services/claims", json=CLAIM).status_code == 401
    assert client.post("/services/maps", files={"file": ("demo.txt", b"x")}).status_code == 401
    assert client.get("/services/track/example").status_code == 401
    assert client.get("/services/certificate/example").status_code == 401
    assert client.post("/services/claims", json=CLAIM, headers={
        "Authorization": "Bearer invalid",
    }).status_code == 401


def test_mock_validation_does_not_attempt_submission(accounts):
    client, _ = accounts
    headers = login(client, "alice")
    invalid = {**CLAIM, "national_id": "123"}
    with patch("app.routers.mock_registry.random") as random:
        for path in ("/mock-registry/submit", "/services/claims"):
            response = client.post(path, json=invalid, headers=headers)
            assert response.status_code == 422
            assert response.json()["detail"][0]["loc"] == ["body", "national_id"]
        random.assert_not_called()


def test_claim_retry_owner_tracking_and_pdf(accounts):
    client, sessions = accounts
    alice, bob = login(client, "alice"), login(client, "bob")
    payload = CLAIM
    with patch("app.routers.mock_registry.random", side_effect=[0, 0, 1]) as mock:
        claim = client.post("/services/claims", headers=alice, json=payload)
        assert claim.status_code == 201, claim.text
        assert mock.call_count == 3
    assert claim.json()["status"] == "success"
    url = "/services/track/" + claim.json()["tracking_code"]
    assert client.get(url, headers=alice).json() == claim.json()
    assert client.get(url, headers=bob).status_code == 404
    pdf_url = "/services/certificate/" + claim.json()["tracking_code"]
    assert client.get(pdf_url).status_code == 401
    assert client.get(pdf_url, headers=bob).status_code == 404
    pdf = client.get(pdf_url, headers=alice)
    assert pdf.status_code == 200, pdf.text
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.headers["cache-control"] == "no-store"
    assert pdf.content.startswith(b"%PDF")
    with sessions() as db:
        assert set(db.scalars(select(AuditLog.action))) == {"LOGIN", "CLAIM_SUCCESS", "DOWNLOAD_CERTIFICATE"}


def test_circuit_breaker_opens_blocks_and_recovers(accounts):
    client, _ = accounts
    alice = login(client, "alice")
    payload = CLAIM
    with patch("app.routers.mock_registry.random", return_value=0) as mock:
        failed = client.post("/services/claims", headers=alice, json=payload)
        assert failed.status_code == 503, failed.text
        assert mock.call_count == 3
    assert failed.json()["status"] == "failed"
    failed_pdf = "/services/certificate/" + failed.json()["tracking_code"]
    assert client.get(failed_pdf, headers=alice).status_code == 409
    assert client.get("/services/track/" + failed.json()["tracking_code"], headers=alice).json() == failed.json()
    with patch("app.registry_breaker.monotonic", return_value=100) as clock:
        with patch("app.routers.mock_registry.random", return_value=0) as mock:
            # Three previous failures plus two now open the circuit on attempt five.
            assert client.post("/services/claims", headers=alice, json=payload).status_code == 503
            assert mock.call_count == 2
            blocked = client.post("/services/claims", headers=alice, json=payload)
            assert blocked.status_code == 503
            assert blocked.json()["status"] == "failed"
            assert mock.call_count == 2
        clock.return_value = 160
        with patch("app.routers.mock_registry.random", return_value=1) as mock:
            assert client.post("/services/claims", headers=alice, json=payload).status_code == 201
            assert client.post("/services/claims", headers=alice, json=payload).status_code == 201
            assert mock.call_count == 2


def test_map_requests_have_unique_tracking_codes(accounts):
    client, sessions = accounts
    alice = login(client, "alice")
    maps = [client.post("/services/maps", headers=alice, files={"file": ("demo.txt", b"test")}) for _ in range(2)]
    assert all(reply.status_code == 201 for reply in maps), [reply.text for reply in maps]
    assert maps[0].json()["tracking_code"] != maps[1].json()["tracking_code"]
    with sessions() as db:
        assert list(db.scalars(select(AuditLog.action).where(AuditLog.action == "REQUEST_MAP"))) == [
            "REQUEST_MAP", "REQUEST_MAP",
        ]


def test_portal_demo_workflows_and_certificate_pdf(broker):
    client, _ = broker
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
        pdf = client.get(f"{url}/certificate.pdf")
        if service == "certificate":
            assert pdf.status_code == 200, pdf.text
            assert pdf.headers["content-type"] == "application/pdf"
            assert pdf.content.startswith(b"%PDF")
        else:
            assert pdf.status_code == 409
