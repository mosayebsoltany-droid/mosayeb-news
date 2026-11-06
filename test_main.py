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
    assert response.json() == {"status": "ok", "mode": "simulation"}
""",
        ],
        env={**os.environ, "BROKER_DATABASE_URL": f"sqlite:///{database}"},
        cwd=Path(__file__).resolve().parent,
        check=True,
    )
    with sqlite3.connect(database) as connection:
        rows = connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        assert {"users", "audit_logs"} <= {name for (name,) in rows}
