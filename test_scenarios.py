"""Deterministic QA, with temporary databases inherited from the main fixtures."""
import logging
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.security import configure_security
from app.registry_breaker import RegistryBreaker, RegistryUnavailable
from test_main import accounts, broker, login  # pytest fixture reuse


def test_redacted_validation_and_request_id(accounts, caplog):
    client, _ = accounts
    marker = "sensitive-value-do-not-log"
    with caplog.at_level(logging.WARNING, logger="broker.errors"):
        response = client.post("/auth/token", json={"password": marker})
    assert response.status_code == 422
    assert marker not in response.text + caplog.text
    assert response.json()["request_id"] == response.headers["x-request-id"]
    assert all(set(error) == {"loc", "type"} for error in response.json()["errors"])


def test_global_error_is_safe(monkeypatch, caplog):
    app = FastAPI()
    monkeypatch.setenv("BROKER_CORS_ORIGINS", "https://portal.example.test")
    configure_security(app)

    @app.get("/boom")
    def fail():
        raise RuntimeError("private-token-value")

    with TestClient(app, raise_server_exceptions=False) as client:
        with caplog.at_level(logging.ERROR, logger="broker.errors"):
            response = client.get("/boom?token=private-query", headers={
                "Origin": "https://portal.example.test",
            })
    assert response.status_code == 500
    assert "private-token-value" not in response.text + caplog.text
    assert "private-query" not in caplog.text
    assert response.json()["request_id"] == response.headers["x-request-id"]
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["access-control-allow-origin"] == "https://portal.example.test"


def test_host_and_cors_policy(monkeypatch):
    app = FastAPI()
    monkeypatch.setenv("BROKER_CORS_ORIGINS", "https://portal.example.test")
    configure_security(app)

    @app.get("/ok")
    def ok():
        return {"ok": True}

    with TestClient(app) as client:
        assert client.get("/ok", headers={"Host": "evil.example"}).status_code == 400
        for status, origin in [(200, "https://portal.example.test"), (400, "https://evil.example")]:
            response = client.options("/ok", headers={
                "Origin": origin, "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization",
            })
            assert response.status_code == status
            assert response.headers["x-frame-options"] == "DENY"
            assert response.headers.get("access-control-allow-origin") == (
                origin if status == 200 else None
            )


def test_security_headers_cover_errors_and_portal(broker):
    client, _ = broker
    for path in ("/portal", "/missing", "/services/track/unknown"):
        response = client.get(path)
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["x-frame-options"] == "DENY"
        assert response.headers["referrer-policy"] == "same-origin"
        assert len(response.headers["x-request-id"]) == 32


def test_missing_pdf_and_failed_claim_audit(accounts):
    from sqlalchemy import select
    from app.models import AuditLog

    client, sessions = accounts
    headers = login(client, "alice")
    assert client.get("/services/certificate/INVALID-CODE-123", headers=headers).status_code == 404
    with patch("app.routers.mock_registry.random", return_value=0):
        response = client.post("/services/claims", headers=headers, json={
            "national_id": "0123456789", "claim_type": "demo",
        })
    assert response.status_code == 503
    with sessions() as db:
        records = list(db.scalars(select(AuditLog).where(AuditLog.action == "CLAIM_FAILED")))
        assert len(records) == 1
        assert records[0].details == response.json()["tracking_code"]


def test_breaker_allows_one_half_open_probe():
    breaker = RegistryBreaker()
    with patch("app.registry_breaker.monotonic", return_value=100) as clock:
        for _ in range(5):
            generation = breaker.acquire()
            breaker.finish(generation, "unavailable")
        clock.return_value = 160
        generation = breaker.acquire()
        try:
            breaker.acquire()
        except RegistryUnavailable:
            pass
        else:
            raise AssertionError("Concurrent half-open probe was allowed")
        breaker.finish(generation, "unavailable")
        assert breaker.reopen_at == 220
        clock.return_value = 220
        generation = breaker.acquire()
        breaker.finish(generation, "reachable")
        assert breaker.acquire() == breaker.generation
        assert breaker.reopen_at is None


def test_staging_disables_public_demo(tmp_path):
    import os
    import subprocess
    import sys

    subprocess.run(
        [sys.executable, "-c", """
from fastapi.testclient import TestClient
from app.main import app
with TestClient(app) as client:
    assert client.post("/api/demo/requests", json={"service":"claim","reference":"DEMO-101"}).status_code == 404
    assert client.get("/health").status_code == 200
    assert client.get("/services/track/example").status_code == 401
"""],
        env={**os.environ, "BROKER_ENABLE_DEMO": "false",
             "BROKER_DATABASE_URL": f"sqlite:///{tmp_path / 'staging.db'}"},
        check=True,
    )
