FROM python:3.12-slim AS base

FROM base AS builder
WORKDIR /build
COPY requirements.txt .
RUN python -m pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt \
    && python -m venv /opt/venv \
    && /opt/venv/bin/python -m pip install --no-cache-dir --no-index --find-links=/wheels -r requirements.txt

FROM base AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    BROKER_DATABASE_URL=sqlite:////data/broker.db \
    PATH="/opt/venv/bin:$PATH"
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --system --user-group --uid 10001 broker \
    && install -d -o broker -g broker /data
COPY --from=builder /opt/venv /opt/venv
COPY requirements.txt .
COPY app ./app
COPY alembic.ini .
COPY migrations ./migrations
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=4s --start-period=20s CMD ["python", "-c", "from urllib.request import urlopen; urlopen('http://127.0.0.1:8000/ready', timeout=3).close()"]
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--log-config", "app/uvicorn_logging.json"]
