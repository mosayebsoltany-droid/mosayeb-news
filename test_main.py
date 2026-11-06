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
