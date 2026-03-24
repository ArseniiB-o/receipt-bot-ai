# ─── Stage 1: builder ─────────────────────────────────────────────────────────
FROM python:3.12-slim-bookworm AS builder

WORKDIR /build

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# Pre-compile all Python bytecode
COPY . .
RUN python -m compileall -q .

# ─── Stage 2: runtime ─────────────────────────────────────────────────────────
FROM python:3.12-slim-bookworm AS runtime

# Create non-root user
RUN useradd --create-home --shell /bin/bash --uid 1001 receipt_bot

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application source
COPY --from=builder /build/*.py ./
COPY --from=builder /build/handlers/ ./handlers/

# Create required directories with correct ownership
RUN mkdir -p /app/receipts /app/temp /app/logs \
    && chown -R receipt_bot:receipt_bot /app

USER receipt_bot

# Health check via a simple Python probe (avoids installing curl)
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import sqlite3; sqlite3.connect('/app/receipts.db').execute('SELECT 1')" || exit 1

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=0 \
    RECEIPTS_FOLDER=/app/receipts \
    TEMP_FOLDER=/app/temp \
    DB_PATH=/app/receipts.db

CMD ["python", "main.py"]
