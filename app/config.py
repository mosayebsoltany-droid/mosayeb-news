"""Validated environment settings. Secrets are never committed or shown in repr."""
from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

PROJECT_ROOT = Path(__file__).resolve().parent.parent
VERSION = "0.6.0"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="BROKER_", env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8", extra="ignore", hide_input_in_errors=True,
    )
    jwt_secret: SecretStr = SecretStr("")  # Missing disables login; public simulation can run.
    algorithm: Literal["HS256"] = "HS256"
    access_token_expire_minutes: int = Field(default=30, ge=1, le=120)
    database_url: SecretStr = SecretStr(f"sqlite:///{PROJECT_ROOT / 'broker.db'}")
    mock_registry_url: str = "http://mock-registry/submit"
    mock_failure_rate: float = Field(default=0.2, ge=0, le=1)
    registry_timeout_seconds: float = Field(default=5, gt=0, le=30)
    enable_demo: bool = True
    auto_create_tables: bool = True  # SQLite compatibility only; PostgreSQL uses Alembic.
    allowed_hosts: str = "localhost,127.0.0.1,testserver"
    cors_origins: str = ""

    @field_validator("jwt_secret")
    @classmethod
    def strong_secret(cls, value):
        if value.get_secret_value() and len(value.get_secret_value().encode()) < 32:
            raise ValueError("JWT secret must contain at least 32 bytes")
        return value

    @field_validator("database_url")
    @classmethod
    def database_driver(cls, value):
        url = make_url(value.get_secret_value())
        if url.drivername in {"postgresql", "postgres"}:
            url = url.set(drivername="postgresql+psycopg")
        if url.drivername not in {"sqlite", "sqlite+pysqlite", "postgresql+psycopg"}:
            raise ValueError("Use SQLite or postgresql+psycopg")
        return SecretStr(url.render_as_string(hide_password=False))

    @field_validator("mock_registry_url")
    @classmethod
    def mock_endpoint(cls, value):
        url = urlsplit(value)
        if (url.scheme not in {"http", "https"} or not url.hostname or url.username
                or url.password or url.query or url.fragment or not url.path):
            raise ValueError("Mock URL must be an HTTP(S) endpoint without credentials or query")
        if url.scheme == "http" and url.hostname not in {"mock-registry", "localhost", "127.0.0.1"}:
            raise ValueError("Remote mock endpoints require HTTPS")
        if url.hostname == "mock-registry" and value != "http://mock-registry/submit":
            raise ValueError("Use the built-in mock endpoint http://mock-registry/submit")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
