"""Run inside the isolated Compose broker; all credentials and data are test-only."""
from uuid import uuid4

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
        # One initial claim plus four more exhaust this account's quota in shared Redis.
        for _ in range(4):
            assert client.post("/services/claims", json={"national_id": "0123456789", "claim_type": "demo"}).status_code == 201
        limited = client.post("/services/claims", json={"national_id": "0123456789", "claim_type": "demo"})
        assert limited.status_code == 429 and limited.headers.get("retry-after")
        assert client.get("/services/track/" + code).json()["status"] == "success"
        assert client.get("/services/certificate/" + code).content.startswith(b"%PDF")
        admin_token = client.post("/auth/token", data={"username": name+"-admin", "password": password}).json()["access_token"]
        stats = client.get("/analytics/dashboard", headers={"Authorization": "Bearer "+admin_token})
        assert stats.status_code == 200 and stats.json()["successful_requests"] >= 5
    with SessionLocal() as db:
        assert db.scalar(select(AuditLog.id).where(AuditLog.action == "CLAIM_SUCCESS", AuditLog.details == code))
    print("PostgreSQL Compose: login, claim, tracking, PDF, audit and account rate limit passed")


if __name__ == "__main__":
    main()
