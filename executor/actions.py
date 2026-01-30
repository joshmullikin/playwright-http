"""Action implementations for test step execution.

Each action function takes a Playwright Page and step dict,
returning a result dict with status and optional error.
"""

import asyncio
import json
import re
from typing import Any

from playwright.async_api import Page, expect

from .logging import get_logger
from .element_finder import (
    find_element,
    find_input_element,
    find_clickable_element,
    get_target_variations,
    is_css_selector,
)


async def _wait_for_element(page: Page, target: str, timeout: int = 10000) -> bool:
    """Wait for an element to appear using the same strategy as find_element.

    Supports CSS selectors (#id, .class) and natural language descriptions.
    For CSS selectors, uses Playwright's native wait_for().
    For natural language, polls for buttons, links, and text with suffix stripping.

    Args:
        page: Playwright Page instance
        target: CSS selector (e.g., "#my_link", ".my_button") or
                element description (e.g., "credentials link", "Submit button")
        timeout: Timeout in milliseconds

    Returns:
        True if element found, False otherwise
    """
    # CSS selectors use Playwright's built-in waiting
    if is_css_selector(target):
        try:
            locator = page.locator(target)
            await locator.wait_for(state="visible", timeout=timeout)
            return True
        except Exception:
            return False

    # Natural language descriptions need polling across multiple locator strategies
    import time
    start_time = time.time()
    poll_interval = 0.3  # 300ms between polls

    while (time.time() - start_time) * 1000 < timeout:
        for variation in get_target_variations(target):
            pattern = re.compile(re.escape(variation), re.IGNORECASE)

            # Try button role
            try:
                locator = page.get_by_role("button", name=pattern)
                if await locator.count() > 0:
                    return True
            except Exception:
                pass

            # Try link role
            try:
                locator = page.get_by_role("link", name=pattern)
                if await locator.count() > 0:
                    return True
            except Exception:
                pass

            # Try text (catches most other elements)
            try:
                locator = page.get_by_text(pattern)
                if await locator.count() > 0:
                    return True
            except Exception:
                pass

        await asyncio.sleep(poll_interval)

    return False


async def execute_navigate(page: Page, step: dict, base_url: str) -> dict[str, Any]:
    """Navigate to a URL.

    Args:
        page: Playwright Page instance
        step: Step dict with "value" containing URL or path
        base_url: Base URL for relative paths

    Returns:
        Result dict with status
    """
    url = step.get("value", "")

    if not url:
        return {"status": "failed", "error": "No URL provided for navigate action"}

    # Handle relative URLs
    if url.startswith("/"):
        url = base_url.rstrip("/") + url

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        return {"status": "passed"}
    except Exception as e:
        return {"status": "failed", "error": f"Navigation failed: {str(e)}"}


async def execute_click(page: Page, step: dict, base_url: str) -> dict[str, Any]:
    """Click on an element.

    Args:
        page: Playwright Page instance
        step: Step dict with "target" containing element description
        base_url: Base URL (unused but included for consistency)

    Returns:
        Result dict with status
    """
    target = step.get("target", "")

    if not target:
        return {"status": "failed", "error": "No target provided for click action"}

    try:
        element = await find_clickable_element(page, target)
        if not element:
            element = await find_element(page, target)

        if not element:
            return {"status": "failed", "error": f"Element not found: {target}"}

        await element.click(timeout=5000)
        return {"status": "passed"}
    except Exception as e:
        return {"status": "failed", "error": f"Click failed: {str(e)}"}


async def execute_type(page: Page, step: dict, base_url: str) -> dict[str, Any]:
    """Type text into an input element.

    Uses human-like typing for password fields to avoid bot detection.
    Other fields use fill() for speed.

    Args:
        page: Playwright Page instance
        step: Step dict with "target" and "value"
        base_url: Base URL (unused but included for consistency)

    Returns:
        Result dict with status
    """
    target = step.get("target", "")
    value = step.get("value", "")

    if not target:
        return {"status": "failed", "error": "No target provided for type action"}

    try:
        element = await find_input_element(page, target)
        if not element:
            element = await find_element(page, target)

        if not element:
            return {"status": "failed", "error": f"Element not found: {target}"}

        # Check if this is a password field (by target name or input type)
        is_password_field = "password" in target.lower()
        if not is_password_field:
            try:
                input_type = await element.get_attribute("type")
                is_password_field = input_type == "password"
            except Exception:
                pass

        if is_password_field:
            # Use human-like typing for password fields to avoid bot detection
            # Clear field first, then type with small delays
            await element.click()
            await element.fill("")  # Clear existing content
            await element.type(value, delay=50)  # 50ms between keystrokes
        else:
            # Use fill() for non-sensitive fields (faster)
            await element.fill(value, timeout=5000)

        return {"status": "passed"}
    except Exception as e:
        return {"status": "failed", "error": f"Type failed: {str(e)}"}


