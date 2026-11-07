import io
import json
import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.logging import configure_logging
from app.core.security import configure_security
from test_main import broker


def test_json_logging_is_idempotent_and_redacts_extras():
    stream = io.StringIO()
    logger = configure_logging(stream)
    logger = logging.getLogger("broker")
    configure_logging(stream)
    assert sum(getattr(h, "broker_json_handler", False) for h in logger.handlers) == 1
    try:
        try:
            raise RuntimeError("private-exception-value")
        except RuntimeError:
            logging.getLogger("broker.errors").error("unexpected_error", exc_info=True, extra={
                "error_kind": "RuntimeError", "password": "private-password-value",
            })
        result = json.loads(stream.getvalue())
        assert result["levelname"] == "ERROR"
        assert result["error_kind"] == "RuntimeError"
        assert "timestamp" in result
        assert "private" not in stream.getvalue()
        assert "password" not in result and "exc_info" not in result
    finally:
        configure_logging()


def test_json_access_log_redacts_input_and_matches_response(broker):
    client, _ = broker
    stream = io.StringIO()
    configure_logging(stream)
    try:
        response = client.get("/services/track/private-tracking-value?token=private-token-value")
        assert response.status_code == 401
        record = json.loads(stream.getvalue().splitlines()[-1])
        assert record["route"] == "/services/track/{tracking_code}"
        assert record["request_id"] == response.headers["x-request-id"]
        assert record["status"] == 401
        assert record["duration_ms"] >= 0
        assert "private" not in stream.getvalue()
    finally:
        configure_logging()


def test_json_validation_and_server_errors_do_not_include_input():
    app = FastAPI()
    configure_security(app)
    @app.get("/boom")
    def boom():
        raise RuntimeError("private-error-value")
    stream = io.StringIO()
    configure_logging(stream)
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/boom?token=private-query-value")
        records = [json.loads(line) for line in stream.getvalue().splitlines()]
        error = next(r for r in records if r["message"] == "unhandled_error")
        assert error["request_id"] == response.headers["x-request-id"]
        assert error["error_kind"] == "RuntimeError"
        assert "private" not in stream.getvalue()
        assert any(r.get("status") == 500 for r in records)
    finally:
        configure_logging()
