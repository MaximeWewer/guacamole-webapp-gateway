# =============================================================================
# Stage 1: Build — install all Python dependencies
# =============================================================================
FROM python:3.14-slim AS builder

WORKDIR /build

# Install build dependencies for compiled packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# Install into a virtual environment for clean copy to runtime stage
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN pip install --no-cache-dir -r requirements.txt

# =============================================================================
# Stage 2: Runtime — lean production image
# =============================================================================
FROM python:3.14-slim

# OCI standard labels
LABEL org.opencontainers.image.title="guacamole-webapp-gateway"
LABEL org.opencontainers.image.description="Session broker for Guacamole VNC container lifecycle management"
LABEL org.opencontainers.image.source="https://github.com/MaximeWewer/guacamole-webapp-gateway"
LABEL org.opencontainers.image.vendor="MaximeWewer"

# Create non-root user with docker socket access (for Docker orchestrator mode)
ARG DOCKER_GID=999
RUN groupadd -r -g ${DOCKER_GID} docker && \
    groupadd -r broker && \
    useradd -r -g broker -G docker broker

WORKDIR /app

# Runtime system dependencies
#   libpq5       — PostgreSQL client library (psycopg2)
#   curl         — HEALTHCHECK probe
#   tini         — PID 1 init for proper signal handling
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    tini \
    && rm -rf /var/lib/apt/lists/*

# Copy virtual environment from builder (excludes dev/test packages build artifacts)
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy application
COPY . /app/broker/
RUN cp /app/broker/app.py /app/app.py

# Create data directories with correct permissions
RUN mkdir -p /data/config /data/users && \
    chown -R broker:broker /data /app

# Run as non-root user
USER broker

# ---- Environment variable reference ----
# Guacamole connection
#   GUACAMOLE_URL               — Guacamole base URL (e.g. http://guacamole:8080/guacamole)
#   GUACAMOLE_ADMIN_USER        — Guacamole admin username
#   GUACAMOLE_ADMIN_PASSWORD    — Guacamole admin password
# Database
#   DATABASE_HOST / DATABASE_PORT / DATABASE_NAME / DATABASE_USER / DATABASE_PASSWORD
#   DB_POOL_MIN                 — Minimum pool connections (default: 2)
#   DB_POOL_MAX                 — Maximum pool connections (default: 8)
# Authentication
#   BROKER_API_KEY              — API key for authenticating requests
# Logging
#   LOG_LEVEL                   — DEBUG, INFO, WARNING, ERROR (default: INFO)
# Alembic
#   ALEMBIC_INI                 — Override path to alembic.ini (auto-detected by default)
# Vault / OpenBao
#   VAULT_ADDR / VAULT_TOKEN / VAULT_ROLE_ID / VAULT_SECRET_ID

# Expose HTTP port (API + Swagger UI + Prometheus metrics)
EXPOSE 5000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:5000/health || exit 1

# Use tini as PID 1 for proper signal forwarding to gunicorn
ENTRYPOINT ["tini", "--"]

# Run with gunicorn (single worker + threads for background services compatibility)
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "1", "--threads", "4", "--timeout", "120", "app:app"]
