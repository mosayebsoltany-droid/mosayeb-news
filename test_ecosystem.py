import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import httpx
from sqlalchemy import func, select

from app.models import AuditLog, DocumentRequest, NotificationEvent, User
from app import worker
from test_main import accounts, broker, login
from test_enterprise import admin_headers


PAYLOAD = {"national_id": "0012345678", "claim_type": "demo"}


def successful_claim(client, headers):
    with patch("app.routers.mock_registry.random", return_value=1):
        response = client.post("/services/claims", headers=headers, json=PAYLOAD)
    assert response.status_code == 201, response.text
    return response


def test_external_integrations_are_mock_only_and_role_protected(accounts, caplog):
    client, sessions = accounts
    broker_header = login(client, "alice")
    admin_header = admin_headers(client, sessions)
    assert client.post("/external/verify-national-id", json=PAYLOAD).status_code == 401
    valid = client.post("/external/verify-national-id", headers=broker_header,
                        json={"national_id": "0012345678"})
    assert valid.json()["simulation"] is True and valid.json()["is_valid"] is True
    assert client.post("/external/verify-national-id", headers=broker_header,
                       json={"national_id": "0112345678"}).json()["is_valid"] is False
    assert client.post("/external/verify-national-id", headers=broker_header,
                       json={"national_id": "bad"}).status_code == 422
    payload = {"phone_number": "09120000000", "message": "private-message-marker"}
    assert client.post("/external/send-sms", json=payload).status_code == 401
    assert client.post("/external/send-sms", headers=broker_header, json=payload).status_code == 403
    result = client.post("/external/send-sms", headers=admin_header, json=payload)
    assert result.status_code == 200
    assert result.json()["status"] == "simulated" and result.json()["simulation"] is True
    assert "09120000000" not in result.text + caplog.text
    assert "private-message-marker" not in result.text + caplog.text


def test_claim_returns_without_delivery_and_notification_is_owner_only(accounts):
    client, sessions = accounts
    alice, bob = login(client, "alice"), login(client, "bob")
    with patch("app.worker.send_sms_background", new_callable=AsyncMock) as deliver:
        response = successful_claim(client, alice)
        deliver.assert_not_awaited()
    event_id = response.headers["x-simulated-notification-id"]
    url = "/notifications/" + event_id
    assert client.get(url).status_code == 401
    assert client.get(url, headers=bob).status_code == 404
    assert client.get(url, headers=alice).json()["status"] == "pending"
    assert asyncio.run(worker.process_one(sessions)) is True
    final = client.get(url, headers=alice).json()
    assert final["status"] == "completed" and final["attempts"] == 1
    assert final["receipt"] == "SIM-SMS-" + event_id
    assert asyncio.run(worker.process_one(sessions)) is False
    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(AuditLog).where(
            AuditLog.action == "SIM_NOTIFICATION_DONE", AuditLog.details == event_id)) == 1


def test_failed_claim_never_queues_notification(accounts):
    client, sessions = accounts
    headers = login(client, "alice")
    with patch("app.routers.mock_registry.random", return_value=0):
        response = client.post("/services/claims", headers=headers, json=PAYLOAD)
    assert response.status_code == 503
    assert "x-simulated-notification-id" not in response.headers
    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(NotificationEvent)) == 0


def test_outbox_transaction_and_same_claim_idempotency(accounts):
    _, sessions = accounts
    with sessions() as db:
        user_id = db.scalar(select(User.id).where(User.username == "alice"))
        record = DocumentRequest(user_id=user_id, tracking_code="TRANSACTION-DEMO", request_type="claim", status="success")
        db.add(record)
        db.flush()
        event = worker.queue_claim_notification(db, record)
        assert worker.queue_claim_notification(db, record).id == event.id
        assert db.scalar(select(func.count()).select_from(NotificationEvent)) == 1
        db.rollback()
    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(NotificationEvent)) == 0
        assert db.scalar(select(func.count()).select_from(DocumentRequest)) == 0


def test_retry_budget_and_failed_event_are_durable(accounts):
    client, sessions = accounts
    headers = login(client, "alice")
    clock = datetime.now(timezone.utc).replace(tzinfo=None)
    with patch("app.worker.utcnow", side_effect=lambda: clock):
        response = successful_claim(client, headers)
        with patch("app.worker.send_sms_background", new_callable=AsyncMock,
                   side_effect=httpx.ConnectTimeout("private-gateway-value")) as deliver:
            assert asyncio.run(worker.process_one(sessions)) is True
            assert asyncio.run(worker.process_one(sessions)) is False  # backoff respected
            clock += timedelta(seconds=31)
            assert asyncio.run(worker.process_one(sessions)) is True
            clock += timedelta(seconds=31)
            assert asyncio.run(worker.process_one(sessions)) is True
            assert asyncio.run(worker.process_one(sessions)) is False
            assert deliver.await_count == 3
    result = client.get("/notifications/"+response.headers["x-simulated-notification-id"], headers=headers).json()
    assert result["status"] == "failed" and result["attempts"] == 3 and result["receipt"] is None


