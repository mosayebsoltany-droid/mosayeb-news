from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import PROJECT_ROOT, get_settings


def enable_foreign_keys(dbapi_connection, _connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def build_engine(database_url: str):
    backend = make_url(database_url).get_backend_name()
    arguments = {"check_same_thread": False, "timeout": 3} if backend == "sqlite" else {
        "connect_timeout": 3, "options": "-c statement_timeout=3000",
    }
    result = create_engine(database_url, connect_args=arguments, pool_pre_ping=True,
                           pool_timeout=3)
    if backend == "sqlite":
        event.listen(result, "connect", enable_foreign_keys)
    return result


DATABASE_URL = get_settings().database_url.get_secret_value()
engine = build_engine(DATABASE_URL)


class Base(DeclarativeBase):
    pass


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session
