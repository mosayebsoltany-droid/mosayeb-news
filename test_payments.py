"""Payment workflow invariants on isolated databases; no real money or bank calls."""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, event, select, text
from alembic import command

from app.database import enable_foreign_keys
from app.migrate import config_for, migrate_sqlite
from app.models import AuditLog, DocumentRequest, PaymentTransaction
from app.routers.payments import now
from test_main import accounts, broker, login, pay_mock, CLAIM


def successful_case(client, headers):
    with patch("app.routers.mock_registry.random", return_value=1):
        response = client.post("/services/claims", json=CLAIM, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()["tracking_code"]


def request_payment(client, code, headers):
    result = client.post("/payments/request", json={"tracking_code": code}, headers=headers)
    assert result.status_code == 200, result.text
    return result.json()["authority"]


def test_payment_auth_ownership_and_no_callback_forgery(accounts):
    client, sessions = accounts
    alice, bob = login(client, "alice"), login(client, "bob")
    code = successful_case(client, alice)
    body = {"tracking_code": code}
    assert client.post("/payments/request", json=body).status_code == 401
    assert client.post("/payments/request", json=body, headers=bob).status_code == 404
    authority = request_payment(client, code, alice)
    callback = {"tracking_code": code, "authority": authority, "status": "OK"}
    assert client.post("/payments/verify", json=callback).status_code == 401
    assert client.post("/payments/verify", json=callback, headers=bob).status_code == 404
    assert client.post("/payments/verify", json=callback, headers=alice).status_code == 409
    assert client.post("/payments/simulate", json={"authority": authority, "outcome": "OK"}, headers=bob).status_code == 404
    assert client.get("/payments/mock-bank-page", params={"authority": authority}, headers=bob).status_code == 404
    assert client.get("/services/certificate/"+code, headers=alice).status_code == 402
    with sessions() as db:
        assert db.scalar(select(DocumentRequest.payment_status)) == "unpaid"
        assert not db.scalar(select(AuditLog.id).where(AuditLog.action == "PAYMENT_SUCCESS"))


@pytest.mark.parametrize("amount,expected", [(0,422),(-1,422),(True,422),("50000",422),(1,400),(50001,400),(50000,200)])
def test_server_owns_positive_irr_tariff(accounts, amount, expected):
    client, _ = accounts
    headers = login(client, "alice")
    code = successful_case(client, headers)
    response = client.post("/payments/request", json={"tracking_code":code,"amount":amount}, headers=headers)
    assert response.status_code == expected, response.text
    if expected == 200:
        assert response.json()["currency"] == "IRR" and response.json()["amount"] == 50000
        assert response.json()["payment_url"].startswith("/payments/mock-bank-page?")


def test_success_idempotence_tracking_binding_and_pdf(accounts):
    client, sessions = accounts
    headers = login(client, "alice")
    code = successful_case(client, headers)
    authority = pay_mock(client, code, headers)
    body = {"tracking_code":code,"authority":authority,"status":"OK"}
    for _ in range(3):
        assert client.post("/payments/verify", json=body, headers=headers).status_code == 200
    other = successful_case(client, headers)
    assert client.post("/payments/verify", json={**body,"tracking_code":other}, headers=headers).status_code == 404
    assert client.get("/services/certificate/"+other, headers=headers).status_code == 402
    assert client.post("/payments/request", json={"tracking_code":code}, headers=headers).status_code == 409
    assert client.get("/services/track/"+code, headers=headers).json()["payment_status"] == "paid"
    assert client.get("/services/certificate/"+code, headers=headers).content.startswith(b"%PDF")
    with sessions() as db:
        assert len(list(db.scalars(select(AuditLog).where(AuditLog.action == "PAYMENT_SUCCESS")))) == 1
        assert len(list(db.scalars(select(PaymentTransaction).where(PaymentTransaction.status == "success")))) == 1


def test_cancel_is_terminal_and_retry_gets_new_authority(accounts):
    client, _ = accounts
    headers = login(client, "alice")
    code = successful_case(client, headers)
    authority = request_payment(client, code, headers)
    assert request_payment(client, code, headers) == authority
    assert client.post("/payments/simulate", json={"authority":authority,"outcome":"NOK"}, headers=headers).status_code == 200
    assert client.post("/payments/simulate", json={"authority":authority,"outcome":"OK"}, headers=headers).status_code == 409
    body={"tracking_code":code,"authority":authority,"status":"OK"}
    assert client.post("/payments/verify", json=body, headers=headers).status_code == 400
    assert client.post("/payments/verify", json=body, headers=headers).status_code == 409
    assert client.get("/services/certificate/"+code, headers=headers).status_code == 402
    assert request_payment(client, code, headers) != authority


def test_expiry_and_competing_authorities_cannot_double_finalize(accounts):
    client, sessions = accounts
    headers = login(client, "alice")
    code = successful_case(client, headers)
    first = request_payment(client, code, headers)
    with sessions() as db:
        transaction = db.scalar(select(PaymentTransaction).where(PaymentTransaction.authority == first))
        transaction.expires_at = now()-timedelta(seconds=1)
        db.commit()
    assert client.post("/payments/simulate", json={"authority":first,"outcome":"OK"}, headers=headers).status_code == 409
    assert client.post("/payments/verify", json={"tracking_code":code,"authority":first}, headers=headers).status_code == 409
    second = request_payment(client, code, headers)
    assert first != second
    # Fixture emulates two overlapping request creations from separate workers.
    with sessions() as db:
        db.scalar(select(PaymentTransaction).where(PaymentTransaction.authority == first)).expires_at = now()+timedelta(minutes=20)
        db.commit()
    for authority in (first,second):
        assert client.post("/payments/simulate", json={"authority":authority,"outcome":"OK"}, headers=headers).status_code == 200
    assert client.post("/payments/verify", json={"tracking_code":code,"authority":second}, headers=headers).status_code == 200
    assert client.post("/payments/verify", json={"tracking_code":code,"authority":first}, headers=headers).status_code == 409
    with sessions() as db:
        assert len(list(db.scalars(select(AuditLog.id).where(AuditLog.action == "PAYMENT_SUCCESS")))) == 1


def test_audit_failure_rolls_back_payment_and_document(accounts):
    client, sessions = accounts
    headers = login(client, "alice")
    code = successful_case(client, headers)
    authority = request_payment(client, code, headers)
    client.post("/payments/simulate", json={"authority":authority,"outcome":"OK"}, headers=headers)
    with patch("app.routers.payments.audit", side_effect=RuntimeError("audit failure")):
        with pytest.raises(RuntimeError):
            client.post("/payments/verify", json={"tracking_code":code,"authority":authority}, headers=headers)
    with sessions() as db:
        assert db.scalar(select(DocumentRequest.payment_status)) == "unpaid"
        assert db.scalar(select(PaymentTransaction.status)) == "pending"


def test_migration_preserves_existing_case_and_notification(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path/'old.db'}")
    event.listen(engine, "connect", enable_foreign_keys)
    with engine.begin() as db:
        command.upgrade(config_for(db), "0003")
        db.execute(text("INSERT INTO users (id,username,hashed_password,role,is_active) VALUES (1,'old','hash','broker',1)"))
        db.execute(text("INSERT INTO document_requests (id,tracking_code,user_id,request_type,status,created_at) VALUES (1,'OLD',1,'claim','success',CURRENT_TIMESTAMP)"))
        db.execute(text("INSERT INTO notification_events (id,document_request_id,user_id,status,attempts,available_at,created_at) VALUES ('event',1,1,'pending',0,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"))
        db.execute(text("INSERT INTO audit_logs (user_id,action,timestamp) VALUES (1,'OLD_LOG',CURRENT_TIMESTAMP)"))
    migrate_sqlite(engine)
    with engine.connect() as db:
        assert db.execute(text("SELECT payment_status FROM document_requests WHERE tracking_code='OLD'")).scalar_one() == "unpaid"
        assert db.execute(text("SELECT id FROM notification_events")).scalar_one() == "event"
        assert db.execute(text("SELECT action FROM audit_logs")).scalar_one() == "OLD_LOG"
        assert not db.execute(text("PRAGMA foreign_key_check")).all()
    engine.dispose()


def test_payment_ui_no_cookie_or_local_storage_and_nonce(broker):
    client, _ = broker
    page = client.get("/payments")
    assert page.status_code == 200 and "هیچ وجهی جابه‌جا نمی‌شود" in page.text
    assert "localStorage" not in page.text and "sessionStorage" not in page.text
    assert "'nonce-" in page.headers["content-security-policy"]


def test_failed_case_cannot_start_payment(accounts):
    client, _ = accounts
    headers = login(client, "alice")
    with patch("app.routers.mock_registry.random", return_value=0):
        failed = client.post("/services/claims", json=CLAIM, headers=headers)
    assert failed.status_code == 503
    assert client.post("/payments/request", json={"tracking_code":failed.json()["tracking_code"]}, headers=headers).status_code == 409
