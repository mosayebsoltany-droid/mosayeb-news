import asyncio
import re
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect, select, text

import app.main as application
from app.auth import secret
from app.core.body_limit import RequestBodyLimitMiddleware
from app.models import AuditLog, User
from app.migrate import migrate_sqlite
from test_main import accounts, broker, login, PASSWORD
from test_enterprise import admin_headers


def test_failed_login_audit_peer_and_redaction(accounts):
    client, sessions = accounts
    peer = TestClient(application.app, client=("198.51.100.8", 2345))
    payloads = [("alice", "private-wrong-password"), ("not-present-marker", "wrong"), ("' OR 1=1--", "wrong")]
    ids = []
    for username, password in payloads:
        response = peer.post("/auth/token", data={"username": username, "password": password},
                             headers={"X-Forwarded-For": "203.0.113.99"})
        assert response.status_code == 401
        ids.append(response.headers["x-request-id"])
    with sessions() as db:
        rows = list(db.scalars(select(AuditLog).where(AuditLog.action == "FAILED_LOGIN_ATTEMPT").order_by(AuditLog.id)))
        assert len(rows) == 3 and rows[0].user_id is not None and rows[1].user_id is None
        assert [r.request_id for r in rows] == ids
        assert all(r.ip_address == "198.51.100.8" for r in rows)
        assert all(r.details == "Credentials rejected" for r in rows)
        assert db.scalar(select(User.id).where(User.username == "alice"))
    assert client.get("/admin/audit-logs").status_code == 401
    assert client.get("/admin/audit-logs", headers=login(client, "alice")).status_code == 403
    admin = admin_headers(client, sessions)
    logs = client.get("/admin/audit-logs?limit=3", headers=admin)
    assert logs.status_code == 200 and len(logs.json()) == 3
    assert client.get("/admin/audit-logs?limit=99999", headers=admin).status_code == 422
    for marker in ("private-wrong-password", "not-present-marker", "' OR 1=1--"):
        assert marker not in logs.text
    peer.close()


def test_login_sixth_attempt_is_limited_and_success_has_no_cookie(accounts):
    client, sessions = accounts
    for _ in range(5):
        assert client.post("/auth/token", data={"username": "missing", "password": "wrong"}).status_code == 401
    sixth = client.post("/auth/token", data={"username": "missing", "password": "wrong"})
    assert sixth.status_code == 429 and int(sixth.headers["retry-after"]) > 0
    with sessions() as db:
        assert len(list(db.scalars(select(AuditLog).where(AuditLog.action == "FAILED_LOGIN_ATTEMPT")))) == 5
    # Another network peer can log in; denial is temporary quota, not a permanent IP ban.
    peer = TestClient(application.app, client=("2001:db8::8", 2345))
    response = peer.post("/auth/token", data={"username": "alice", "password": PASSWORD})
    assert response.status_code == 200 and "set-cookie" not in response.headers
    with sessions() as db:
        assert db.scalar(select(AuditLog.ip_address).where(AuditLog.action == "LOGIN")) == "2001:db8::8"
    peer.close()


@pytest.mark.parametrize("patch", [{"sub": "0"}, {"sub": "01"}, {"sub": "9"*80},
                                     {"sub": {}}, {"exp": {}}, {"exp": float("inf")},
                                     {"iat": {}}, {"exp": 1}])
def test_malformed_signed_claims_fail_as_401(accounts, patch):
    client, sessions = accounts
    with sessions() as db:
        user_id = db.scalar(select(User.id).where(User.username == "alice"))
    now = datetime.now(timezone.utc)
    claims = {"sub": str(user_id), "iat": now, "exp": now+timedelta(minutes=5), **patch}
    token = jwt.encode(claims, secret(), algorithm="HS256")
    assert client.get("/analytics/dashboard", headers={"Authorization": "Bearer "+token}).status_code == 401


def test_token_role_field_does_not_grant_admin(accounts):
    client, sessions = accounts
    with sessions() as db:
        user_id = db.scalar(select(User.id).where(User.username == "alice"))
    now = datetime.now(timezone.utc)
    claims = {"sub": str(user_id), "iat": now, "exp": now+timedelta(minutes=5), "role": "admin"}
    token = jwt.encode(claims, secret(), algorithm="HS256")
    assert client.get("/admin/audit-logs", headers={"Authorization": "Bearer "+token}).status_code == 403
    token = jwt.encode(claims, secret(), algorithm="HS512")
    assert client.get("/admin/audit-logs", headers={"Authorization": "Bearer "+token}).status_code == 401


