# Build stage
FROM python:3.11-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends gcc && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml requirements.txt ./
RUN pip install --no-cache-dir --user -r requirements.txt

# Runtime stage
FROM python:3.11-slim

# Run as non-root user for defence-in-depth
RUN useradd --create-home --shell /bin/bash wiuser

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /root/.local /home/wiuser/.local
ENV PATH=/home/wiuser/.local/bin:$PATH

# Copy application code (no .env, no secrets)
COPY app/ ./app/
COPY migrations/ ./migrations/
COPY alembic.ini ./

ENV PYTHONPATH=/app
# DATABASE_URL must be provided at runtime — no default baked in
ENV SNAPSHOT_STORAGE_DIR=/app/snapshots
ENV PRODUCTION_MODE=true

# Create data directories and give wiuser ownership
RUN mkdir -p /app/snapshots && chown -R wiuser:wiuser /app

USER wiuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
