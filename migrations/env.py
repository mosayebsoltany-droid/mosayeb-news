from alembic import context

from app.config import get_settings
from app.database import Base, build_engine
from app import models, services  # noqa: F401 — register all five tables

config = context.config
target_metadata = Base.metadata
url = get_settings().database_url.get_secret_value()

if context.is_offline_mode():
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True,
                      dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()
else:
    supplied = config.attributes.get("connection")
    def migrate(connection):
        context.configure(connection=connection, target_metadata=target_metadata,
                          compare_type=True, render_as_batch=connection.dialect.name == "sqlite")
        with context.begin_transaction():
            context.run_migrations()
    if supplied is not None:
        migrate(supplied)
    else:
        engine = build_engine(url)
        try:
            with engine.connect() as connection:
                migrate(connection)
        finally:
            engine.dispose()
