from contextlib import asynccontextmanager
from pathlib import Path
from os import getenv

from fastapi import FastAPI
from fastapi.responses import FileResponse
from sqlalchemy import text

from app.core.security import configure_security
from app import models  # noqa: F401 — register models in Base.metadata
from app.database import Base, SessionLocal, engine
from app.routers import services, users
from app.routers.mock_registry import mock_registry
from app.schemas import HealthResponse
from app.services import router as services_router


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield
    engine.dispose()


app = FastAPI(
    title="سامانه کارگزاری فنی و مهندسی ثبت اسناد — شبیه‌سازی",
    description="ورود JWT، ثبت ادعا، درخواست نقشه، پیگیری و PDF آزمایشی. ارتباط شبیه‌سازی‌شده با Retry و Circuit Breaker.",
    version="0.4.0",
    lifespan=lifespan,
)

configure_security(app)

if getenv("BROKER_ENABLE_DEMO", "true").lower() == "true":
    app.include_router(services_router)
app.include_router(users.router)
app.include_router(services.router)
app.mount('/mock-registry', mock_registry)


@app.get("/", response_model=HealthResponse)
def root():
    return HealthResponse(status="ok", mode="simulation")


@app.get("/health", response_model=HealthResponse)
def health():
    with SessionLocal() as session:
        session.execute(text("SELECT 1"))
    return HealthResponse(status="ok", mode="simulation")


@app.get("/portal", response_class=FileResponse, include_in_schema=False)
def portal():
    return FileResponse(Path(__file__).with_name("portal.html"), media_type="text/html")
