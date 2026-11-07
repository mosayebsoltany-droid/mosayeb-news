import pytest
from app.config import get_settings


@pytest.fixture(autouse=True)
def isolated_settings_cache(monkeypatch):
    from app.core.rate_limit import limiter
    limiter.reset()
    monkeypatch.setenv("BROKER_NOTIFICATION_WORKER_ENABLED", "false")
    get_settings.cache_clear()
    yield
    limiter.reset()
    get_settings.cache_clear()