async def execute_hover(page: Page, step: dict, base_url: str) -> dict[str, Any]:
    """Hover over an element.

    Args:
        page: Playwright Page instance
        step: Step dict with "target" containing element description
        base_url: Base URL (unused but included for consistency)

    Returns:
        Result dict with status
    """
    target = step.get("target", "")

    if not target:
        return {"status": "failed", "error": "No target provided for hover action"}

    try:
        element = await find_element(page, target)
        if not element:
            return {"status": "failed", "error": f"Element not found: {target}"}

        await element.hover(timeout=5000)
        return {"status": "passed"}
    except Exception as e:
        return {"status": "failed", "error": f"Hover failed: {str(e)}"}


async def execute_select(page: Page, step: dict, base_url: str) -> dict[str, Any]:
    """Select an option from a dropdown.

    Args:
        page: Playwright Page instance
        step: Step dict with "target" (dropdown) and "value" (option)
        base_url: Base URL (unused but included for consistency)

    Returns:
        Result dict with status
    """
    target = step.get("target", "")
    value = step.get("value", "")

    if not target:
        return {"status": "failed", "error": "No target provided for select action"}

    try:
        element = await find_element(page, target)
        if not element:
            return {"status": "failed", "error": f"Element not found: {target}"}

        # Handle single or multiple values
        values = [value] if isinstance(value, str) else value
        await element.select_option(values, timeout=5000)
        return {"status": "passed"}
    except Exception as e:
        return {"status": "failed", "error": f"Select failed: {str(e)}"}


async def execute_wait(page: Page, step: dict, base_url: str) -> dict[str, Any]:
    """Wait for an element/text or specified time.

    Args:
        page: Playwright Page instance
        step: Step dict with optional "target" (text/element) and "value" (time in ms)
        base_url: Base URL (unused but included for consistency)

    Returns:
        Result dict with status
    """
    target = step.get("target")
    value = step.get("value", "")

    try:
        if target:
            # Wait for element to appear - try buttons, links, then text
            # This matches the element finding strategy used elsewhere
            element = await _wait_for_element(page, target, timeout=10000)
            if element:
                return {"status": "passed"}
            return {"status": "failed", "error": f"Timeout waiting for: {target}"}
        elif value:
            # Wait for specified time (ms)
            try:
                ms = int(value)
                await asyncio.sleep(ms / 1000)
                return {"status": "passed"}
            except ValueError:
                # Treat value as text to wait for
                element = await _wait_for_element(page, value, timeout=10000)
                if element:
                    return {"status": "passed"}
                return {"status": "failed", "error": f"Timeout waiting for: {value}"}
        else:
            # Default: wait 1 second
            await asyncio.sleep(1)
            return {"status": "passed"}
    except Exception as e:
        error_target = target or value or "1 second"
        return {"status": "failed", "error": f"Timeout waiting for: {error_target}"}


async def execute_assert_text(page: Page, step: dict, base_url: str) -> dict[str, Any]:
    """Assert that text is visible on the page.

    Args:
        page: Playwright Page instance
        step: Step dict with "value" containing expected text
        base_url: Base URL (unused but included for consistency)

    Returns:
        Result dict with status
    """
    text = step.get("value", "")

    if not text:
        return {"status": "failed", "error": "No text provided for assert_text action"}

    try:
        pattern = re.compile(re.escape(text), re.IGNORECASE)
        locator = page.get_by_text(pattern)
        await expect(locator.first).to_be_visible(timeout=5000)
        return {"status": "passed"}
    except Exception as e:
        return {"status": "failed", "error": f"Text not found: {text}"}


async def execute_assert_element(page: Page, step: dict, base_url: str) -> dict[str, Any]:
    """Assert that an element is visible on the page.

    Args:
        page: Playwright Page instance
        step: Step dict with "target" containing element description
        base_url: Base URL (unused but included for consistency)

    Returns:
        Result dict with status
    """
    target = step.get("target", "")

    if not target:
        return {"status": "failed", "error": "No target provided for assert_element action"}

    try:
        element = await find_element(page, target)
        if not element:
            return {"status": "failed", "error": f"Element not found: {target}"}

        await expect(element).to_be_visible(timeout=5000)
        return {"status": "passed"}
    except Exception as e:
        return {"status": "failed", "error": f"Element not visible: {target}"}


