from os import getenv
from uuid import uuid4
from urllib.parse import urlsplit

from fastapi.exceptions import RequestValidationError
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

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

        async def secure_send(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                required = {**SAFE_HEADERS, "X-Request-ID": identifier}
                replaced = {key.lower().encode("ascii") for key in required}
                headers = [(key, value) for key, value in headers if key.lower() not in replaced]
                headers.extend((key.lower().encode("ascii"), value.encode("ascii"))
                               for key, value in required.items())
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, secure_send)


def csv_setting(name: str, default: str = "") -> list[str]:
    return [part.strip() for part in getenv(name, default).split(",") if part.strip()]


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
    app.add_middleware(
        CORSMiddleware, allow_origins=origins, allow_credentials=False,
        allow_methods=["GET", "POST"], allow_headers=["Authorization", "Content-Type"],
    )
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=hosts, www_redirect=False)
    app.add_middleware(SecurityHeadersMiddleware)
