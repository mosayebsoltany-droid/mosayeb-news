"""JSON application logs on stdout; collectors can ship them without app credentials."""
import logging
import sys
from datetime import datetime, timezone

from pythonjsonlogger.json import JsonFormatter


class SafeJsonFormatter(JsonFormatter):
    def process_log_record(self, record):
        # Do not serialize exception traces, arbitrary extra fields or request data.
        allowed = ("levelname", "name", "message", "request_id", "method", "route",
                   "status", "duration_ms", "error_kind")
        output = {key: record[key] for key in allowed if key in record}
        output["timestamp"] = datetime.now(timezone.utc).isoformat()
        return output


def configure_logging(stream=None):
    logger = logging.getLogger("broker")
    for handler in list(logger.handlers):
        if getattr(handler, "broker_json_handler", False):
            logger.removeHandler(handler)
            handler.close()
    handler = logging.StreamHandler(stream if stream is not None else sys.stdout)
    handler.broker_json_handler = True
    handler.setFormatter(SafeJsonFormatter("%(levelname)s %(name)s %(message)s", json_ensure_ascii=False))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