async def execute_assert_style(page: Page, step: dict, base_url: str) -> dict[str, Any]:
    """Assert that an element has a specific CSS style.

    Args:
        page: Playwright Page instance
        step: Step dict with "target" (element) and "value" (JSON with property/expected)
        base_url: Base URL (unused but included for consistency)

    Returns:
        Result dict with status
    """
    target = step.get("target", "")
    value = step.get("value", "")

    if not target or not value:
        return {"status": "failed", "error": "Target and value required for assert_style action"}

    try:
        # Parse style specification
        if isinstance(value, str):
            style_spec = json.loads(value)
        else:
            style_spec = value

        css_property = style_spec.get("property", "")
        expected_value = style_spec.get("expected", "")

        if not css_property or not expected_value:
            return {"status": "failed", "error": "Style spec must include 'property' and 'expected'"}

        element = await find_element(page, target)
        if not element:
            return {"status": "failed", "error": f"Element not found: {target}"}

        await expect(element).to_have_css(css_property, expected_value, timeout=5000)
        return {"status": "passed"}
    except json.JSONDecodeError:
        return {"status": "failed", "error": f"Invalid style spec JSON: {value}"}
    except Exception as e:
        return {"status": "failed", "error": f"Style assertion failed: {str(e)}"}


async def execute_press_key(page: Page, step: dict, base_url: str) -> dict[str, Any]:
    """Press a keyboard key.

    Args:
        page: Playwright Page instance
        step: Step dict with "value" containing key name (e.g., "Enter", "Tab")
        base_url: Base URL (unused but included for consistency)

    Returns:
        Result dict with status
    """
    key = step.get("value", "")

    if not key:
        return {"status": "failed", "error": "No key provided for press_key action"}

    try:
        await page.keyboard.press(key)
        return {"status": "passed"}
    except Exception as e:
        return {"status": "failed", "error": f"Key press failed: {str(e)}"}


async def execute_screenshot(page: Page, step: dict, base_url: str) -> dict[str, Any]:
    """Take a screenshot.

    Args:
        page: Playwright Page instance
        step: Step dict with optional "value" (filename) and "target" (element)
        base_url: Base URL (unused but included for consistency)

    Returns:
        Result dict with status and screenshot bytes
    """
    filename = step.get("value", "screenshot.png")
    target = step.get("target")

    try:
        if target:
            # Screenshot specific element
            element = await find_element(page, target)
            if not element:
                return {"status": "failed", "error": f"Element not found: {target}"}
            screenshot_bytes = await element.screenshot(type="png")
        else:
            # Full page screenshot
            screenshot_bytes = await page.screenshot(type="png", full_page=False)

        return {"status": "passed", "screenshot": screenshot_bytes}
    except Exception as e:
        return {"status": "failed", "error": f"Screenshot failed: {str(e)}"}


async def execute_back(page: Page, step: dict, base_url: str) -> dict[str, Any]:
    """Navigate back in browser history.

    Args:
        page: Playwright Page instance
        step: Step dict (unused)
        base_url: Base URL (unused)

    Returns:
        Result dict with status
    """
    try:
        await page.go_back(wait_until="domcontentloaded", timeout=10000)
        return {"status": "passed"}
    except Exception as e:
        return {"status": "failed", "error": f"Back navigation failed: {str(e)}"}


async def execute_fill_form(page: Page, step: dict, base_url: str) -> dict[str, Any]:
    """Fill multiple form fields at once.

    Args:
        page: Playwright Page instance
        step: Step dict with "value" containing JSON {field: value} mapping
        base_url: Base URL (unused but included for consistency)

    Returns:
        Result dict with status
    """
    value = step.get("value", "{}")

    try:
        # Parse fields
        if isinstance(value, str):
            fields = json.loads(value)
        else:
            fields = value

        if not fields or not isinstance(fields, dict):
            return {"status": "failed", "error": "No fields provided for fill_form action"}

        # Fill each field
        for field_name, field_value in fields.items():
            element = await find_input_element(page, field_name)
            if not element:
                element = await find_element(page, field_name)

            if not element:
                return {"status": "failed", "error": f"Field not found: {field_name}"}

            await element.fill(str(field_value), timeout=5000)

        return {"status": "passed"}
    except json.JSONDecodeError:
        return {"status": "failed", "error": f"Invalid JSON for fields: {value}"}
    except Exception as e:
        return {"status": "failed", "error": f"Fill form failed: {str(e)}"}


async def execute_upload(page: Page, step: dict, base_url: str) -> dict[str, Any]:
    """Upload files to a file input.

    Args:
        page: Playwright Page instance
        step: Step dict with "value" containing comma-separated file paths
        base_url: Base URL (unused but included for consistency)

    Returns:
        Result dict with status
    """
    value = step.get("value", "")
    target = step.get("target")

    if not value:
        return {"status": "failed", "error": "No file paths provided for upload action"}

    try:
        # Parse paths
        paths = [p.strip() for p in value.split(",") if p.strip()]

        if not paths:
            return {"status": "failed", "error": "No valid file paths provided"}

        if target:
            # Find specific file input
            element = await find_element(page, target)
            if not element:
                return {"status": "failed", "error": f"File input not found: {target}"}
            await element.set_input_files(paths)
        else:
            # Find first file input on page
            file_input = page.locator('input[type="file"]').first
            await file_input.set_input_files(paths)

        return {"status": "passed"}
    except Exception as e:
        return {"status": "failed", "error": f"Upload failed: {str(e)}"}


