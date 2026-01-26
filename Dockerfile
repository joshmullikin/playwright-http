# playwright-http Dockerfile
# Build: docker build -t playwright-http .
# Run:   docker run -p 8932:8932 -e AVAILABLE_BROWSERS=chromium-headless playwright-http

FROM python:3.13-slim-bookworm

WORKDIR /app

# Install curl for health check
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv for fast package management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy dependency files first for caching
COPY pyproject.toml uv.lock ./

# Install Python dependencies (excluding dev deps)
RUN uv sync --frozen --no-dev

# Install Playwright browser with system dependencies
RUN uv run playwright install --with-deps chromium

# Uncomment to install additional browsers:
# RUN uv run playwright install --with-deps chrome
# RUN uv run playwright install --with-deps firefox
# RUN uv run playwright install --with-deps webkit

# Copy application code
COPY executor/ ./executor/

# Expose port
EXPOSE 8932

# Default environment variables
ENV AVAILABLE_BROWSERS=chromium-headless
ENV BROWSER_TIMEOUT=30000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8932/health || exit 1

# Run the server
CMD ["uv", "run", "uvicorn", "executor.main:app", "--host", "0.0.0.0", "--port", "8932"]
