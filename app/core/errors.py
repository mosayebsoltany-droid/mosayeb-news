import logging
from uuid import uuid4

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

logger = logging.getLogger("broker.errors")
SAFE_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
    "Cache-Control": "no-store",
}


def request_id(request: Request) -> str:
    identifier = getattr(request.state, "request_id", None)
    if identifier is None:
        identifier = uuid4().hex
        request.state.request_id = identifier
    return identifier


def safe_route(request: Request) -> str:
    route = request.scope.get("route")
    return getattr(route, "path", "<unmatched>")


async def validation_exception_handler(request: Request, exc: RequestValidationError):
    identifier = request_id(request)
    # Never return or log submitted values, exception context, or query strings.
    errors = [
        {"loc": list(error["loc"]), "type": error["type"]}
        for error in exc.errors()
    ]
    logger.warning("validation_error id=%s method=%s route=%s",
                   identifier, request.method, safe_route(request))
    return JSONResponse(
        status_code=422,
        content={"detail": "داده‌های ارسالی نامعتبر است. لطفاً قالب فیلدها را بررسی کنید.",
                 "errors": errors, "request_id": identifier},
        headers={**SAFE_HEADERS, "X-Request-ID": identifier},
    )


async def global_exception_handler(request: Request, exc: Exception):
    identifier = request_id(request)
    logger.error("unhandled_error id=%s kind=%s method=%s route=%s",
                 identifier, type(exc).__name__, request.method, safe_route(request))
    headers = {**SAFE_HEADERS, "X-Request-ID": identifier}
    # ServerErrorMiddleware is outside FastAPI's CORS middleware.
    origin = request.headers.get("origin")
    if origin and origin in getattr(request.app.state, "cors_origins", ()):
        headers["Access-Control-Allow-Origin"] = origin
        headers["Vary"] = "Origin"
    return JSONResponse(
        status_code=500,
        content={"detail": "خطای داخلی سرور رخ داده است.",
                 "request_id": identifier},
        headers=headers,
    )
