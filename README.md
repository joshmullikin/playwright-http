# playwright-http

Browser automation over HTTP. Execute Playwright tests via simple REST API with natural language element targeting.

**[UTML Specification](UTML.md)** - Full documentation of the UI Test Markup Language

## Features

- **Simple REST API** - POST JSON steps, get SSE streaming results
- **Natural language targeting** - Use "Submit button" instead of CSS selectors
- **Multi-browser support** - Chrome, Chromium, Firefox, WebKit (headless or visible)
- **Stealth mode** - Built-in bot detection bypass for headless browsers
- **No sessions** - Each test gets isolated browser context
- **Real-time streaming** - SSE events for step-by-step progress

## Quick Start

```bash
# Install
uv sync
uv run playwright install chromium chrome

# Run
AVAILABLE_BROWSERS=chrome-headless,chrome uv run uvicorn executor.main:app --port 8932

# Test
curl http://localhost:8932/health
```

## API

### `POST /execute` - Run Test

```bash
curl -X POST http://localhost:8932/execute \
  -H "Content-Type: application/json" \
  -d '{
    "base_url": "https://example.com",
    "steps": [
      {"action": "navigate", "value": "/", "description": "Go to homepage"},
      {"action": "assert_text", "value": "Example Domain", "description": "Verify title"}
    ]
  }'
```

**Response (SSE Stream):**
```
data: {"type": "started", "test_id": "abc123", "total_steps": 2}
data: {"type": "step_started", "step_number": 1, "action": "navigate"}
data: {"type": "step_completed", "step_number": 1, "status": "passed", "duration": 150}
data: {"type": "step_started", "step_number": 2, "action": "assert_text"}
data: {"type": "step_completed", "step_number": 2, "status": "passed", "duration": 50}
data: {"type": "completed", "status": "passed", "passed": 2, "failed": 0, "skipped": 0}
```

### `GET /browsers` - List Available Browsers

```bash
curl http://localhost:8932/browsers
# {"browsers": [{"id": "chrome-headless", "name": "Google Chrome (Headless)", "headless": true}], "default": "chrome-headless"}
```

### `GET /health` - Health Check

```bash
curl http://localhost:8932/health
# {"status": "ok", "browsers": ["chrome-headless", "chrome"], "default_browser": "chrome-headless"}
```

## SSE Events

The `/execute` endpoint streams Server-Sent Events:

| Event | Description | Fields |
|-------|-------------|--------|
| `started` | Test execution began | `test_id`, `total_steps` |
| `step_started` | Step beginning | `step_number`, `action`, `description` |
| `step_completed` | Step finished | `step_number`, `status`, `duration`, `screenshot`, `error` |
| `completed` | Test finished | `test_id`, `status`, `passed`, `failed`, `skipped`, `duration` |
| `error` | Fatal error | `error` |

**Status values:** `passed`, `failed`, `skipped`

## Supported Actions

20 browser actions. See [UTML spec](UTML.md#actions-reference) for full details.

| Action | Description | Target | Value |
|--------|-------------|--------|-------|
| `navigate` | Go to URL | - | URL or path |
| `click` | Click element | Element description | - |
| `type` | Type into input | Input description | Text to type |
| `hover` | Hover over element | Element description | - |
| `select` | Select dropdown option | Dropdown description | Option value |
| `wait` | Wait for element/time | Text/element or CSS selector | Time in ms (opt) |
| `wait_for_page` | Wait for page load | - | load/domcontentloaded/networkidle |
| `assert_text` | Assert text visible | - | Expected text |
| `assert_element` | Assert element visible | Element description | - |
| `assert_style` | Assert CSS style | Element description | JSON: {property, expected} |
| `assert_url` | Assert URL matches regex | - | Regex pattern |
| `press_key` | Press keyboard key | - | Key name (Enter, Tab) |
| `screenshot` | Take screenshot | Element (opt) | Filename (opt) |
| `back` | Navigate back | - | - |
| `fill_form` | Fill multiple fields | - | JSON: {field: value} |
| `upload` | Upload file(s) | Input (opt) | File path(s) |
| `drag` | Drag to element | Source element | Destination element |
| `evaluate` | Run JavaScript | - | JS code |
| `capture_state` | Capture browser state | - | - |
| `restore_state` | Restore browser state | URL (opt) | JSON: {url, state} |

## Element Finding

Natural language element targeting with automatic suffix stripping:

```
"Password input field" → tries:
  1. "Password input field"
  2. "Password input"
  3. "Password"
```

Also supports CSS selectors: `#my-id`, `.my-class`, `input[type="submit"]`

## Configuration

```bash
# Available browsers (comma-separated)
AVAILABLE_BROWSERS=chrome-headless,chrome    # Local dev
AVAILABLE_BROWSERS=chromium-headless         # CI/Production

# Browser timeout (ms)
BROWSER_TIMEOUT=30000
```

**Browser IDs:** `chromium`, `chromium-headless`, `chrome`, `chrome-headless`, `firefox`, `firefox-headless`, `webkit`, `webkit-headless`

## Docker

```bash
# Build (installs chromium by default)
docker build -t playwright-http .

# Run
docker run -p 8932:8932 playwright-http
```

Default: `AVAILABLE_BROWSERS=chromium-headless`. To add more browsers, uncomment the relevant `RUN playwright install --with-deps <browser>` line in the Dockerfile before building.

## Why playwright-http?

| Feature | Browserless | Playwright MCP | playwright-http |
|---------|-------------|----------------|-----------------|
| Interface | WebSocket + Code | MCP Protocol | REST API |
| Element targeting | CSS selectors | Accessibility tree | Natural language |
| Code required | Yes | Yes | No |
| Session management | You handle it | Buggy | Automatic |
| Stealth mode | Paid feature | No | Built-in |

## Dependency and Security Automation

This repository uses scheduled bots and workflows to keep dependencies and security checks current.

- Dependabot updates Python dependencies daily at 06:00 UTC.
- Dependabot updates GitHub Actions weekly on Monday at 07:00 UTC.
- Dependabot updates Docker dependencies weekly on Monday at 08:00 UTC.
- A scheduled security workflow runs weekly on Monday at 06:30 UTC and can also be run manually.

The scheduled security workflow exports production requirements, runs `pip-audit`, runs OSV scanning against `uv.lock`, and uploads SARIF results to GitHub code scanning.

## License

MIT
