FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    BROKER_DATABASE_URL=sqlite:////data/broker.db
WORKDIR /app
COPY requirements.txt .
RUN apt-get update && apt-get install -y --no-install-recommends fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir -r requirements.txt \
    && useradd --system --uid 10001 broker \
    && install -d -o broker -g broker /data
COPY app ./app
COPY alembic.ini .
COPY migrations ./migrations
USER broker
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=20s CMD ["python", "-c", "from urllib.request import urlopen; urlopen('http://127.0.0.1:8000/health', timeout=2).close()"]
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
