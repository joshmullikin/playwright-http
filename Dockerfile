# playwright-http Dockerfile
# Build: docker build -t playwright-http .
# Run:   docker run -p 8932:8932 -e AVAILABLE_BROWSERS=chromium-headless playwright-http

# ── Stage 1: build venv and download browser binaries ────────────────────────
FROM python:3.13-slim-bookworm AS builder

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --link-mode=copy

ENV VIRTUAL_ENV=/app/.venv
ENV PATH="/app/.venv/bin:$PATH"

# Download browser binary only; system deps are handled in the final stage
RUN playwright install chromium

# Uncomment to pre-download additional browsers:
# RUN playwright install chrome
# RUN playwright install firefox
# RUN playwright install webkit

# ── Stage 2: lean runtime image ───────────────────────────────────────────────
FROM python:3.13-slim-bookworm

WORKDIR /app

# Copy venv and browser cache from builder — uv is not needed at runtime
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /root/.cache/ms-playwright /root/.cache/ms-playwright

# Activate the venv
ENV VIRTUAL_ENV=/app/.venv
ENV PATH="/app/.venv/bin:$PATH"

# Install only the OS-level packages that chromium requires (no browser re-download)
RUN playwright install-deps chromium

# Copy application code
COPY executor/ ./executor/

EXPOSE 8932

ENV AVAILABLE_BROWSERS=chromium-headless
ENV BROWSER_TIMEOUT=30000

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD ["/app/.venv/bin/python", "-c", "import sys, urllib.request; urllib.request.urlopen('http://127.0.0.1:8932/health', timeout=5).read(); sys.exit(0)"]

CMD ["uvicorn", "executor.main:app", "--host", "0.0.0.0", "--port", "8932"]