async def execute_drag(page: Page, step: dict, base_url: str) -> dict[str, Any]:
    """Drag an element to another location.

    Args:
        page: Playwright Page instance
        step: Step dict with "target" (source) and "value" (destination)
        base_url: Base URL (unused but included for consistency)

    Returns:
        Result dict with status
    """
    source = step.get("target", "")
    destination = step.get("value", "")

    if not source or not destination:
        return {"status": "failed", "error": "Source and destination required for drag action"}

    try:
        source_element = await find_element(page, source)
        if not source_element:
            return {"status": "failed", "error": f"Source element not found: {source}"}

        dest_element = await find_element(page, destination)
        if not dest_element:
            return {"status": "failed", "error": f"Destination element not found: {destination}"}

        await source_element.drag_to(dest_element)
        return {"status": "passed"}
    except Exception as e:
        return {"status": "failed", "error": f"Drag failed: {str(e)}"}


async def execute_evaluate(page: Page, step: dict, base_url: str) -> dict[str, Any]:
    """Execute custom JavaScript code.

    Args:
        page: Playwright Page instance
        step: Step dict with "value" containing JavaScript code
        base_url: Base URL (unused but included for consistency)

    Returns:
        Result dict with status and optional result
    """
    code = step.get("value", "")

    if not code:
        return {"status": "failed", "error": "No code provided for evaluate action"}

    try:
        result = await page.evaluate(code)
        return {"status": "passed", "result": result}
    except Exception as e:
        return {"status": "failed", "error": f"JavaScript evaluation failed: {str(e)}"}


async def execute_wait_for_page(page: Page, step: dict, base_url: str) -> dict[str, Any]:
    """Wait for page to finish loading.

    Args:
        page: Playwright Page instance
        step: Step dict with optional "value" containing load state:
              - "load" (default): Wait for load event
              - "domcontentloaded": Wait for DOMContentLoaded event
              - "networkidle": Wait for network to be idle
        base_url: Base URL (unused but included for consistency)

    Returns:
        Result dict with status
    """
    logger = get_logger(__name__)

    load_state = step.get("value", "load").lower().strip()

    # Map common variations to valid Playwright states
    state_map = {
        "load": "load",
        "loaded": "load",
        "domcontentloaded": "domcontentloaded",
        "dom": "domcontentloaded",
        "networkidle": "networkidle",
        "idle": "networkidle",
        "network": "networkidle",
    }

    state = state_map.get(load_state, "load")

    logger.info(f"wait_for_page: waiting for '{state}' state, current URL: {page.url}")

    try:
        # First, give a small delay to allow any pending navigation to start
        await asyncio.sleep(0.1)

        # Wait for the load state
        await page.wait_for_load_state(state, timeout=30000)

        logger.info(f"wait_for_page: '{state}' state reached, URL: {page.url}")
        return {"status": "passed"}
    except Exception as e:
        logger.error(f"wait_for_page: failed - {str(e)}")
        return {"status": "failed", "error": f"Timeout waiting for page {state}: {str(e)}"}


# Action dispatcher mapping
ACTION_HANDLERS = {
    "navigate": execute_navigate,
    "click": execute_click,
    "type": execute_type,
    "hover": execute_hover,
    "select": execute_select,
    "wait": execute_wait,
    "wait_for_page": execute_wait_for_page,
    "assert_text": execute_assert_text,
    "assert_element": execute_assert_element,
    "assert_style": execute_assert_style,
    "press_key": execute_press_key,
    "screenshot": execute_screenshot,
    "back": execute_back,
    "fill_form": execute_fill_form,
    "upload": execute_upload,
    "drag": execute_drag,
    "evaluate": execute_evaluate,
}


async def execute_action(page: Page, step: dict, base_url: str) -> dict[str, Any]:
    """Execute a single test action.

    Args:
        page: Playwright Page instance
        step: Step dict with "action", "target", "value", "description"
        base_url: Base URL for relative paths

    Returns:
        Result dict with "status" and optional "error"
    """
    action = step.get("action", "")

    if not action:
        return {"status": "failed", "error": "No action specified in step"}

    handler = ACTION_HANDLERS.get(action)
    if not handler:
        return {"status": "failed", "error": f"Unknown action: {action}"}

    return await handler(page, step, base_url)
