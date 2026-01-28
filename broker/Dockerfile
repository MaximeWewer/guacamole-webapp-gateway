FROM python:3.14-slim

# Labels
LABEL maintainer="Guacamole session broker"
LABEL description="Session broker for VNC container lifecycle management"

# Create non-root user with docker socket access
# The docker group GID (999) should match the host's docker group
# If it doesn't match, override with: docker compose run --user root session-broker
ARG DOCKER_GID=999
RUN groupadd -r -g ${DOCKER_GID} docker && \
    groupadd -r broker && \
    useradd -r -g broker -G docker broker

WORKDIR /app

# Install dependencies
# - libpq5 for psycopg2
# - curl for healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application (entire broker package)
COPY . /app/broker/
RUN cp /app/broker/app.py /app/app.py

# Create data directories with correct permissions
RUN mkdir -p /data/config /data/users && \
    chown -R broker:broker /data /app

# Run as non-root user
USER broker

# Expose port
EXPOSE 5000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:5000/health || exit 1

# Run with gunicorn
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "1", "--threads", "4", "--timeout", "120", "app:app"]
