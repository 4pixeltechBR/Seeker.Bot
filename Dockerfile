# Seeker.Bot — Production Image
# Multi-stage build for optimal size

FROM python:3.12-slim as builder

WORKDIR /build

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy project metadata + source
COPY pyproject.toml .
COPY requirements.txt .
COPY src/ src/
COPY config/ config/

# Install Python dependencies from pyproject.toml
RUN pip install --user --no-cache-dir .


# ─────────────────────────────────────────────────────────────────
# Final Image
# ─────────────────────────────────────────────────────────────────

FROM python:3.12-slim

LABEL maintainer="Seeker.Bot <https://github.com/4pixeltechBR/Seeker.Bot>"
LABEL description="Autonomous Research Agent with Multi-Provider LLM Support"

WORKDIR /app

# Install runtime dependencies only
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy Python dependencies from builder
COPY --from=builder /root/.local /root/.local

# Set PATH
ENV PATH=/root/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Copy application code
COPY . .

# Create necessary directories
RUN mkdir -p data logs cache

# Health check — verifies seeker_memory.db is accessible (SQLite WAL check)
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import sqlite3; c=sqlite3.connect('data/seeker_memory.db'); c.execute('PRAGMA journal_mode'); c.close(); print('OK')" || exit 1

# Run Seeker.Bot
CMD ["python", "-m", "src"]
