from contextlib import asynccontextmanager, suppress
import asyncio
from pathlib import Path
import logging

from fastapi import FastAPI, Request
from fastapi.openapi.docs import get_swagger_ui_html, get_swagger_ui_oauth2_redirect_html
from app.core.pages import nonce_html, local_page
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from app.config import VERSION, get_settings
from sqlalchemy import text

from app.core.logging import configure_logging
from app.core.security import configure_security
from app import models  # noqa: F401 — register models in Base.metadata
from app.database import Base, SessionLocal, engine
from app.routers import admin, analytics, external_services, notifications, payments, services, users
from app.worker import run_worker
from app.core.rate_limit import limiter, rate_limit_handler, rate_storage_error_handler
from limits.errors import StorageError
from slowapi.errors import RateLimitExceeded
from app.routers.mock_registry import mock_registry
from app.schemas import HealthResponse
from app.services import router as services_router


@asynccontextmanager
async def lifespan(_app: FastAPI):
    configure_logging()
    if engine.dialect.name == "sqlite" and get_settings().auto_create_tables:
        from app.migrate import migrate_sqlite
        migrate_sqlite(engine)
    worker = (asyncio.create_task(run_worker(SessionLocal))
              if get_settings().notification_worker_enabled else None)
    try:
        yield
    finally:
        if worker is not None:
            worker.cancel()
            with suppress(asyncio.CancelledError):
                await worker
        engine.dispose()


app = FastAPI(
    title="سامانه کارگزاری فنی و مهندسی ثبت اسناد — شبیه‌سازی",
    description="ورود JWT، ثبت ادعا، درخواست نقشه، پیگیری و PDF آزمایشی. ارتباط شبیه‌سازی‌شده با Retry و Circuit Breaker.",
    version=VERSION,
    docs_url=None, redoc_url=None,
    lifespan=lifespan,
)

configure_security(app)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_handler)
app.add_exception_handler(StorageError, rate_storage_error_handler)

if get_settings().enable_demo:
    app.include_router(services_router)
app.include_router(users.router)
app.include_router(analytics.router)
app.include_router(admin.router)
app.include_router(external_services.router)
app.include_router(notifications.router)
app.include_router(services.router)
app.include_router(payments.router)
app.mount('/mock-registry', mock_registry)


@app.get("/", response_model=HealthResponse)
def root():
    return HealthResponse(status="ok", mode="simulation")


@app.get("/live", tags=["Monitoring"], summary="Process liveness")
def live():
    return {"status": "ok", "version": VERSION}


@app.get("/ready", tags=["Monitoring"], summary="Database readiness",
         responses={503: {"description": "Database unavailable"}})
@app.get("/health", tags=["Monitoring"], summary="Service and database health",
         responses={503: {"description": "Database unavailable"}})
def health():
    try:
        with SessionLocal() as session:
            session.execute(text("SELECT 1"))
    except SQLAlchemyError:
        logging.getLogger("broker.errors").warning("database_readiness_failed")
        return JSONResponse(status_code=503, content={
            "status": "unhealthy", "database": "disconnected",
            "mode": "simulation", "version": VERSION,
        })
    try:
        rate_ready = limiter._storage.check()
    except StorageError:
        rate_ready = False
    if not rate_ready:
        return JSONResponse(status_code=503, content={
            "status": "unhealthy", "database": "connected", "rate_limit": "unavailable",
            "mode": "simulation", "version": VERSION,
        })
    return {"status": "ok", "database": "connected", "mode": "simulation", "version": VERSION}


@app.get("/portal", response_class=FileResponse, include_in_schema=False)
def portal(request: Request):
    return local_page("portal.html", request)


@app.get("/payments", response_class=FileResponse, include_in_schema=False)
def payments_ui(request: Request):
    return local_page("payments.html", request)


@app.get("/admin", response_class=FileResponse, include_in_schema=False)
def admin_ui(request: Request):
    return local_page("admin.html", request)


@app.get("/docs", include_in_schema=False)
def swagger_docs(request: Request):
    html = get_swagger_ui_html(openapi_url=app.openapi_url, title=app.title + " - Swagger UI",
                               oauth2_redirect_url="/docs/oauth2-redirect",
                               swagger_favicon_url="/favicon.ico")
    return nonce_html(html.body.decode("utf-8"), request)


@app.get("/docs/oauth2-redirect", include_in_schema=False)
def swagger_redirect(request: Request):
    return nonce_html(get_swagger_ui_oauth2_redirect_html().body.decode("utf-8"), request)


@app.get("/favicon.ico", include_in_schema=False, status_code=204)
def favicon():
    from fastapi import Response
    return Response(status_code=204)
