# ── Builder stage ─────────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.prod.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.prod.txt

# ── Final stage ───────────────────────────────────────────────────────────────
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Runtime-only system deps; gosu used in entrypoint to drop root → app
RUN apt-get update && apt-get install -y --no-install-recommends \
        postgresql-client \
        netcat-traditional \
        curl \
        gosu \
    && rm -rf /var/lib/apt/lists/*

# Copy installed Python packages from builder (no build tools in final image)
COPY --from=builder /install /usr/local

# Non-root application user (uid/gid 10001 avoids collision with common system UIDs)
RUN groupadd -g 10001 app && useradd -u 10001 -g app -m -s /bin/false app

WORKDIR /app

COPY . .

# Create writable directories; named volumes inherit this ownership on first create
RUN mkdir -p /app/staticfiles /app/media /app/logs \
    && chown -R app:app /app

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Entrypoint runs as root to fix bind-mount permissions then execs as app via gosu
ENTRYPOINT ["/entrypoint.sh"]
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000"]
