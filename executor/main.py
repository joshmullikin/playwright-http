"""FastAPI application for Playwright Executor service.

Provides REST API for browser automation test execution.
"""

import asyncio
import json
import time
import uuid
import os
from contextlib import asynccontextmanager
from dotenv import load_dotenv

# Load .env file before any other imports that read env vars
load_dotenv()
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from .browser import get_browser_manager, get_browser_info, startup_browser, shutdown_browser
from .runner import execute_test
from .logging import setup_logging, get_logger, request_id_var

# Initialize logging
setup_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifespan - startup and shutdown."""
    # Startup: Start browser
    logger.info("Starting Playwright Executor service")
    await startup_browser()
    yield
    # Shutdown: Stop browser
    logger.info("Shutting down Playwright Executor service")
    await shutdown_browser()


app = FastAPI(
    title="Playwright Executor",
    description="Browser automation test execution service",
    version="0.1.0",
    lifespan=lifespan,
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log all HTTP requests with request ID for correlation."""
    # Use X-Request-ID from upstream (checkmate) or generate new one
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    request_id_var.set(request_id)

    start = time.perf_counter()
    logger.info(f"{request.method} {request.url.path}")

    response = await call_next(request)

    duration_ms = (time.perf_counter() - start) * 1000
    logger.info(f"{response.status_code} ({duration_ms:.1f}ms)")

    # Return request ID in response header
    response.headers["X-Request-ID"] = request_id

    return response


# Request/Response models
class TestStep(BaseModel):
    """Individual test step."""

    action: str
    target: str | None = None
    value: str | None = None
    description: str | None = None


class TestOptions(BaseModel):
    """Test execution options."""

    browser: str | None = None  # Browser ID (e.g., "chrome", "chromium-headless")
    timeout: int = 30000
    screenshot_on_failure: bool = True


class ExecuteRequest(BaseModel):
    """Test execution request."""

    test_id: str | None = None
    base_url: str
    steps: list[TestStep]
    options: TestOptions | None = None


class HealthResponse(BaseModel):
    """Health check response."""

    status: str
    browsers: list[str]
    default_browser: str


class BrowserInfo(BaseModel):
    """Browser information."""

    id: str
    name: str
    headless: bool


class BrowsersResponse(BaseModel):
    """Available browsers response."""

    browsers: list[BrowserInfo]
    default: str


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Health check endpoint.

    Returns service status and available browsers.
    """
    manager = get_browser_manager()

    return HealthResponse(
        status="ok" if manager.is_running else "degraded",
        browsers=manager.available_browsers,
        default_browser=manager.default_browser,
    )


@app.get("/browsers", response_model=BrowsersResponse)
async def get_browsers() -> BrowsersResponse:
    """Get available browsers.

    Returns list of browsers that can be used for test execution.
    """
    manager = get_browser_manager()

    browsers = [
        BrowserInfo(**get_browser_info(browser_id))
        for browser_id in manager.available_browsers
    ]

    return BrowsersResponse(
        browsers=browsers,
        default=manager.default_browser,
    )


@app.post("/execute")
async def execute_endpoint(request: Request) -> StreamingResponse:
    """Execute test steps with SSE streaming.

    Streams events as the test executes:
    - started: Test execution started
    - step_started: Individual step starting
    - step_completed: Individual step completed (with status, duration, error)
    - completed: Test execution completed (with summary)

    Returns:
        SSE stream of test execution events
    """
    # Parse request body
    body = await request.json()

    # Convert to dict for runner
    test_request = {
        "test_id": body.get("test_id"),
        "base_url": body.get("base_url", ""),
        "steps": body.get("steps", []),
        "options": body.get("options", {}),
    }

    async def event_stream():
        """Generate SSE events."""
        # Queue for events from the callback
        event_queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

        async def callback(event: dict[str, Any]) -> None:
            """Put events into queue."""
            await event_queue.put(event)

        async def run_test():
            """Run test and signal completion."""
            try:
                browser_manager = get_browser_manager()
                await execute_test(browser_manager, test_request, callback)
            except Exception as e:
                logger.error(f"Test execution error: {e}")
                await event_queue.put({
                    "type": "error",
                    "error": str(e),
                })
            finally:
                # Signal end of stream
                await event_queue.put(None)

        # Start test execution in background
        task = asyncio.create_task(run_test())

        try:
            while True:
                event = await event_queue.get()
                if event is None:
                    # End of stream
                    break
                yield f"data: {json.dumps(event)}\n\n"
        finally:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable buffering in nginx
        },
    )


@app.post("/execute/sync")
async def execute_sync_endpoint(request: ExecuteRequest) -> JSONResponse:
    """Execute test steps synchronously (non-streaming).

    For clients that don't need real-time updates.

    Returns:
        JSON response with test results
    """
    test_request = {
        "test_id": request.test_id,
        "base_url": request.base_url,
        "steps": [s.model_dump() for s in request.steps],
        "options": request.options.model_dump() if request.options else {},
    }

    # Collect all events
    events: list[dict[str, Any]] = []

    async def callback(event: dict[str, Any]) -> None:
        events.append(event)

    browser_manager = get_browser_manager()
    result = await execute_test(browser_manager, test_request, callback)

    return JSONResponse(content={
        "result": result,
        "events": events,
    })


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8932"))
    uvicorn.run(app, host="0.0.0.0", port=port)
