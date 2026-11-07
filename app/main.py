from contextlib import asynccontextmanager
from pathlib import Path
import logging

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from app.config import VERSION, get_settings
from sqlalchemy import text

from app.core.logging import configure_logging
from app.core.security import configure_security
from app import models  # noqa: F401 — register models in Base.metadata
from app.database import Base, SessionLocal, engine
from app.routers import services, users
from app.routers.mock_registry import mock_registry
from app.schemas import HealthResponse
from app.services import router as services_router


@asynccontextmanager
async def lifespan(_app: FastAPI):
    configure_logging()
    if engine.dialect.name == "sqlite" and get_settings().auto_create_tables:
        Base.metadata.create_all(bind=engine)
    yield
    engine.dispose()


app = FastAPI(
    title="سامانه کارگزاری فنی و مهندسی ثبت اسناد — شبیه‌سازی",
    description="ورود JWT، ثبت ادعا، درخواست نقشه، پیگیری و PDF آزمایشی. ارتباط شبیه‌سازی‌شده با Retry و Circuit Breaker.",
    version=VERSION,
    lifespan=lifespan,
)

configure_security(app)

if get_settings().enable_demo:
    app.include_router(services_router)
app.include_router(users.router)
app.include_router(services.router)
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
    return {"status": "ok", "database": "connected", "mode": "simulation", "version": VERSION}


@app.get("/portal", response_class=FileResponse, include_in_schema=False)
def portal():
    return FileResponse(Path(__file__).with_name("portal.html"), media_type="text/html")
