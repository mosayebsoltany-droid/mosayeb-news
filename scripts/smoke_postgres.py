"""Run inside the isolated Compose broker; all credentials and data are test-only."""
from uuid import uuid4
import time

import httpx
from sqlalchemy import select

from app.auth import passwords
from app.database import SessionLocal
from app.models import AuditLog, User, UserRole


def main():
    name = "smoke-" + uuid4().hex[:12]
    password = uuid4().hex
    with SessionLocal() as db:
        db.add(User(username=name, hashed_password=passwords.hash(password)))
        db.add(User(username=name+"-admin", hashed_password=passwords.hash(password), role=UserRole.admin))
        db.commit()
    with httpx.Client(base_url="http://127.0.0.1:8000", timeout=25, trust_env=False) as client:
        assert client.get("/ready").status_code == 200
        assert client.post("/api/demo/requests", json={}).status_code == 404
        token = client.post("/auth/token", data={"username": name, "password": password})
        assert token.status_code == 200
        client.headers["Authorization"] = "Bearer " + token.json()["access_token"]
        claim = client.post("/services/claims", json={"national_id": "0123456789", "claim_type": "demo"})
        assert claim.status_code == 201, claim.status_code
        code = claim.json()["tracking_code"]
        event_id = claim.headers["x-simulated-notification-id"]
        # One initial claim plus four more exhaust this account's quota in shared Redis.
        for _ in range(4):
            assert client.post("/services/claims", json={"national_id": "0123456789", "claim_type": "demo"}).status_code == 201
        limited = client.post("/services/claims", json={"national_id": "0123456789", "claim_type": "demo"})
        assert limited.status_code == 429 and limited.headers.get("retry-after")
        assert client.get("/services/track/" + code).json()["status"] == "success"
        assert client.get("/services/certificate/" + code).status_code == 402
        payment = client.post("/payments/request", json={"tracking_code": code}).json()
        authority = payment["authority"]
        body = {"tracking_code": code, "authority": authority, "status": "OK"}
        assert client.post("/payments/verify", json=body).status_code == 409
        assert client.post("/payments/simulate", json={"authority": authority, "outcome": "OK"}).status_code == 200
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(lambda _: client.post("/payments/verify", json=body).status_code, range(2)))
        assert outcomes == [200, 200], outcomes
        with SessionLocal() as db:
            audits = list(db.scalars(select(AuditLog.id).where(AuditLog.action == "PAYMENT_SUCCESS", AuditLog.details == code)))
            assert len(audits) == 1
        assert client.get("/services/certificate/" + code).content.startswith(b"%PDF")
        admin_token = client.post("/auth/token", data={"username": name+"-admin", "password": password}).json()["access_token"]
        stats = client.get("/analytics/dashboard", headers={"Authorization": "Bearer "+admin_token})
        assert stats.status_code == 200 and stats.json()["successful_requests"] >= 5
        rejected = client.post("/auth/token", data={"username": "missing-security-fixture", "password": "wrong-test-only"})
        assert rejected.status_code == 401
        logs = client.get("/admin/audit-logs", headers={"Authorization": "Bearer "+admin_token})
        assert logs.status_code == 200
        assert any(row["action"] == "FAILED_LOGIN_ATTEMPT" and row["user_id"] is None and row["ip_address"] for row in logs.json())
        assert "wrong-test-only" not in logs.text and "missing-security-fixture" not in logs.text
        chart = client.get("/admin/analytics/chart-data", headers={"Authorization": "Bearer "+admin_token})
        assert chart.status_code == 200 and len(chart.json()["labels"]) == 7
        assert client.get("/admin").status_code == 200
        for _ in range(30):
            event = client.get("/notifications/"+event_id).json()
            if event["status"] == "completed":
                break
            time.sleep(0.2)
        assert event["status"] == "completed" and event["receipt"].startswith("SIM-SMS-")
    with SessionLocal() as db:
        assert db.scalar(select(AuditLog.id).where(AuditLog.action == "CLAIM_SUCCESS", AuditLog.details == code))
    print("PostgreSQL Compose: login, claim, tracking, PDF, audit and account rate limit passed")


if __name__ == "__main__":
    main()
