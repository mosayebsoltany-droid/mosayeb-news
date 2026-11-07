import logging
from time import monotonic
from uuid import uuid4
from secrets import token_urlsafe
from app.core.headers import response_headers
from app.core.body_limit import RequestBodyLimitMiddleware
from urllib.parse import urlsplit

from fastapi.exceptions import RequestValidationError
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.config import get_settings
from app.core.errors import (
    SAFE_HEADERS, global_exception_handler, validation_exception_handler,
)


class SecurityHeadersMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        identifier = uuid4().hex
        scope.setdefault("state", {})["request_id"] = identifier
        scope["state"]["csp_nonce"] = token_urlsafe(24)

        started = monotonic()
        status = 500

        async def secure_send(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                headers = list(message.get("headers", []))
                required = response_headers(scope, identifier)
                replaced = {key.lower().encode("ascii") for key in required}
                headers = [(key, value) for key, value in headers if key.lower() not in replaced]
                headers.extend((key.lower().encode("ascii"), value.encode("ascii"))
                               for key, value in required.items())
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, secure_send)
        finally:
            route = getattr(scope.get("route"), "path", "<unmatched>")
            logging.getLogger("broker.access").info("request_completed", extra={
                "request_id": identifier, "method": scope.get("method"),
                "route": route, "status": status,
                "duration_ms": round((monotonic() - started) * 1000, 2),
            })


def csv_setting(name: str, default: str = "") -> list[str]:
    return [part.strip() for part in getattr(get_settings(), name.removeprefix("BROKER_").lower(), default).split(",") if part.strip()]


def configure_security(app):
    hosts = csv_setting("BROKER_ALLOWED_HOSTS", "localhost,127.0.0.1,testserver")
    origins = csv_setting("BROKER_CORS_ORIGINS")
    if not hosts or "*" in hosts:
        raise ValueError("BROKER_ALLOWED_HOSTS must contain explicit hosts")
    parsed = [urlsplit(origin) for origin in origins]
    if any(
        "*" in origin or parts.username or parts.password or parts.path
        or parts.query or parts.fragment or not parts.hostname
        or not (parts.scheme == "https" or (
            parts.scheme == "http" and parts.hostname in {"localhost", "127.0.0.1"}
        ))
        for origin, parts in zip(origins, parsed)
    ):
        raise ValueError("BROKER_CORS_ORIGINS must contain explicit origins")
    app.state.cors_origins = origins
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, global_exception_handler)
    app.add_middleware(RequestBodyLimitMiddleware)
    app.add_middleware(
        CORSMiddleware, allow_origins=origins, allow_credentials=False,
        allow_methods=["GET", "POST"], allow_headers=["Authorization", "Content-Type"],
    )
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=hosts, www_redirect=False)
    app.add_middleware(SecurityHeadersMiddleware)
