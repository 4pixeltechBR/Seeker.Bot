# Seeker.Bot — Production Image
# Multi-stage build for optimal size

FROM python:3.10-slim as builder

WORKDIR /build

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt .

# Install Python dependencies
RUN pip install --user --no-cache-dir -r requirements.txt


# ─────────────────────────────────────────────────────────────────
# Final Image
# ─────────────────────────────────────────────────────────────────

FROM python:3.10-slim

LABEL maintainer="Seeker.Bot <https://github.com/4pixeltechBR/Seeker.Bot>"
LABEL description="Autonomous Research Agent with Multi-Provider LLM Support"

WORKDIR /app

# Install runtime dependencies only
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
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

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# Expose port (for future API server)
EXPOSE 8080

# Run Seeker.Bot
CMD ["python", "-m", "src"]
