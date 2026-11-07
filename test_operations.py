"""Operations checks: configuration, readiness, migrations and optional real PostgreSQL."""
import os
import subprocess
import sys
from unittest.mock import patch

import httpx
import jwt
import pytest
from pydantic import ValidationError
from sqlalchemy import inspect
from sqlalchemy.exc import OperationalError

import app.main as application
from app.config import Settings, get_settings
from app.database import build_engine
from test_main import accounts, broker, login


def test_readiness_fails_safely_but_process_is_live(broker, monkeypatch, caplog):
    client, _ = broker
    def unavailable():
        raise OperationalError("password=private-database-secret", {}, Exception("private-host"))
    monkeypatch.setattr(application, "SessionLocal", unavailable)
    for endpoint in ("/health", "/ready"):
        response = client.get(endpoint)
        assert response.status_code == 503
        assert response.json()["database"] == "disconnected"
        assert "private" not in response.text + caplog.text
        assert response.headers["cache-control"] == "no-store"
    assert client.get("/live").status_code == 200


def test_dotenv_priority_and_redaction(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text('BROKER_JWT_SECRET=' + 'file-secret-' * 4 + '\nBROKER_ACCESS_TOKEN_EXPIRE_MINUTES=11\n')
    monkeypatch.setenv("BROKER_ACCESS_TOKEN_EXPIRE_MINUTES", "17")
    settings = Settings(_env_file=env)
    assert settings.access_token_expire_minutes == 17
    assert 'file-secret' not in repr(settings)
    assert settings.jwt_secret.get_secret_value().startswith('file-secret')
    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None, jwt_secret="too-short")
    assert 'too-short' not in str(error.value)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, algorithm="none")
    with pytest.raises(ValidationError):
        Settings(_env_file=None, mock_failure_rate=2)


def test_configurable_token_lifetime(accounts, monkeypatch):
    client, _ = accounts
    monkeypatch.setenv("BROKER_ACCESS_TOKEN_EXPIRE_MINUTES", "12")
    get_settings.cache_clear()
    token = login(client, "alice")["Authorization"].split()[1]
    claims = jwt.decode(token, get_settings().jwt_secret.get_secret_value(), algorithms=["HS256"])
    assert claims["exp"] - claims["iat"] == 12 * 60


def test_external_mock_url_and_no_retry_on_client_error(accounts, monkeypatch):
    client, _ = accounts
    headers = login(client, "alice")
    monkeypatch.setenv("BROKER_MOCK_REGISTRY_URL", "https://mock.example.test/submit")
    get_settings.cache_clear()
    calls = []
    def respond(request):
        calls.append(str(request.url))
        return httpx.Response(400, json={"detail": "invalid demo input"})
    original = httpx.AsyncClient
    def mock_client(**kwargs):
        kwargs["transport"] = httpx.MockTransport(respond)
        return original(**kwargs)
    with patch("app.routers.services.httpx.AsyncClient", side_effect=mock_client):
        response = client.post("/services/claims", headers=headers,
                               json={"national_id": "0123456789", "claim_type": "demo"})
    assert response.status_code == 422
    assert calls == ["https://mock.example.test/submit"]


def test_fresh_sqlite_migrations_preserve_data(tmp_path):
    url = f"sqlite:///{tmp_path / 'migrated.db'}"
    env = {**os.environ, "BROKER_DATABASE_URL": url}
    for command in (("upgrade", "head"), ("check",)):
        subprocess.run([sys.executable, "-m", "alembic", *command], env=env, check=True)
    engine = build_engine(url)
    assert {"users", "audit_logs", "document_requests", "demo_requests", "demo_request_events"} <= set(inspect(engine).get_table_names())
    with engine.begin() as db:
        from sqlalchemy import text
        db.execute(text("INSERT INTO users (username, hashed_password, role, is_active) VALUES ('preserved', 'hash', 'broker', true)"))
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], env=env, check=True)
    with engine.connect() as db:
        assert db.execute(text("SELECT username FROM users")).scalar_one() == "preserved"
    engine.dispose()


@pytest.mark.skipif(not os.getenv("TEST_POSTGRES_URL"), reason="PostgreSQL integration runs in CI")
def test_postgresql_migration_and_full_claim_flow():
    env = {**os.environ, "BROKER_DATABASE_URL": os.environ.get("TEST_POSTGRES_URL", ""),
           "BROKER_AUTO_CREATE_TABLES": "false",
           "BROKER_JWT_SECRET": "ci-disposable-signing-key-for-postgres-only-0000"}
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], env=env, check=True)
    subprocess.run([sys.executable, "-m", "alembic", "check"], env=env, check=True)
    subprocess.run([sys.executable, "-c", '''
from fastapi.testclient import TestClient
from unittest.mock import patch
from uuid import uuid4
from app.main import app
from app.database import SessionLocal
from app.models import User, AuditLog
from app.auth import passwords
from sqlalchemy import select
name = "pg-" + uuid4().hex[:12]
with TestClient(app) as client:
    assert client.get("/ready").status_code == 200
    with SessionLocal() as db:
        db.add(User(username=name, hashed_password=passwords.hash("test-password-only")))
        db.commit()
    token = client.post("/auth/token", data={"username": name, "password": "test-password-only"}).json()["access_token"]
    headers = {"Authorization": "Bearer " + token}
    with patch("app.routers.mock_registry.random", return_value=1):
        claim = client.post("/services/claims", json={"national_id":"0123456789","claim_type":"demo"}, headers=headers)
    assert claim.status_code == 201, claim.text
    code = claim.json()["tracking_code"]
    assert client.get("/services/track/"+code, headers=headers).json()["status"] == "success"
    assert client.get("/services/certificate/"+code, headers=headers).content.startswith(b"%PDF")
    with SessionLocal() as db:
        assert db.scalar(select(AuditLog.id).where(AuditLog.action == "CLAIM_SUCCESS"))
'''], env=env, check=True)
