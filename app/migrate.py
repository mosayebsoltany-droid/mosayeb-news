"""Migrate SQLite safely; adopt only an exact known legacy schema without history."""
from pathlib import Path
from tempfile import TemporaryDirectory

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import MetaData, create_engine, inspect, text

ROOT = Path(__file__).resolve().parent.parent


def config_for(connection):
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.attributes["connection"] = connection
    return cfg


def migrate_sqlite(engine):
    if engine.dialect.name != "sqlite":
        raise ValueError("This bootstrap is for SQLite only; use Alembic for PostgreSQL")
    with engine.begin() as connection:
        names = set(inspect(connection).get_table_names())
        cfg = config_for(connection)
        if names and "alembic_version" not in names:
            if connection.execute(text("SELECT 1 FROM sqlite_master WHERE type IN ('view','trigger') LIMIT 1")).first():
                raise RuntimeError("Custom SQLite schema requires migration review")
            adopted = None
            # Both prior create_all schemas and current fresh CLI-created schemas are known.
            for revision in ("0002", "head"):
                with TemporaryDirectory(prefix="broker-schema-") as directory:
                    reference = create_engine(f"sqlite:///{Path(directory) / 'reference.db'}")
                    try:
                        with reference.begin() as ref_connection:
                            command.upgrade(config_for(ref_connection), revision)
                            metadata = MetaData()
                            metadata.reflect(bind=ref_connection, only=lambda name, _: name != "alembic_version")
                        differences = compare_metadata(MigrationContext.configure(connection, opts={"compare_server_default": True}), metadata)
                        for table in metadata.tables:
                            actual = {(c.get("name"), " ".join(c["sqltext"].split())) for c in inspect(connection).get_check_constraints(table)} if table in names else set()
                            expected = {(c.name, " ".join(str(c.sqltext).split())) for c in metadata.tables[table].constraints if hasattr(c, "sqltext")}
                            if actual != expected:
                                differences.append(("check_constraint_mismatch", table))
                        if not differences:
                            adopted = revision
                            break
                    finally:
                        reference.dispose()
            if adopted is None:
                raise RuntimeError("Unrecognized SQLite schema; preserve the database and review migrations")
            command.stamp(cfg, adopted)
        command.upgrade(cfg, "head")


if __name__ == "__main__":
    from app.database import engine
    migrate_sqlite(engine)
