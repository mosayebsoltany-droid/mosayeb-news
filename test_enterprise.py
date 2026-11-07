from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from sqlalchemy import func, select

from app.auth import passwords
from app.models import AuditLog, DocumentRequest, User, UserRole
from app.core.rate_limit import limiter
from test_main import accounts, broker, login, PASSWORD


def admin_headers(client, sessions):
    with sessions() as db:
        db.add(User(username="admin", hashed_password=passwords.hash(PASSWORD), role=UserRole.admin))
        db.commit()
    return login(client, "admin")


def test_dashboard_is_admin_only_with_exact_period_counts(accounts):
    client, sessions = accounts
    alice = login(client, "alice")
    assert client.get("/analytics/dashboard").status_code == 401
    assert client.get("/analytics/dashboard", headers=alice).status_code == 403
    headers = admin_headers(client, sessions)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    with sessions() as db:
        ids = {u.username: u.id for u in db.scalars(select(User))}
        for i, (who, status, when) in enumerate([
            ("alice", "success", now), ("bob", "success", now),
            ("alice", "failed", now), ("bob", "pending", now),
            ("bob", "success", now - timedelta(days=90)),
        ]):
            db.add(DocumentRequest(user_id=ids[who], request_type="claim", status=status,
                                   tracking_code=f"ANALYTICS-{i}", created_at=when))
        db.commit()
    result = client.get("/analytics/dashboard", headers=headers)
    assert result.status_code == 200
    stats = result.json()
    assert [stats[k] for k in ("total_requests", "successful_requests", "failed_requests", "pending_requests")] == [4, 2, 1, 1]
    assert stats["top_broker"] == "alice"  # deterministic alphabetical tie
    assert client.get("/analytics/dashboard?start_date=2026-01-02&end_date=2026-01-01", headers=headers).status_code == 422


def test_dashboard_empty_and_explicit_dates(accounts):
    client, sessions = accounts
    headers = admin_headers(client, sessions)
    stats = client.get("/analytics/dashboard?start_date=2020-01-01&end_date=2020-01-31", headers=headers).json()
    assert stats["total_requests"] == 0
    assert stats["top_broker"] == "نامشخص"
    assert stats["start_date"] == "2020-01-01"


def test_identity_mock_validation_rejection_and_no_registry_submission(accounts):
    client, sessions = accounts
    headers = login(client, "alice")
    invalid = client.get("/mock-registry/identity-check/123")
    assert invalid.status_code == 400
    assert client.get("/mock-registry/identity-check/abcdefghij").status_code == 400
    assert client.get("/mock-registry/identity-check/9012345678").json()["simulation"] is True
    with patch("app.routers.services.call_mock_registry", new_callable=AsyncMock) as registry:
        rejected = client.post("/services/claims", headers=headers,
                               json={"national_id": "9012345678", "claim_type": "demo"})
    assert rejected.status_code == 400
    registry.assert_not_called()
    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(DocumentRequest)) == 0
        assert db.scalar(select(AuditLog.action).where(AuditLog.action == "IDENTITY_REJECTED"))


@pytest.mark.parametrize("outcome", ["timeout", "server_error", "malformed", "wrong_id", "non_boolean"])
def test_identity_failure_is_closed_and_audited(accounts, outcome):
    client, sessions = accounts
    headers = login(client, "alice")
    async def failing_get(self, url, **kwargs):
        request = httpx.Request("GET", "http://mock-registry" + url)
        if outcome == "timeout":
            raise httpx.ConnectTimeout("private-network-info", request=request)
        data = {"national_id": "0012345678", "is_alive": True, "simulation": True}
        if outcome == "wrong_id": data["national_id"] = "0012345679"
        if outcome == "non_boolean": data["is_alive"] = "true"
        if outcome == "malformed": data = {"private": "do-not-show"}
        return httpx.Response(503 if outcome == "server_error" else 200, json=data, request=request)
    with patch("httpx.AsyncClient.get", new=failing_get), patch("app.routers.services.call_mock_registry", new_callable=AsyncMock) as registry:
        response = client.post("/services/claims", headers=headers,
                               json={"national_id": "0012345678", "claim_type": "demo"})
    assert response.status_code == 503
    assert "private" not in response.text
    registry.assert_not_called()
    with sessions() as db:
        assert db.scalar(select(AuditLog.id).where(AuditLog.action == "IDENTITY_UNAVAILABLE"))


def test_claim_limit_is_per_account_and_applies_before_submission(accounts):
    client, _ = accounts
    alice, bob = login(client, "alice"), login(client, "bob")
    payload = {"national_id": "0012345678", "claim_type": "demo"}
    with patch("app.routers.mock_registry.random", return_value=1) as registry:
        for _ in range(5):
            assert client.post("/services/claims", headers=alice, json=payload).status_code == 201
        response = client.post("/services/claims", headers={**alice, "X-Forwarded-For": "8.8.8.8"}, json=payload)
        assert response.status_code == 429
        assert int(response.headers["retry-after"]) > 0
        assert registry.call_count == 5
        assert client.post("/services/claims", headers=bob, json=payload).status_code == 201


def test_login_limit_cannot_be_bypassed_by_forwarded_header(broker):
    client, _ = broker
    for i in range(10):
        assert client.post("/auth/token", data={"username": "missing", "password": "wrong"},
                           headers={"X-Forwarded-For": f"10.0.0.{i}"}).status_code == 401
    response = client.post("/auth/token", data={"username": "missing", "password": "wrong"})
    assert response.status_code == 429


def test_rate_storage_outage_fails_closed(accounts):
    from limits.errors import StorageError
    client, _ = accounts
    headers = login(client, "alice")
    with patch.object(limiter.limiter, "hit", side_effect=StorageError(RuntimeError("private-storage-key"))):
        response = client.post("/services/claims", headers=headers,
                               json={"national_id": "0012345678", "claim_type": "demo"})
    assert response.status_code == 503
    assert "private" not in response.text


def test_inactive_admin_cannot_access_dashboard(accounts):
    client, sessions = accounts
    headers = admin_headers(client, sessions)
    with sessions() as db:
        user = db.scalar(select(User).where(User.username == "admin"))
        user.is_active = False
        db.commit()
    assert client.get("/analytics/dashboard", headers=headers).status_code == 401


def test_readiness_checks_rate_backend(broker):
    client, _ = broker
    with patch.object(limiter._storage, "check", return_value=False):
        response = client.get("/ready")
        assert response.status_code == 503
        assert response.json()["database"] == "connected"
        assert response.json()["rate_limit"] == "unavailable"
        assert client.get("/live").status_code == 200
