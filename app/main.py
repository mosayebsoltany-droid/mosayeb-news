from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import text

from app import models  # noqa: F401 — register models in Base.metadata
from app.database import Base, SessionLocal, engine
from app.schemas import HealthResponse


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield
    engine.dispose()


app = FastAPI(
    title="Real Estate Broker System — Simulation",
    description="Step 1. Local simulation only; no connection to an official registry.",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/", response_model=HealthResponse)
def root():
    return HealthResponse(status="ok", mode="simulation")


@app.get("/health", response_model=HealthResponse)
def health():
    with SessionLocal() as session:
        session.execute(text("SELECT 1"))
    return HealthResponse(status="ok", mode="simulation")
