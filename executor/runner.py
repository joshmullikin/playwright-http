"""Test execution orchestrator.

Executes test steps and streams results via callback for SSE streaming.
"""

import base64
import logging
import time
import uuid
from typing import Any, Callable, Awaitable

from playwright.async_api import Page

from .actions import execute_action
from .browser import BrowserManager

logger = logging.getLogger(__name__)

# Type alias for event callback
EventCallback = Callable[[dict[str, Any]], Awaitable[None]]


async def execute_test(
    browser_manager: BrowserManager,
    test_request: dict[str, Any],
    event_callback: EventCallback,
) -> dict[str, Any]:
    """Execute a test and stream results via callback.

    Args:
        browser_manager: Browser manager instance
        test_request: Request containing steps and options:
            - test_id: Optional identifier for the test
            - base_url: Base URL for relative paths
            - steps: List of step dicts
            - options: Execution options (headless, timeout, screenshot_on_failure)
        event_callback: Async callback for streaming events

    Returns:
        Summary dict with final status and counts

    Events emitted:
        - started: {type, test_id, total_steps}
        - step_started: {type, step_number, action, description}
        - step_completed: {type, step_number, status, duration, error?, screenshot?}
        - completed: {type, status, passed, failed, skipped, summary}
    """
    test_id = test_request.get("test_id") or str(uuid.uuid4())[:8]
    base_url = test_request.get("base_url", "")
    steps = test_request.get("steps", [])
    options = test_request.get("options", {})

    screenshot_on_failure = options.get("screenshot_on_failure", True)
    browser_id = options.get("browser")  # None means use default

    logger.info(f"Starting test {test_id} with {len(steps)} steps (browser={browser_id or 'default'})")

    # Emit started event
    await event_callback({
        "type": "started",
        "test_id": test_id,
        "total_steps": len(steps),
    })

    passed = 0
    failed = 0
    skipped = 0
    final_status = "passed"

    # Create a fresh context and page for this test
    async with browser_manager.new_page(browser_id=browser_id) as page:
        for i, step in enumerate(steps):
            step_num = i + 1
            action = step.get("action", "")
            description = step.get("description", "")

            target = step.get("target")
            value = step.get("value")

            # Emit step started
            await event_callback({
                "type": "step_started",
                "step_number": step_num,
                "action": action,
                "target": target,
                "value": value,
                "description": description,
            })

            start_time = time.time()

            try:
                result = await execute_action(page, step, base_url)
                duration = int((time.time() - start_time) * 1000)

                status = result.get("status", "failed")
                error = result.get("error")

                # Handle screenshot - either from the action result or captured on failure
                screenshot_b64 = None

                # If action returned a screenshot (e.g., screenshot action), encode it
                if result.get("screenshot"):
                    screenshot_bytes = result.get("screenshot")
                    if isinstance(screenshot_bytes, bytes):
                        screenshot_b64 = base64.b64encode(screenshot_bytes).decode("utf-8")
                    elif isinstance(screenshot_bytes, str):
                        # Already base64 encoded
                        screenshot_b64 = screenshot_bytes

                # Capture screenshot on failure if not already captured
                if status == "failed" and screenshot_on_failure and not screenshot_b64:
                    try:
                        screenshot_bytes = await page.screenshot(type="png")
                        screenshot_b64 = base64.b64encode(screenshot_bytes).decode("utf-8")
                    except Exception as e:
                        logger.warning(f"Failed to capture screenshot: {e}")

                # Emit step completed
                await event_callback({
                    "type": "step_completed",
                    "step_number": step_num,
                    "action": action,
                    "target": target,
                    "value": value,
                    "status": status,
                    "duration": duration,
                    "error": error,
                    "screenshot": screenshot_b64,
                })

                if status == "passed":
                    passed += 1
                else:
                    failed += 1
                    final_status = "failed"
                    # Stop on first failure
                    skipped = len(steps) - step_num
                    break

            except Exception as e:
                duration = int((time.time() - start_time) * 1000)
                error_msg = str(e)
                logger.error(f"Step {step_num} exception: {error_msg}")

                # Capture screenshot on exception
                screenshot_b64 = None
                if screenshot_on_failure:
                    try:
                        screenshot_bytes = await page.screenshot(type="png")
                        screenshot_b64 = base64.b64encode(screenshot_bytes).decode("utf-8")
                    except Exception:
                        pass

                await event_callback({
                    "type": "step_completed",
                    "step_number": step_num,
                    "action": action,
                    "target": target,
                    "value": value,
                    "status": "failed",
                    "duration": duration,
                    "error": error_msg,
                    "screenshot": screenshot_b64,
                })

                failed += 1
                final_status = "failed"
                skipped = len(steps) - step_num
                break

    # Build summary
    executed = passed + failed
    summary = f"Executed {executed} of {len(steps)} steps: {passed} passed"
    if failed > 0:
        summary += f", {failed} failed"
    if skipped > 0:
        summary += f", {skipped} skipped"

    # Emit completed event
    await event_callback({
        "type": "completed",
        "status": final_status,
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "summary": summary,
    })

    logger.info(f"Test {test_id} completed: {summary}")

    return {
        "test_id": test_id,
        "status": final_status,
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "summary": summary,
    }


async def execute_single_step(
    page: Page,
    step: dict[str, Any],
    base_url: str,
    screenshot_on_failure: bool = True,
) -> dict[str, Any]:
    """Execute a single step (for batch operations).

    Args:
        page: Playwright Page instance
        step: Step dict with action, target, value, description
        base_url: Base URL for relative paths
        screenshot_on_failure: Capture screenshot if step fails

    Returns:
        Result dict with status, duration, error, screenshot
    """
    start_time = time.time()

    try:
        result = await execute_action(page, step, base_url)
        duration = int((time.time() - start_time) * 1000)

        output = {
            "status": result.get("status", "failed"),
            "duration": duration,
            "error": result.get("error"),
        }

        if output["status"] == "failed" and screenshot_on_failure:
            try:
                screenshot_bytes = await page.screenshot(type="png")
                output["screenshot"] = base64.b64encode(screenshot_bytes).decode("utf-8")
            except Exception:
                pass

        return output

    except Exception as e:
        duration = int((time.time() - start_time) * 1000)
        output = {
            "status": "failed",
            "duration": duration,
            "error": str(e),
        }

        if screenshot_on_failure:
            try:
                screenshot_bytes = await page.screenshot(type="png")
                output["screenshot"] = base64.b64encode(screenshot_bytes).decode("utf-8")
            except Exception:
                pass

        return output
