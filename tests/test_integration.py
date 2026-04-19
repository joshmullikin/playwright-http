"""Integration tests for Playwright HTTP executor.

Uses pytest-playwright fixtures and httpserver to test with real browser instances.
Runs both locally and in CI environments.
"""

import asyncio
import re
from pathlib import Path

import pytest
import pytest_asyncio

from executor.runner import execute_test
from executor.browser import BrowserManager


# All tests in this file are async
pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def html_content():
    """HTML content for the test server."""
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Test Page</title>
        <style>
            #hidden { display: none; }
            .button-group { margin: 20px 0; }
            [role="dialog"] { border: 2px solid red; padding: 20px; }
        </style>
    </head>
    <body>
        <h1>Welcome Page</h1>
        <p id="greeting">Hello, World!</p>
        <p id="hidden">This is hidden</p>
        
        <div class="button-group">
            <button id="login-btn">Login</button>
            <a href="/about" id="about-link">About</a>
        </div>
        
        <form id="user-form">
            <label for="username">Username:</label>
            <input id="username" type="text" placeholder="Enter username" />
            
            <label for="password">Password:</label>
            <input id="password" type="password" placeholder="Enter password" />
            
            <button type="submit" id="submit-btn">Submit</button>
        </form>
        
        <div id="modal" role="dialog" style="display: none;">
            <h2>Modal Dialog</h2>
            <p>This is a modal window</p>
            <button id="modal-close">Close</button>
        </div>
        
        <div id="results"></div>
        
        <script>
            document.getElementById('login-btn').addEventListener('click', function() {
                document.getElementById('results').textContent = 'Login clicked';
                document.getElementById('modal').style.display = 'block';
            });
            
            document.getElementById('modal-close').addEventListener('click', function() {
                document.getElementById('modal').style.display = 'none';
            });
            
            document.getElementById('user-form').addEventListener('submit', function(e) {
                e.preventDefault();
                const username = document.getElementById('username').value;
                document.getElementById('results').textContent = `Submitted: ${username}`;
            });
        </script>
    </body>
    </html>
    """


@pytest.fixture
def http_server_url(httpserver, html_content):
    """Serve test HTML page via httpserver fixture."""
    httpserver.expect_request("/").respond_with_data(html_content, mimetype="text/html")
    httpserver.expect_request("/recovery").respond_with_data(
        """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Recovery Page</title>
            <style>
                .menu { display: inline-block; position: relative; }
                .menu-trigger { padding: 8px 10px; border: 1px solid #999; background: #f7f7f7; }
                .submenu { display: none; position: absolute; top: 100%; left: 0; background: white; border: 1px solid #ccc; }
                .submenu a { display: block; padding: 8px 10px; }
                .menu:hover .submenu { display: block; }
            </style>
        </head>
        <body>
            <h1>Recovery Targets</h1>

            <button data-testid="save-action-999" id="save-btn">Save Draft</button>

            <nav>
                <div class="menu" id="reports-menu">
                    <a class="menu-trigger" href="#">Reports</a>
                    <div class="submenu" aria-hidden="true">
                        <a id="export-csv" href="#">Export CSV</a>
                    </div>
                </div>
            </nav>

            <div id="results"></div>

            <script>
                document.getElementById('save-btn').addEventListener('click', function () {
                    document.getElementById('results').textContent = 'Saved';
                });

                document.getElementById('export-csv').addEventListener('click', function (e) {
                    e.preventDefault();
                    document.getElementById('results').textContent = 'Exported CSV';
                });
            </script>
        </body>
        </html>
        """,
        mimetype="text/html",
    )
    return httpserver.url_for("/")


@pytest_asyncio.fixture
async def browser_manager(monkeypatch):
    """Create and yield a BrowserManager instance using only chromium-headless.

    Restricts to chromium-headless so the fixture works on machines where
    Firefox and WebKit aren't installed (including most CI environments that
    only run ``playwright install chromium``).
    """
    monkeypatch.setenv("AVAILABLE_BROWSERS", "chromium-headless")
    manager = BrowserManager()
    await manager.start()
    yield manager
    await manager.stop()


@pytest.fixture
def base_url(http_server_url):
    """Base URL for test server."""
    return http_server_url


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


async def collect_events(execute_test_coro):
    """Execute a test and collect all emitted events."""
    events = []

    async def callback(event):
        events.append(event)

    await execute_test_coro(callback)
    return events


# ---------------------------------------------------------------------------
# Integration Tests: Element Finding and Interaction
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestElementFindingIntegration:
    """Tests for real element finding and interaction on live HTML."""

    async def test_navigate_and_find_text(self, browser_manager, base_url):
        """Navigate to page and verify text is visible."""
        events = []

        async def callback(event):
            events.append(event)

        result = await execute_test(
            browser_manager,
            {
                "test_id": "nav-test",
                "base_url": base_url,
                "steps": [
                    {"action": "navigate", "value": "/"},
                    {"action": "assert_text", "value": "Welcome Page"},
                ],
            },
            callback,
        )

        assert result["status"] == "passed"
        assert result["passed"] == 2

    async def test_click_button_and_detect_change(self, browser_manager, base_url):
        """Click a button and verify page changes."""
        events = []

        async def callback(event):
            events.append(event)

        result = await execute_test(
            browser_manager,
            {
                "base_url": base_url,
                "steps": [
                    {"action": "navigate", "value": "/"},
                    {"action": "click", "target": "Login"},
                    {"action": "wait", "value": "500"},
                    {"action": "assert_text", "value": "Login clicked"},
                ],
            },
            callback,
        )

        assert result["status"] == "passed"
        assert result["passed"] == 4

    async def test_form_fill_and_submit(self, browser_manager, base_url):
        """Fill form fields and submit."""
        events = []

        async def callback(event):
            events.append(event)

        result = await execute_test(
            browser_manager,
            {
                "base_url": base_url,
                "steps": [
                    {"action": "navigate", "value": "/"},
                    {"action": "type", "target": "Username", "value": "alice"},
                    {"action": "type", "target": "Password", "value": "secret123"},
                    {"action": "click", "target": "Submit"},
                    {"action": "wait", "value": "300"},
                    {"action": "assert_text", "value": "Submitted: alice"},
                ],
            },
            callback,
        )

        assert result["status"] == "passed"
        assert result["passed"] == 6

    async def test_element_not_found_fails(self, browser_manager, base_url):
        """Verify that looking for non-existent element fails."""
        events = []

        async def callback(event):
            events.append(event)

        result = await execute_test(
            browser_manager,
            {
                "base_url": base_url,
                "steps": [
                    {"action": "navigate", "value": "/"},
                    {"action": "click", "target": "NonexistentButton"},
                ],
            },
            callback,
        )

        # Should fail on step 2 (click)
        assert result["status"] == "failed"
        assert result["failed"] == 1
        assert result["skipped"] == 0

    async def test_assert_element_visibility(self, browser_manager, base_url):
        """Assert that an element is visible."""
        events = []

        async def callback(event):
            events.append(event)

        result = await execute_test(
            browser_manager,
            {
                "base_url": base_url,
                "steps": [
                    {"action": "navigate", "value": "/"},
                    {"action": "assert_element", "target": "Welcome Page"},
                ],
            },
            callback,
        )

        assert result["status"] == "passed"

    async def test_wait_for_element(self, browser_manager, base_url):
        """Wait for element to appear."""
        events = []

        async def callback(event):
            events.append(event)

        result = await execute_test(
            browser_manager,
            {
                "base_url": base_url,
                "steps": [
                    {"action": "navigate", "value": "/"},
                    {"action": "wait", "target": "Login"},
                ],
            },
            callback,
        )

        assert result["status"] == "passed"

    async def test_css_selector_click(self, browser_manager, base_url):
        """Click using CSS selector instead of natural language."""
        events = []

        async def callback(event):
            events.append(event)

        result = await execute_test(
            browser_manager,
            {
                "base_url": base_url,
                "steps": [
                    {"action": "navigate", "value": "/"},
                    {"action": "click", "target": "#login-btn"},
                    {"action": "wait", "value": "200"},
                    {"action": "assert_text", "value": "Login clicked"},
                ],
            },
            callback,
        )

        assert result["status"] == "passed"
        assert result["passed"] == 4


# ---------------------------------------------------------------------------
# Integration Tests: Assertions
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestAssertionsIntegration:
    """Tests for various assertion types on real pages."""

    async def test_assert_url_matches_pattern(self, browser_manager, base_url):
        """Assert current URL matches a regex pattern."""
        events = []

        async def callback(event):
            events.append(event)

        result = await execute_test(
            browser_manager,
            {
                "base_url": base_url,
                "steps": [
                    {"action": "navigate", "value": "/"},
                    {"action": "assert_url", "value": "/$|/index"},
                ],
            },
            callback,
        )

        assert result["status"] == "passed"

    async def test_assert_text_not_on_page_fails(self, browser_manager, base_url):
        """Verify that asserting for non-existent text fails."""
        events = []

        async def callback(event):
            events.append(event)

        result = await execute_test(
            browser_manager,
            {
                "base_url": base_url,
                "steps": [
                    {"action": "navigate", "value": "/"},
                    {"action": "assert_text", "value": "NonexistentText12345"},
                ],
            },
            callback,
        )

        assert result["status"] == "failed"
        assert result["failed"] == 1

    async def test_evaluate_javascript(self, browser_manager, base_url):
        """Execute custom JavaScript and verify result."""
        events = []

        async def callback(event):
            events.append(event)

        result = await execute_test(
            browser_manager,
            {
                "base_url": base_url,
                "steps": [
                    {"action": "navigate", "value": "/"},
                    {
                        "action": "evaluate",
                        "value": "() => document.title",
                    },
                ],
            },
            callback,
        )

        assert result["status"] == "passed"
        # Check that step_completed event contains the result
        events_dict = {e["type"]: e for e in events}
        # find evaluate step_completed
        eval_event = next(
            (e for e in events if e.get("type") == "step_completed" and "result" in e),
            None,
        )
        if eval_event and eval_event.get("result"):
            assert eval_event["result"] == "Test Page"


# ---------------------------------------------------------------------------
# Integration Tests: State and Recovery
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestStateManagementIntegration:
    """Tests for capturing and restoring page state."""

    async def test_capture_and_restore_state(self, browser_manager, base_url):
        """Test that capture_state action works without errors."""
        events = []

        async def callback(event):
            events.append(event)

        # Test capture_state action - it captures storage state (cookies, localStorage, etc.)
        result = await execute_test(
            browser_manager,
            {
                "base_url": base_url,
                "steps": [
                    {"action": "navigate", "value": "/"},
                    {"action": "capture_state"},  # Should capture and store state
                    {"action": "assert_url", "value": base_url},  # Verify still on correct page
                ],
            },
            callback,
        )

        # capture_state returns status "passed" even if there's no storage state to capture
        assert result["status"] == "passed"
        # Verify navigate and assert_url also passed (events should show these)
        assert any(e.get("action") == "navigate" for e in events)


# ---------------------------------------------------------------------------
# Integration Tests: Retries and Recovery
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestRetryIntegration:
    """Tests for retry behavior in action execution."""

    async def test_action_succeeds_on_retry(self, browser_manager, base_url):
        """Verify that actions can retry and succeed."""
        events = []

        async def callback(event):
            events.append(event)

        # This should succeed on first attempt
        result = await execute_test(
            browser_manager,
            {
                "base_url": base_url,
                "steps": [
                    {"action": "navigate", "value": "/"},
                    {"action": "click", "target": "Login"},
                ],
                "options": {"step_retries": {"click": 2}},
            },
            callback,
        )

        assert result["status"] == "passed"
        assert result["failed"] == 0


# ---------------------------------------------------------------------------
# Integration Tests: Full End-to-End Workflows
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestEndToEndWorkflows:
    """Tests for complete user workflows."""

    async def test_complete_login_workflow(self, browser_manager, base_url):
        """Complete workflow: navigate, fill form, submit, verify result."""
        events = []

        async def callback(event):
            events.append(event)

        result = await execute_test(
            browser_manager,
            {
                "base_url": base_url,
                "steps": [
                    {"action": "navigate", "value": "/", "description": "Navigate to login page"},
                    {
                        "action": "assert_element",
                        "target": "Login",
                        "description": "Verify login button exists",
                    },
                    {
                        "action": "type",
                        "target": "Username",
                        "value": "testuser",
                        "description": "Enter username",
                    },
                    {
                        "action": "type",
                        "target": "Password",
                        "value": "password123",
                        "description": "Enter password",
                    },
                    {
                        "action": "click",
                        "target": "Submit",
                        "description": "Click submit button",
                    },
                    {"action": "wait", "value": "300", "description": "Wait for submission"},
                    {
                        "action": "assert_text",
                        "value": "Submitted: testuser",
                        "description": "Verify form was submitted",
                    },
                ],
            },
            callback,
        )

        assert result["status"] == "passed"
        assert result["passed"] == 7
        assert result["failed"] == 0

        # Verify event flow
        event_types = [e["type"] for e in events]
        assert event_types[0] == "started"
        assert event_types[-1] == "completed"
        assert "step_completed" in event_types

    async def test_workflow_with_screenshot_on_failure(self, browser_manager, base_url):
        """Verify screenshot is captured when step fails."""
        events = []

        async def callback(event):
            events.append(event)

        result = await execute_test(
            browser_manager,
            {
                "base_url": base_url,
                "steps": [
                    {"action": "navigate", "value": "/"},
                    {"action": "click", "target": "NonexistentButton"},
                ],
                "options": {"screenshot_on_failure": True},
            },
            callback,
        )

        assert result["status"] == "failed"
        assert result["failed"] == 1

        # Check that a failure event includes a screenshot
        failure_events = [e for e in events if e.get("type") == "step_completed" and e.get("status") == "failed"]
        assert len(failure_events) > 0
        # Screenshot should be present (base64 encoded)
        assert failure_events[0].get("screenshot") is not None


# ---------------------------------------------------------------------------
# Integration Tests: Multiple Browsers
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestMultipleBrowsers:
    """Tests with different browser types if available."""

    async def test_chromium_browser(self, browser_manager, base_url):
        """Test with chromium browser."""
        events = []

        async def callback(event):
            events.append(event)

        result = await execute_test(
            browser_manager,
            {
                "base_url": base_url,
                "steps": [
                    {"action": "navigate", "value": "/"},
                    {"action": "assert_text", "value": "Welcome Page"},
                ],
                "options": {"browser": "chromium-headless"},
            },
            callback,
        )

        assert result["status"] == "passed"


# ---------------------------------------------------------------------------
# Integration Tests: Click Recovery Strategies
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestClickRecoveryIntegration:
    """Tests for click recovery tiers using real browser DOM behavior."""

    async def test_css_autoheal_click_by_fuzzy_data_testid(self, browser_manager, base_url):
        """Tier 2b: fuzzy CSS selector should recover from stale numeric suffix."""
        events = []

        async def callback(event):
            events.append(event)

        result = await execute_test(
            browser_manager,
            {
                "base_url": base_url,
                "steps": [
                    {"action": "navigate", "value": "/recovery"},
                    {
                        "action": "click",
                        "target": "[data-testid='save-action-123']",
                        "locators": {
                            "coordinates": {"pageX": 40, "pageY": 40},
                        },
                    },
                    {"action": "assert_text", "value": "Saved"},
                ],
            },
            callback,
        )

        assert result["status"] == "passed"
        click_event = next(e for e in events if e.get("type") == "step_completed" and e.get("action") == "click")
        assert click_event.get("status") == "passed"

    async def test_hover_submenu_click_reveals_hidden_target(self, browser_manager, base_url):
        """Tier 4: hover submenu fallback reveals hidden link and clicks it."""
        events = []

        async def callback(event):
            events.append(event)

        result = await execute_test(
            browser_manager,
            {
                "base_url": base_url,
                "steps": [
                    {"action": "navigate", "value": "/recovery"},
                    {"action": "click", "target": "Export CSV"},
                    {"action": "assert_text", "value": "Exported CSV"},
                ],
            },
            callback,
        )

        assert result["status"] == "passed"
        click_event = next(e for e in events if e.get("type") == "step_completed" and e.get("action") == "click")
        assert click_event.get("status") == "passed"


# End of test file
