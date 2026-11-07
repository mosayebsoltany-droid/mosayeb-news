"""Account-scoped claim limits; login uses the actual network peer, not forwarded headers."""
import logging

from fastapi import Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from limits.errors import StorageError

from app.config import get_settings


def account_key(request: Request) -> str:
    user_id = getattr(request.state, "authenticated_user_id", None)
    return f"user:{user_id}" if user_id is not None else f"peer:{get_remote_address(request)}"


limiter = Limiter(key_func=account_key, headers_enabled=True,
                  storage_uri=get_settings().rate_limit_storage_uri.get_secret_value(),
                  key_prefix="broker-v1", swallow_errors=False,
                  storage_options={"wrap_exceptions": True, "socket_connect_timeout": 1, "socket_timeout": 1},
                  in_memory_fallback_enabled=False)


async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    # Full fixed-window duration is a safe upper bound for the remaining wait.
    retry_after = exc.limit.limit.get_expiry()
    return JSONResponse(status_code=429,
                        content={"detail": "تعداد درخواست‌ها از حد مجاز بیشتر است. کمی بعد تلاش کنید."},
                        headers={"Retry-After": str(retry_after)})


async def rate_storage_error_handler(request: Request, exc: StorageError):
    logging.getLogger("broker.limits").warning("rate_storage_unavailable")
    return JSONResponse(status_code=503, content={
        "detail": "سرویس کنترل نرخ موقتاً در دسترس نیست. کمی بعد تلاش کنید."
    }, headers={"Retry-After": "1"})
