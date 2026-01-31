"""Test execution orchestrator.

Executes test steps and streams results via callback for SSE streaming.
"""

import asyncio
import base64
import os
import time
import uuid
from typing import Any, Callable, Awaitable

from playwright.async_api import Page

from .actions import execute_action
from .browser import BrowserManager
from .logging import get_logger

logger = get_logger(__name__)

# Type alias for event callback
EventCallback = Callable[[dict[str, Any]], Awaitable[None]]

# Default retry configuration per action type
# Actions that interact with elements may fail due to timing - retry makes sense
# Assertions should NOT retry - they represent actual test failures
DEFAULT_RETRIES_BY_ACTION = {
    # Interaction actions - retry on element timing issues
    "click": 2,
    "type": 2,
    "fill_form": 2,
    "select": 2,
    "hover": 1,
    "press_key": 1,
    "upload": 1,
    "drag": 1,
    # Navigation - retry on network issues
    "navigate": 2,
    "back": 1,
    # Waiting - retry on timing
    "wait": 1,
    "wait_for_page": 1,
    # Assertions - DO NOT retry (real test failures)
    "assert_text": 0,
    "assert_element": 0,
    "assert_style": 0,
    # Utility - no retry needed
    "screenshot": 0,
    "evaluate": 0,
}

# Default retry delay in milliseconds
DEFAULT_RETRY_DELAY_MS = int(os.getenv("STEP_RETRY_DELAY_MS", "1000"))


def get_retry_config(action: str, options: dict[str, Any]) -> tuple[int, int]:
    """Get retry configuration for an action.

    Args:
        action: The action type (e.g., "click", "assert_text")
        options: Request options that may override defaults

    Returns:
        Tuple of (max_retries, retry_delay_ms)
    """
    # Check for global override in options
    if "step_retries" in options:
        # options.step_retries can be int (apply to all) or dict (per-action)
        step_retries = options["step_retries"]
        if isinstance(step_retries, int):
            max_retries = step_retries
        elif isinstance(step_retries, dict):
            max_retries = step_retries.get(action, DEFAULT_RETRIES_BY_ACTION.get(action, 0))
        else:
            max_retries = DEFAULT_RETRIES_BY_ACTION.get(action, 0)
    else:
        # Use environment variable override or default
        env_key = f"STEP_RETRY_{action.upper()}"
        env_value = os.getenv(env_key)
        if env_value is not None:
            max_retries = int(env_value)
        else:
            max_retries = DEFAULT_RETRIES_BY_ACTION.get(action, 0)

    retry_delay = options.get("step_retry_delay_ms", DEFAULT_RETRY_DELAY_MS)

    return max_retries, retry_delay


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
            - options: Execution options including:
                - browser: Browser ID to use
                - timeout: Step timeout in ms
                - screenshot_on_failure: Capture screenshot on failure
                - step_retries: Override retry count (int or dict per action)
                - step_retry_delay_ms: Delay between retries in ms
        event_callback: Async callback for streaming events

    Returns:
        Summary dict with final status and counts

    Events emitted:
        - started: {type, test_id, total_steps}
        - step_started: {type, step_number, action, description, attempt, max_attempts}
        - step_retry: {type, step_number, action, attempt, max_attempts, error, retry_delay}
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

            # Get retry config for this action type
            max_retries, retry_delay_ms = get_retry_config(action, options)

            step_passed = False
            last_error = None
            last_screenshot_b64 = None
            last_duration = 0

            for attempt in range(max_retries + 1):
                # Emit step started with attempt info
                await event_callback({
                    "type": "step_started",
                    "step_number": step_num,
                    "action": action,
                    "target": target,
                    "value": value,
                    "description": description,
                    "attempt": attempt + 1,
                    "max_attempts": max_retries + 1,
                })

                start_time = time.time()

                try:
                    result = await execute_action(page, step, base_url)
                    duration = int((time.time() - start_time) * 1000)
                    last_duration = duration

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

                    if status == "passed":
                        # Success - emit step_completed and break retry loop
                        await event_callback({
                            "type": "step_completed",
                            "step_number": step_num,
                            "action": action,
                            "target": target,
                            "value": value,
                            "status": status,
                            "duration": duration,
                            "error": None,
                            "screenshot": screenshot_b64,
                            "attempt": attempt + 1,
                            "max_attempts": max_retries + 1,
                        })
                        step_passed = True
                        break
                    else:
                        # Failed - check if we should retry
                        last_error = error
                        last_screenshot_b64 = screenshot_b64

                        if attempt < max_retries:
                            # Emit step_retry event and wait before retrying
                            logger.info(f"Step {step_num} ({action}) failed (attempt {attempt + 1}/{max_retries + 1}), retrying in {retry_delay_ms}ms: {error}")
                            await event_callback({
                                "type": "step_retry",
                                "step_number": step_num,
                                "action": action,
                                "target": target,
                                "value": value,
                                "attempt": attempt + 1,
                                "max_attempts": max_retries + 1,
                                "error": error,
                                "retry_delay": retry_delay_ms,
                            })
                            await asyncio.sleep(retry_delay_ms / 1000)
                        # else: final attempt failed, will emit step_completed below

                except Exception as e:
                    duration = int((time.time() - start_time) * 1000)
                    last_duration = duration
                    error_msg = str(e)
                    logger.error(f"Step {step_num} ({action}) exception (attempt {attempt + 1}): {error_msg}")

                    # Capture screenshot on exception
                    screenshot_b64 = None
                    if screenshot_on_failure:
                        try:
                            screenshot_bytes = await page.screenshot(type="png")
                            screenshot_b64 = base64.b64encode(screenshot_bytes).decode("utf-8")
                        except Exception:
                            pass

                    last_error = error_msg
                    last_screenshot_b64 = screenshot_b64

                    if attempt < max_retries:
                        # Emit step_retry event and wait before retrying
                        logger.info(f"Step {step_num} ({action}) exception (attempt {attempt + 1}/{max_retries + 1}), retrying in {retry_delay_ms}ms")
                        await event_callback({
                            "type": "step_retry",
                            "step_number": step_num,
                            "action": action,
                            "target": target,
                            "value": value,
                            "attempt": attempt + 1,
                            "max_attempts": max_retries + 1,
                            "error": error_msg,
                            "retry_delay": retry_delay_ms,
                        })
                        await asyncio.sleep(retry_delay_ms / 1000)
                    # else: final attempt failed, will emit step_completed below

            # After retry loop - update counts
            if step_passed:
                passed += 1
            else:
                # All retries exhausted - emit final failure
                await event_callback({
                    "type": "step_completed",
                    "step_number": step_num,
                    "action": action,
                    "target": target,
                    "value": value,
                    "status": "failed",
                    "duration": last_duration,
                    "error": last_error,
                    "screenshot": last_screenshot_b64,
                    "attempt": max_retries + 1,
                    "max_attempts": max_retries + 1,
                })
                failed += 1
                final_status = "failed"
                # Stop on first failure
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