def test_csp_nonce_pages_docs_and_errors(broker):
    client, _ = broker
    for path in ("/admin", "/portal", "/docs", "/docs/oauth2-redirect"):
        first, second = client.get(path), client.get(path)
        assert first.status_code == 200
        csp = first.headers["content-security-policy"]
        nonce = re.search(r"'nonce-([^']+)'", csp)[1]
        assert nonce != re.search(r"'nonce-([^']+)'", second.headers["content-security-policy"])[1]
        assert f'nonce="{nonce}"' in first.text
        assert all(f'nonce="{nonce}"' in tag for tag in re.findall(r"<script[^>]*>", first.text))
        assert "'unsafe-inline'" not in csp.split("style-src")[0]
        assert first.headers["x-xss-protection"] == "0"
        assert first.headers["x-frame-options"] == "DENY"
        assert "frame-ancestors 'none'" in csp
        assert "payment=()" in first.headers["permissions-policy"]
    for path in ("/missing", "/admin/audit-logs"):
        response = client.get(path)
        assert "default-src 'none'" in response.headers["content-security-policy"]


def test_hsts_only_for_https_not_untrusted_forwarded_proto(broker):
    client, _ = broker
    assert "strict-transport-security" not in client.get("/live", headers={"X-Forwarded-Proto":"https"}).headers
    secure = TestClient(application.app, base_url="https://testserver")
    for path in ("/live", "/missing", "/admin/audit-logs"):
        assert secure.get(path).headers["strict-transport-security"] == "max-age=31536000"
    secure.close()


def test_request_body_cap_before_parsing_and_with_chunked_transfer():
    async def run_case(headers, chunks, path="/auth/token"):
        called, received, sent = [], [], []
        async def inner(scope, receive, send):
            called.append(True)
        messages = iter([{"type":"http.request", "body":chunk, "more_body":i < len(chunks)-1} for i,chunk in enumerate(chunks)])
        async def receive():
            received.append(True)
            return next(messages)
        async def send(message): sent.append(message)
        await RequestBodyLimitMiddleware(inner)({"type":"http", "method":"POST", "path":path, "headers":headers}, receive, send)
        return called, received, sent
    called, received, sent = asyncio.run(run_case([(b"content-length", b"99999999")], [b"x"]))
    assert not called and not received and sent[0]["status"] == 413
    called, received, sent = asyncio.run(run_case([], [b"x"*10000,b"x"*10000,b"unused"]))
    assert not called and len(received) == 2 and sent[0]["status"] == 413
    called, received, sent = asyncio.run(run_case([(b"content-length",b"2"),(b"transfer-encoding",b"chunked")], [b"ab"]))
    assert not called and not received and sent[0]["status"] == 400


def test_body_cap_has_security_headers_and_no_auth_work(broker):
    client, _ = broker
    response = client.post("/auth/token", content=b"x"*17000)
    assert response.status_code == 413
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-request-id"]


def test_legacy_sqlite_bootstrap_preserves_audit_and_upgrades(tmp_path):
    from alembic import command
    from app.database import build_engine
    from app.migrate import config_for
    engine = build_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    with engine.begin() as db:
        command.upgrade(config_for(db), "0002")
        db.execute(text("INSERT INTO users (id,username,hashed_password,role,is_active) VALUES (1,'existing','hash','broker',1)"))
        db.execute(text("INSERT INTO audit_logs (user_id,action,timestamp,details) VALUES (1,'LOGIN','2026-01-01','preserve')"))
        db.execute(text("DROP TABLE alembic_version"))
    migrate_sqlite(engine)
    with engine.begin() as db:
        assert db.execute(text("SELECT details FROM audit_logs")).scalar_one() == "preserve"
        assert db.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0004"
        db.execute(text("INSERT INTO audit_logs (user_id,action,timestamp,details,ip_address) VALUES (NULL,'FAILED_LOGIN_ATTEMPT','2026-01-02','Credentials rejected','198.51.100.8')"))
    assert {"ip_address","request_id"} <= {c["name"] for c in inspect(engine).get_columns("audit_logs")}
    engine.dispose()


def test_unknown_legacy_schema_is_not_modified(tmp_path):
    from app.database import build_engine
    engine = build_engine(f"sqlite:///{tmp_path / 'unknown.db'}")
    with engine.begin() as db:
        db.execute(text("CREATE TABLE private_table (id INTEGER PRIMARY KEY, value TEXT)"))
        db.execute(text("INSERT INTO private_table VALUES (1,'keep')"))
    with pytest.raises(RuntimeError, match="Unrecognized"):
        migrate_sqlite(engine)
    with engine.connect() as db:
        assert db.execute(text("SELECT value FROM private_table")).scalar_one() == "keep"
    assert "alembic_version" not in inspect(engine).get_table_names()
    engine.dispose()