def test_lease_recovery_fences_a_stale_worker(accounts):
    client, sessions = accounts
    response = successful_claim(client, login(client, "alice"))
    event_id = response.headers["x-simulated-notification-id"]
    now = worker.utcnow() + timedelta(seconds=1)
    first = worker.claim_event(sessions, now)
    assert first.id == event_id
    assert worker.claim_event(sessions, now) is None
    second = worker.claim_event(sessions, now+timedelta(seconds=31))
    assert second.attempt == 2 and second.lease_token != first.lease_token
    worker.finish_event(first, "SIM-SMS-"+event_id, sessions, now)
    with sessions() as db:
        assert db.get(NotificationEvent, event_id).status == "processing"
    worker.finish_event(second, "SIM-SMS-"+event_id, sessions, now+timedelta(seconds=32))
    with sessions() as db:
        assert db.get(NotificationEvent, event_id).status == "completed"
        assert db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action == "SIM_NOTIFICATION_DONE")) == 1


def test_worker_crash_on_last_attempt_is_marked_failed(accounts):
    client, sessions = accounts
    response = successful_claim(client, login(client, "alice"))
    event_id = response.headers["x-simulated-notification-id"]
    now = worker.utcnow()
    with sessions() as db:
        event = db.get(NotificationEvent, event_id)
        event.status = "processing"
        event.attempts = 3
        event.lease_until = now-timedelta(seconds=1)
        event.lease_token = "crashed-worker"
        db.commit()
    assert worker.claim_event(sessions, now) is None
    with sessions() as db:
        assert db.get(NotificationEvent, event_id).status == "failed"


def test_chart_has_seven_zero_filled_days_and_admin_access(accounts):
    client, sessions = accounts
    user_header = login(client, "alice")
    endpoint = "/admin/analytics/chart-data"
    assert client.get(endpoint).status_code == 401
    assert client.get(endpoint, headers=user_header).status_code == 403
    headers = admin_headers(client, sessions)
    today = datetime.now(timezone.utc).replace(tzinfo=None, hour=12, minute=0, second=0, microsecond=0)
    with sessions() as db:
        user_id = db.scalar(select(User.id).where(User.username == "alice"))
        for index, (offset, status) in enumerate([(0,"success"),(0,"success"),(6,"failed"),(7,"success"),(-1,"success"),(0,"pending")]):
            db.add(DocumentRequest(user_id=user_id, tracking_code=f"CHART-{index}", request_type="claim", status=status,
                                   created_at=today-timedelta(days=offset)))
        db.commit()
    response = client.get(endpoint, headers=headers)
    assert response.status_code == 200
    result = response.json()
    assert len(result["labels"]) == 7 and result["labels"][-1] == today.date().isoformat()
    assert result["datasets"][0]["data"] == [0,0,0,0,0,0,2]
    assert result["datasets"][1]["data"] == [1,0,0,0,0,0,0]
    shell = client.get("/admin")
    assert shell.status_code == 200 and 'id="dashboard" hidden' in shell.text
    assert "localStorage" not in shell.text and "https://cdn" not in shell.text


def test_additive_migration_preserves_existing_users_and_claims(tmp_path):
    import os
    import subprocess
    import sys
    from sqlalchemy import create_engine, inspect, text
    url = f"sqlite:///{tmp_path / 'upgrade.db'}"
    env = {**os.environ, "BROKER_DATABASE_URL": url}
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "0001"], env=env, check=True)
    engine = create_engine(url)
    with engine.begin() as db:
        db.execute(text("INSERT INTO users (id, username, hashed_password, role, is_active) VALUES (1,'preserved','hash','broker',true)"))
        db.execute(text("INSERT INTO document_requests (tracking_code,user_id,request_type,status,created_at) VALUES ('KEEP-ME',1,'claim','success','2026-01-01 00:00:00')"))
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], env=env, check=True)
    subprocess.run([sys.executable, "-m", "alembic", "check"], env=env, check=True)
    with engine.connect() as db:
        assert db.execute(text("SELECT tracking_code FROM document_requests")).scalar_one() == "KEEP-ME"
        assert db.execute(text("SELECT username FROM users")).scalar_one() == "preserved"
    assert "notification_events" in inspect(engine).get_table_names()
    engine.dispose()


def test_embedded_worker_is_owned_by_lifespan(tmp_path, monkeypatch):
    import threading
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    import app.main as application
    from app.config import get_settings
    started, stopped = threading.Event(), threading.Event()
    async def fake_worker(sessions):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()
    engine = create_engine(f"sqlite:///{tmp_path / 'lifespan.db'}")
    monkeypatch.setattr(application, "engine", engine)
    monkeypatch.setattr(application, "SessionLocal", sessionmaker(bind=engine))
    monkeypatch.setattr(application, "run_worker", fake_worker)
    monkeypatch.setenv("BROKER_NOTIFICATION_WORKER_ENABLED", "true")
    get_settings.cache_clear()
    with TestClient(application.app):
        assert started.wait(1)
    assert stopped.is_set()
