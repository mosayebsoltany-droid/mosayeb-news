from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from sqlalchemy import text

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
    title="Real Estate Broker System — Simulation",
    description="Local simulation only; no connection to an official registry.",
    version="0.2.0",
    lifespan=lifespan,
)

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
