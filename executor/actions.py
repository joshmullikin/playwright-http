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
    find_by_aria_path,
    get_target_variations,
    is_css_selector,
)

_log = get_logger(__name__)


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


async def _find_nearest_clickable(
    page: Page, page_x: float, page_y: float, target_text: str = "", radius: int = 200
) -> int:
    """Find the nearest clickable element to recorded coordinates.

    Returns the nth-index among clickable elements, or -1 if none within radius.
    If target_text is provided, filters to elements containing that text.
    """
    _CLICKABLE_SEL = (
        "button, a, [role='button'], [role='menuitem'], "
        "[aria-haspopup], input[type='button'], input[type='submit']"
    )
    return await page.evaluate(
        """([recX, recY, sel, filterText, maxDist]) => {
            const lower = filterText ? filterText.toLowerCase() : "";
            const all = document.querySelectorAll(sel);
            let bestDist = Infinity;
            let bestIdx = -1;
            all.forEach((el, i) => {
                if (lower) {
                    const text = (el.textContent || '').trim().toLowerCase();
                    if (text !== lower && !text.includes(lower)) return;
                }
                const rect = el.getBoundingClientRect();
                if (rect.width === 0 && rect.height === 0) return;
                const cx = rect.left + rect.width / 2 + window.scrollX;
                const cy = rect.top + rect.height / 2 + window.scrollY;
                const dist = Math.hypot(cx - recX, cy - recY);
                if (dist < bestDist) {
                    bestDist = dist;
                    bestIdx = i;
                }
            });
            return bestDist < maxDist ? bestIdx : -1;
        }""",
        [page_x, page_y, _CLICKABLE_SEL, target_text, radius],
    )


def _fuzzy_css_selector(selector: str) -> str | None:
    """Generate a fuzzy CSS selector by stripping trailing numeric IDs.

    When an exact selector like [data-testid="move-folder-50"] fails (the record
    was deleted), this produces a prefix match [data-testid^="move-folder-"]
    so auto-heal can find a similar element and use coordinates to disambiguate.

    Examples:
        [data-testid="move-folder-50"]      → [data-testid^="move-folder-"]
        [data-testid="status-trigger-71"]   → [data-testid^="status-trigger-"]
        #login-btn-5                        → [id^="login-btn-"]
        [data-testid="login-form"]          → None (no numeric suffix)
        .my-class                           → None (not supported)
    """
    # Attribute selectors: [attr="prefix-123"] or [attr='prefix-123']
    m = re.match(r"""^\[(\w[\w-]*)=["'](.+?)-\d+["']\]$""", selector)
    if m:
        attr, prefix = m.group(1), m.group(2)
        return f'[{attr}^="{prefix}-"]'

    # ID selectors: #prefix-123
    m = re.match(r"^#([\w-]+)-\d+$", selector)
    if m:
        prefix = m.group(1)
        return f'[id^="{prefix}-"]'

    return None


async def _click_nearest_from_locator(
    locator, page_x: float, page_y: float, max_dist: float = 300
) -> bool:
    """Click the element in a multi-match locator nearest to given coordinates.

    Used by CSS auto-heal: after [data-testid^="move-folder-"] matches N elements,
    pick the one closest to where the user originally clicked.
    """
    count = await locator.count()
    best_idx = -1
    best_dist = float("inf")

    for i in range(count):
        try:
            bbox = await locator.nth(i).bounding_box()
            if not bbox:
                continue
            cx = bbox["x"] + bbox["width"] / 2
            cy = bbox["y"] + bbox["height"] / 2
            dist = ((cx - page_x) ** 2 + (cy - page_y) ** 2) ** 0.5
            if dist < best_dist:
                best_dist = dist
                best_idx = i
        except Exception:
            continue

    if best_idx >= 0 and best_dist <= max_dist:
        await locator.nth(best_idx).click(timeout=5000)
        return True
    return False


async def _click_nearest(page: Page, page_x: float, page_y: float, target_text: str = "", radius: int = 200) -> bool:
    """Click the nearest clickable element to coordinates. Returns True if clicked."""
    _CLICKABLE_SEL = (
        "button, a, [role='button'], [role='menuitem'], "
        "[aria-haspopup], input[type='button'], input[type='submit']"
    )
    _log.info(
        f"_click_nearest: searching for '{target_text}' near ({page_x}, {page_y}) radius={radius}"
    )
    idx = await _find_nearest_clickable(page, page_x, page_y, target_text, radius)
    if idx >= 0:
        el = page.locator(_CLICKABLE_SEL).nth(idx)
        tag = await el.evaluate("el => el.tagName + ' | ' + el.textContent.trim().slice(0, 60)")
        _log.info(f"_click_nearest: found idx={idx} → {tag}")
        await el.click(timeout=5000)
        return True
    _log.warning(f"_click_nearest: no element found for '{target_text}' within {radius}px")
    return False


async def execute_click(page: Page, step: dict, base_url: str) -> dict[str, Any]:
    """Click on an element with waterfall resolution and post-click verification.

    After a click succeeds:
      - Detects newly opened dialogs and waits for animation to complete
      - For navigation clicks: waits for URL change and page load
      - For other clicks: brief settle time for DOM updates
    """
    url_before = page.url

    # Capture dialog state before click to detect new dialogs
    try:
        dialogs_before = await page.locator("[role='dialog']:visible").count()
    except Exception:
        dialogs_before = 0

    result = await _execute_click_waterfall(page, step, base_url)

    if result.get("status") == "passed":
        target = step.get("target", "")
        resolved_by = result.get("resolved_by", "unknown")

        # For navigation clicks, verify URL actually changed
        if step.get("causes_navigation"):
            try:
                await page.wait_for_url(lambda url: url != url_before, timeout=5000)
                await page.wait_for_load_state("domcontentloaded", timeout=5000)
            except Exception:
                _log.warning(
                    f"execute_click: navigation verification FAILED — "
                    f"URL unchanged after clicking '{target}' (still {url_before})"
                )
                return {
                    "status": "failed",
                    "error": f"Click on '{target}' did not cause navigation (URL still: {url_before})",
                    "resolved_by": resolved_by,
                }
        else:
            # Non-navigation clicks: settle time for DOM updates + dialog detection.
            # 0.3s gives Radix UI dialogs enough time to animate into visibility
            # (they take ~200-300ms). Checking earlier misses them.
            await asyncio.sleep(0.3)
            try:
                dialogs_after = await page.locator("[role='dialog']:visible").count()
                if dialogs_after > dialogs_before:
                    _log.info(f"execute_click: dialog appeared after clicking '{target}', waiting for animation")
                    await asyncio.sleep(0.2)
            except Exception:
                pass

    return result


async def _execute_click_waterfall(page: Page, step: dict, base_url: str) -> dict[str, Any]:
    """Click on an element using waterfall resolution.

    Locator Waterfall (tries each tier in order):
      1. UTML (text match via target) — unique match → click
      1b. UTML + coordinates — multiple matches → pick nearest to recorded position
      2. CSS selector (locators.css) — unique match → click
      3. Aria contextual path (locators.ariaPath) — unique match → click
      4. Hover-submenu recovery — element hidden in dropdown

    If ALL tiers find 0 matches (timing issue), retry up to 3 times with 2s sleep.
    Returns resolved_by in the result dict to track which strategy succeeded.

    Note: coordinate-only fallback (no text filter) was intentionally removed.
    Clicking a random nearby element produces false-positive passes that are
    worse than an honest failure.
    """
    target = step.get("target", "")
    coords = step.get("coordinates")  # {x, y, pageX, pageY} from recorder
    locators = step.get("locators") or {}

    # Merge step-level coordinates into locators if not already there
    if coords and "coordinates" not in locators:
        locators["coordinates"] = coords

    if not target and not locators:
        return {"status": "failed", "error": "No target or locators provided for click action"}

    _log.info(
        f"execute_click: target={target!r}  "
        f"is_css={is_css_selector(target)}  "
        f"locators={list(locators.keys()) if locators else 'NONE'}  "
        f"coords={'YES pageX=' + str(coords.get('pageX')) if coords else 'NONE'}"
    )

    # Nav menu items sometimes record as "HeadingSubtitle" (no separator).
    # Extract just the heading portion for fallback matching.
    def _short_target(t: str) -> str | None:
        if len(t) <= 40:
            return None
        m = re.search(r'[a-z]([A-Z])', t[5:])
        if m:
            return t[:5 + m.start() + 1].strip()
        return t[:40].strip()

    # ── Waterfall resolution with retry ─────────────────────────────────────
    max_attempts = 3
    last_error = ""

    for attempt in range(max_attempts):
        if attempt > 0:
            _log.info(f"execute_click: retry {attempt}/{max_attempts - 1} for '{target}'")
            await asyncio.sleep(2)

        # ── Tier 1: UTML (text match via target field) ──────────────────────
        if target and not is_css_selector(target):
            target_variants = [target]
            short = _short_target(target)
            if short:
                target_variants.append(short)

            for tv in target_variants:
                element = await find_clickable_element(page, tv)
                if not element:
                    element = await find_element(page, tv)
                if not element:
                    continue

                # Check if multiple matches exist (scoped to modal if visible)
                count_scope = page
                try:
                    dialog_loc = page.locator("[role='dialog']:visible, [role='alertdialog']:visible")
                    if await dialog_loc.count() > 0:
                        count_scope = dialog_loc.last
                except Exception:
                    pass

                count = 1
                for variation in get_target_variations(tv):
                    pattern = re.compile(re.escape(variation), re.IGNORECASE)
                    # Only count interactive elements — get_by_text matches headings,
                    # labels, etc. which inflates the count (e.g. "Move to Folder"
                    # title + "Move" button → count=2, triggering Tier 1b wrongly).
                    for loc in [
                        count_scope.get_by_role("button", name=pattern),
                        count_scope.get_by_role("link", name=pattern),
                        count_scope.get_by_role("menuitem", name=pattern),
                    ]:
                        try:
                            c = await loc.count()
                            if c > count:
                                count = c
                        except Exception:
                            pass

                # Resolve coordinates for proximity validation
                loc_coords = locators.get("coordinates") or coords

                if count == 1:
                    # Unique match — validate proximity if coordinates available
                    if loc_coords:
                        try:
                            bbox = await element.bounding_box()
                            if bbox:
                                page_x = loc_coords.get("pageX") or loc_coords.get("x", 0)
                                page_y = loc_coords.get("pageY") or loc_coords.get("y", 0)
                                cx = bbox["x"] + bbox["width"] / 2
                                cy = bbox["y"] + bbox["height"] / 2
                                dist = ((cx - page_x) ** 2 + (cy - page_y) ** 2) ** 0.5
                                if dist > 250:
                                    # Element is far from recorded position — wrong match
                                    _log.info(
                                        f"execute_click: unique UTML match '{tv}' is {dist:.0f}px "
                                        f"from recorded coords — trying coordinate-based click"
                                    )
                                    if await _click_nearest(page, page_x, page_y, tv):
                                        _log.info(f"execute_click: resolved_by=utml+coordinates for '{tv}'")
                                        return {"status": "passed", "resolved_by": "utml+coordinates"}
                                    else:
                                        last_error = f"Unique match for '{tv}' too far from recorded position ({dist:.0f}px)"
                                        break
                        except Exception:
                            pass  # Bounding box failed — fall through to normal click
                    # Click the unique match
                    try:
                        await element.click(timeout=5000)
                        _log.info(f"execute_click: resolved_by=utml for '{tv}'")
                        return {"status": "passed", "resolved_by": "utml"}
                    except Exception as e:
                        last_error = str(e)
                else:
                    # ── Tier 1b: UTML + Coordinate disambiguation ───────────
                    _log.info(f"execute_click: Tier 1b — {count} matches for '{tv}', trying coordinates")
                    if loc_coords:
                        page_x = loc_coords.get("pageX") or loc_coords.get("x", 0)
                        page_y = loc_coords.get("pageY") or loc_coords.get("y", 0)
                        _log.info(f"execute_click: Tier 1b coords: pageX={page_x}, pageY={page_y}")
                        if page_x and page_y:
                            try:
                                if await _click_nearest(page, page_x, page_y, tv):
                                    _log.info(
                                        f"execute_click: resolved_by=utml+coordinates "
                                        f"for '{tv}' ({count} matches, picked nearest)"
                                    )
                                    return {"status": "passed", "resolved_by": "utml+coordinates"}
                            except Exception as e:
                                last_error = str(e)
                    # Multi-match with no coordinates — fall through to Tier 2
                    last_error = f"Multiple matches ({count}) for '{tv}', no coordinates to disambiguate"
                break  # Only try the first variant that found elements

        # ── Tier 1 (CSS target): direct CSS selector as target ──────────────
        if target and is_css_selector(target):
            element = await find_element(page, target)
            if element:
                try:
                    await element.click(timeout=5000)
                    _log.info(f"execute_click: resolved_by=css (target) for '{target}'")
                    return {"status": "passed", "resolved_by": "css"}
                except Exception as e:
                    last_error = str(e)
            else:
                last_error = f"CSS selector not found: {target}"

        # ── Tier 2: CSS selector from locators ──────────────────────────────
        css_sel = locators.get("css", "")
        if css_sel and css_sel != target:
            try:
                loc = page.locator(css_sel)
                if await loc.count() > 0:
                    await loc.first.click(timeout=5000)
                    _log.info(f"execute_click: resolved_by=css (locators) for '{css_sel}'")
                    return {"status": "passed", "resolved_by": "css"}
            except Exception as e:
                last_error = str(e)

        # ── Tier 2b: CSS auto-heal — fuzzy selector + coordinates ─────────
        # When exact CSS fails (e.g. record deleted), strip the numeric ID
        # suffix and try prefix match, using coordinates to disambiguate.
        loc_coords = locators.get("coordinates") or coords
        for sel in [target, css_sel]:
            if not sel:
                continue
            fuzzy = _fuzzy_css_selector(sel)
            if not fuzzy:
                continue
            try:
                fuzzy_loc = page.locator(fuzzy)
                fuzzy_count = await fuzzy_loc.count()
                if fuzzy_count == 0:
                    continue
                if fuzzy_count == 1:
                    # Single match — click it directly
                    await fuzzy_loc.first.click(timeout=5000)
                    _log.info(
                        f"execute_click: resolved_by=css-autoheal "
                        f"('{sel}' → '{fuzzy}', 1 match)"
                    )
                    return {"status": "passed", "resolved_by": "css-autoheal"}
                if loc_coords:
                    page_x = loc_coords.get("pageX") or loc_coords.get("x", 0)
                    page_y = loc_coords.get("pageY") or loc_coords.get("y", 0)
                    if page_x and page_y:
                        if await _click_nearest_from_locator(fuzzy_loc, page_x, page_y):
                            _log.info(
                                f"execute_click: resolved_by=css-autoheal "
                                f"('{sel}' → '{fuzzy}', {fuzzy_count} matches, picked nearest)"
                            )
                            return {"status": "passed", "resolved_by": "css-autoheal"}
                last_error = (
                    f"CSS auto-heal: '{fuzzy}' found {fuzzy_count} matches "
                    f"but no coordinates to disambiguate"
                )
            except Exception as e:
                last_error = str(e)

        # ── Tier 3: Aria contextual path ────────────────────────────────────
        aria_path = locators.get("ariaPath", "")
        if aria_path:
            element = await find_by_aria_path(page, aria_path)
            if element:
                try:
                    await element.click(timeout=5000)
                    _log.info(f"execute_click: resolved_by=ariaPath for '{aria_path}'")
                    return {"status": "passed", "resolved_by": "ariaPath"}
                except Exception as e:
                    last_error = str(e)

        # ── Tier 4: Hover-submenu recovery ──────────────────────────────────
        # The element may be hidden inside a CSS hover-triggered nav dropdown.
        if target and not is_css_selector(target):
            hover_result = await _try_hover_submenu(page, target)
            if hover_result:
                return hover_result

        # If we got here, all tiers found 0 matches — retry
        if not last_error:
            last_error = f"All locator strategies exhausted for '{target}'"
        _log.debug(f"execute_click: attempt {attempt + 1} failed: {last_error}")

    # All retries exhausted
    _log.warning(f"execute_click: FAILED after {max_attempts} attempts for '{target}'")
    return {"status": "failed", "error": last_error, "resolved_by": "failed"}


async def _try_hover_submenu(page: Page, target: str) -> dict[str, Any] | None:
    """Try to reveal and click a hidden element by hovering its nav trigger.

    Returns a result dict if successful, None if this strategy doesn't apply.
    """
    trigger_chain = await page.evaluate(
        """(targetText) => {
            const lower = targetText.toLowerCase();

            function isElementHidden(el) {
                if (!el || el === document.body) return false;
                const style = window.getComputedStyle(el);
                if (style.display === 'none' ||
                    style.visibility === 'hidden' ||
                    parseFloat(style.opacity) === 0) return true;
                if (el.getAttribute('aria-hidden') === 'true') return true;
                return false;
            }

            function findTriggerSibling(hiddenContainer, usedTexts) {
                const parent = hiddenContainer.parentElement;
                if (!parent) return null;
                for (const sib of parent.children) {
                    if (sib === hiddenContainer) continue;
                    const sibStyle = window.getComputedStyle(sib);
                    const sibVisible =
                        sibStyle.display !== 'none' &&
                        sibStyle.visibility !== 'hidden' &&
                        parseFloat(sibStyle.opacity) !== 0 &&
                        sib.offsetWidth > 0 &&
                        sib.getAttribute('aria-hidden') !== 'true';
                    if (sibVisible && (
                        sib.tagName === 'A' ||
                        sib.tagName === 'BUTTON' ||
                        sib.getAttribute('role') === 'menuitem' ||
                        sib.getAttribute('role') === 'link'
                    )) {
                        const text = sib.textContent.trim();
                        if (text && text.toLowerCase() !== lower && !usedTexts.has(text)) {
                            return text;
                        }
                    }
                }
                return null;
            }

            let matchEl = null;
            const shortLower = lower.length > 20 ? lower.slice(0, 30) : lower;
            for (const el of document.querySelectorAll('a, button, [role="menuitem"]')) {
                const text = el.textContent.trim().toLowerCase();
                if (text === lower || text.includes(lower) ||
                    (shortLower !== lower && text.includes(shortLower))) {
                    matchEl = el;
                    break;
                }
            }
            if (!matchEl) return [];

            const chain = [];
            const usedTexts = new Set();
            let el = matchEl.parentElement;
            while (el && el !== document.body) {
                if (isElementHidden(el)) {
                    const trigText = findTriggerSibling(el, usedTexts);
                    if (trigText) {
                        chain.unshift(trigText);
                        usedTexts.add(trigText);
                    }
                }
                el = el.parentElement;
            }
            return chain;
        }""",
        target,
    )

    if not trigger_chain:
        return None

    _log.info(f"execute_click: hover chain {trigger_chain} → '{target}'")

    # Hover each trigger in order (outermost first for multi-level menus)
    for trig_text in trigger_chain:
        trig_loc = page.get_by_role("link", name=trig_text).or_(
            page.get_by_role("button", name=trig_text)
        )
        if await trig_loc.count() == 0:
            trig_loc = page.get_by_text(trig_text, exact=True)
        if await trig_loc.count() > 0:
            try:
                await trig_loc.first.hover(timeout=2000)
                await page.wait_for_timeout(500)
            except Exception:
                pass

    # After hovering, click the target
    for loc in [
        page.get_by_role("link", name=target).first,
        page.get_by_role("menuitem", name=target).first,
        page.get_by_text(target, exact=True).first,
    ]:
        try:
            if await loc.is_visible(timeout=400):
                await loc.click(timeout=3000)
                return {"status": "passed", "resolved_by": "hover+utml"}
        except Exception:
            continue

    # Last resort: click-toggled dropdowns (JS onclick instead of CSS hover)
    for trig_text in reversed(trigger_chain):
        trig_loc = page.get_by_role("link", name=trig_text).or_(
            page.get_by_role("button", name=trig_text)
        )
        if await trig_loc.count() > 0:
            try:
                await trig_loc.first.click(timeout=2000)
                await page.wait_for_timeout(400)
                for loc in [
                    page.get_by_role("link", name=target).first,
                    page.get_by_text(target, exact=True).first,
                ]:
                    try:
                        if await loc.is_visible(timeout=400):
                            await loc.click(timeout=3000)
                            return {"status": "passed", "resolved_by": "hover+utml"}
                    except Exception:
                        continue
            except Exception:
                continue

    return None


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


async def _find_combobox_by_label(page: Page, label_text: str):
    """Find a combobox trigger by label proximity (for Radix UI / shadcn patterns).

    Walks upward from every <label> until it finds a sibling/child combobox.
    Returns the nth-index among all comboboxes on the page so we can use
    page.get_by_role("combobox").nth(idx).
    """
    result = await page.evaluate(
        """(labelText) => {
            const lower = labelText.toLowerCase();
            // Also try with asterisk stripped
            const labels = Array.from(document.querySelectorAll('label, [class*="label" i]'));
            for (const label of labels) {
                const text = label.textContent.replace(/[*:]/g, '').trim().toLowerCase();
                if (text === lower || text.includes(lower)) {
                    let container = label.parentElement;
                    for (let depth = 0; depth < 5 && container; depth++) {
                        const cb = container.querySelector(
                            "[role='combobox'], [aria-haspopup='listbox'], [aria-haspopup='true']"
                        );
                        if (cb) {
                            const all = Array.from(document.querySelectorAll("[role='combobox']"));
                            return all.indexOf(cb);
                        }
                        container = container.parentElement;
                    }
                }
            }
            return -1;
        }""",
        label_text,
    )
    if result >= 0:
        comboboxes = page.get_by_role("combobox")
        if await comboboxes.count() > result:
            _log.debug(f"_find_combobox_by_label: found combobox #{result} for label '{label_text}'")
            return comboboxes.nth(result)
    return None


async def _wait_for_options(page: Page, timeout: int = 3000) -> bool:
    """Wait for dropdown options to appear in the DOM after clicking a trigger."""
    try:
        await page.wait_for_selector(
            "[role='option'], [role='menuitem']",
            state="visible",
            timeout=timeout,
        )
        return True
    except Exception:
        return False


async def _click_option_by_text(page: Page, value: str) -> bool:
    """Click a dropdown option by text content — JS-based for portal/escaping robustness."""
    return await page.evaluate(
        """(targetText) => {
            const normalize = s => s.replace(/\\s+/g, ' ').trim();
            const target = normalize(targetText);
            const roles = ['option', 'menuitem', 'listitem'];
            for (const role of roles) {
                for (const opt of document.querySelectorAll(`[role='${role}']`)) {
                    if (normalize(opt.textContent) === target ||
                        normalize(opt.textContent).startsWith(target)) {
                        opt.click();
                        return true;
                    }
                }
            }
            return false;
        }""",
        value,
    )


async def execute_select(page: Page, step: dict, base_url: str) -> dict[str, Any]:
    """Select an option from a dropdown — native <select> or custom combobox.

    Strategy:
    1. Strip asterisks/colons from target (labels often end with " *" or ":")
    2. Find the element: standard finder → label-proximity combobox search
    3. Native <select>: use Playwright's select_option
    4. Custom combobox: click trigger → wait for options → filter/JS click

    Args:
        page: Playwright Page instance
        step: Step dict with "target" (dropdown label) and "value" (option text)
        base_url: Base URL (unused but included for consistency)

    Returns:
        Result dict with status
    """
    target = step.get("target", "")
    value = step.get("value", "")

    if not target:
        return {"status": "failed", "error": "No target provided for select action"}

    # Strip asterisks and trailing punctuation — form labels often end with " *" or ":"
    clean_target = re.sub(r"[\s\*\:]+$", "", target).strip()

    try:
        # For select, target is always a form label — lead with label-proximity search.
        # find_element falls back to get_by_text() which matches <label> elements
        # themselves (not the combobox trigger), so clicking them opens nothing.
        element = await _find_combobox_by_label(page, clean_target)
        found_via = "label_proximity"

        if not element:
            element = await find_element(page, clean_target)
            found_via = "find_element"

        if not element:
            return {"status": "failed", "error": f"Element not found: {target}"}

        tag_name = await element.evaluate("el => el.tagName.toLowerCase()")
        _log.info(f"execute_select: found element tag='{tag_name}' via {found_via} for target='{target}'")

        # If find_element returned a non-interactive element (label, span, p, div),
        # try label-proximity search to get the actual combobox button.
        NON_INTERACTIVE = {"label", "span", "p", "div", "h1", "h2", "h3", "h4", "li"}
        if tag_name in NON_INTERACTIVE and found_via == "find_element":
            _log.info(f"execute_select: got non-interactive tag '{tag_name}', retrying with label-proximity")
            label_element = await _find_combobox_by_label(page, clean_target)
            if label_element:
                element = label_element
                tag_name = await element.evaluate("el => el.tagName.toLowerCase()")

        if tag_name == "select":
            # Check for hidden Radix UI backing select — need the combobox button instead.
            is_hidden = await element.evaluate(
                "el => { const r = el.getBoundingClientRect(); return r.width < 5 || r.height < 5; }"
            )
            if is_hidden:
                _log.info("execute_select: found hidden <select>, switching to label-proximity combobox search")
                element = await _find_combobox_by_label(page, clean_target)
                if not element:
                    return {"status": "failed", "error": f"Could not find visible combobox for: {target}"}
                tag_name = await element.evaluate("el => el.tagName.toLowerCase()")
            else:
                values = [value] if isinstance(value, str) else value
                await element.select_option(values, timeout=5000)
                return {"status": "passed"}

        # Custom combobox path — scroll into view and click trigger
        await element.scroll_into_view_if_needed(timeout=3000)
        await element.click(timeout=5000)
        _log.debug(f"execute_select: clicked combobox trigger, waiting for options...")

        # Wait for options to actually appear in the DOM (most reliable approach)
        options_appeared = await _wait_for_options(page, timeout=3000)
        if not options_appeared:
            await page.wait_for_timeout(500)  # last-ditch wait

        # Log what options are available for diagnostics
        available = await page.evaluate("""
            () => Array.from(document.querySelectorAll("[role='option'],[role='menuitem']"))
                       .map(el => el.textContent.replace(/\\s+/g,' ').trim())
                       .filter(Boolean)
        """)
        _log.debug(f"execute_select: available options after open: {available}")

        # Strategy 1: Playwright filter (has_text is substring, handles whitespace variations)
        option_locator = page.locator("[role='option'], [role='menuitem']").filter(has_text=value)
        count = await option_locator.count()
        if count > 0:
            await option_locator.first.click(timeout=3000)
            await page.wait_for_timeout(200)
            return {"status": "passed"}

        # Strategy 2: Partial match — strip parenthetical qualifier if no exact match
        # e.g. "Key Replacement (Make New Key)" → try "Key Replacement"
        partial = value.split("(")[0].strip()
        if partial and partial != value:
            option_partial = page.locator("[role='option'], [role='menuitem']").filter(has_text=partial)
            if await option_partial.count() > 0:
                await option_partial.first.click(timeout=3000)
                await page.wait_for_timeout(200)
                return {"status": "passed"}

        # Strategy 3: JS click with whitespace-normalized comparison
        clicked = await _click_option_by_text(page, value)
        if clicked:
            await page.wait_for_timeout(200)
            return {"status": "passed"}

        # Strategy 4: Playwright role locators
        for locator in [
            page.get_by_role("option", name=value, exact=True),
            page.get_by_role("option", name=value),
            page.get_by_role("menuitem", name=value),
        ]:
            try:
                if await locator.count() > 0:
                    await locator.first.click(timeout=3000)
                    await page.wait_for_timeout(200)
                    return {"status": "passed"}
            except Exception:
                continue

        available_str = ", ".join(f'"{o}"' for o in available[:5])
        return {
            "status": "failed",
            "error": f"Could not find option '{value}' in dropdown '{target}'. Available: [{available_str}]",
        }

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

    Strategy (most to least strict):
    1. Wait for page to settle (networkidle) so dynamic content is rendered
    2. page.get_by_text() with exact=False — Playwright substring match
    3. page.locator filter — broader element search
    4. Raw body innerText check — catches text in any element regardless of role

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
        # Wait for any in-flight navigation / AJAX to settle
        try:
            await page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            pass  # continue even if networkidle times out

        # Strategy 1: get_by_text with exact=False (substring match)
        try:
            locator = page.get_by_text(text, exact=False)
            await expect(locator.first).to_be_visible(timeout=5000)
            return {"status": "passed"}
        except Exception:
            pass

        # Strategy 2: regex match (case-insensitive, handles partial element text)
        try:
            pattern = re.compile(re.escape(text), re.IGNORECASE)
            locator = page.get_by_text(pattern)
            if await locator.count() > 0:
                await expect(locator.first).to_be_visible(timeout=3000)
                return {"status": "passed"}
        except Exception:
            pass

        # Strategy 3: body innerText scan — catches text in any element
        try:
            body_text = await page.evaluate("() => document.body.innerText")
            if text.lower() in body_text.lower():
                return {"status": "passed"}
        except Exception:
            pass

        # All strategies failed — report what IS visible for diagnostics
        try:
            visible_text = await page.evaluate(
                "() => document.body.innerText.replace(/\\s+/g, ' ').trim().slice(0, 300)"
            )
        except Exception:
            visible_text = "(could not read page text)"

        return {
            "status": "failed",
            "error": f'Text not found: "{text}". Page contains: {visible_text}',
        }

    except Exception as e:
        return {"status": "failed", "error": f"Assert text failed: {str(e)}"}


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


async def execute_assert_url(page: Page, step: dict, base_url: str) -> dict[str, Any]:
    """Assert that current URL matches a regex pattern.

    Args:
        page: Playwright Page instance
        step: Step dict with "value" containing regex pattern
        base_url: Base URL (unused but included for consistency)

    Returns:
        Result dict with status
    """
    pattern = step.get("value", "")

    if not pattern:
        return {"status": "failed", "error": "No regex pattern provided for assert_url action"}

    try:
        current_url = page.url
        regex = re.compile(pattern)
        
        if regex.search(current_url):
            return {"status": "passed"}
        else:
            return {
                "status": "failed",
                "error": f"URL mismatch. Current: {current_url}, Expected pattern: {pattern}"
            }
    except re.error as e:
        hint = ""
        if "*" in pattern and ".*" not in pattern:
            hint = " Hint: Use '.*' for wildcard matching in regex, not '*'."
        return {"status": "failed", "error": f"Invalid regex pattern: {pattern}. Error: {str(e)}.{hint}"}
    except Exception as e:
        return {"status": "failed", "error": f"URL assertion failed: {str(e)}"}


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


async def execute_capture_state(page: Page, step: dict, base_url: str) -> dict[str, Any]:
    """Capture current browser state (cookies + storage) for fixture caching.

    Args:
        page: Playwright Page instance
        step: Step dict (no target or value needed)
        base_url: Base URL (unused)

    Returns:
        Result dict with status and state data in result field
    """
    try:
        context = page.context

        # Get Playwright storage_state (cookies + origins with localStorage/sessionStorage)
        state = await context.storage_state()

        # Return state in result field for checkmate to cache
        return {
            "status": "passed",
            "result": {
                "url": page.url,
                "state": state
            }
        }
    except Exception as e:
        return {"status": "failed", "error": f"Failed to capture state: {str(e)}"}


async def execute_restore_state(page: Page, step: dict, base_url: str) -> dict[str, Any]:
    """Restore browser state from cached fixture data.

    Args:
        page: Playwright Page instance
        step: Step dict with "value" containing state JSON and "target" containing URL
        base_url: Base URL for relative URL resolution

    Returns:
        Result dict with status
    """
    import json

    try:
        # Get state from value
        value = step.get("value", "")
        if not value:
            return {"status": "failed", "error": "No state data provided for restore_state"}

        # Parse state JSON
        try:
            state_data = json.loads(value) if isinstance(value, str) else value
        except json.JSONDecodeError as e:
            return {"status": "failed", "error": f"Invalid state JSON: {str(e)}"}

        state = state_data.get("state")
        url = state_data.get("url") or step.get("target")

        if not state:
            return {"status": "failed", "error": "No state object found in value"}

        if not url:
            return {"status": "failed", "error": "No URL provided for restore_state"}

        # Add cookies and storage to context
        context = page.context
        await context.add_cookies(state.get("cookies", []))

        # Navigate to the cached URL to restore the browser to that page
        await page.goto(url, wait_until="load", timeout=30000)

        # Set localStorage and sessionStorage for each origin
        origins = state.get("origins", [])
        for origin_data in origins:
            origin = origin_data.get("origin")
            local_storage = origin_data.get("localStorage", [])
            session_storage = origin_data.get("sessionStorage", [])

            if local_storage:
                # Execute JavaScript to set localStorage items (use evaluate with args to avoid injection)
                for item in local_storage:
                    await page.evaluate(
                        "([key, value]) => window.localStorage.setItem(key, value)",
                        [item['name'], item['value']]
                    )

            if session_storage:
                # Execute JavaScript to set sessionStorage items
                for item in session_storage:
                    await page.evaluate(
                        "([key, value]) => window.sessionStorage.setItem(key, value)",
                        [item['name'], item['value']]
                    )

        return {"status": "passed"}
    except Exception as e:
        return {"status": "failed", "error": f"Failed to restore state: {str(e)}"}


async def execute_scroll(page: Page, step: dict, base_url: str) -> dict[str, Any]:
    """Scroll the page or scroll to a specific element.

    Supports multiple scroll modes via `value`:
      - "top": Scroll to top of page instantly
      - "bottom": Scroll to bottom of page instantly
      - "up": Scroll up by one viewport height
      - "down": Scroll down by one viewport height
      - "smooth_top": Slowly scroll to top (human-like)
      - "smooth_bottom": Slowly scroll to bottom (human-like)
      - A number (e.g., "500" or "-300"): Scroll by that many pixels (positive=down)

    If `target` is provided, scrolls that element into view instead.

    Args:
        page: Playwright Page instance
        step: Step dict with optional "target" and "value"
        base_url: Base URL (unused)

    Returns:
        Result dict with status
    """
    logger = get_logger(__name__)
    target = step.get("target")
    value = (step.get("value") or "down").strip().lower()

    try:
        # If target is a specific element (not "page"), scroll it into view
        if target and target.lower() != "page":
            logger.info(f"scroll: scrolling element '{target}' into view")
            element = await find_element(page, target)
            if element:
                await element.scroll_into_view_if_needed()
                await asyncio.sleep(0.3)
                return {"status": "passed"}
            else:
                return {"status": "failed", "error": f"Element not found: {target}"}

        # Page-level scroll
        if value == "top":
            logger.info("scroll: scrolling to top")
            await page.evaluate("window.scrollTo(0, 0)")

        elif value == "bottom":
            logger.info("scroll: scrolling to bottom")
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")

        elif value == "up":
            logger.info("scroll: scrolling up one viewport")
            await page.evaluate("window.scrollBy(0, -window.innerHeight)")

        elif value == "down":
            logger.info("scroll: scrolling down one viewport")
            await page.evaluate("window.scrollBy(0, window.innerHeight)")

        elif value == "smooth_top":
            logger.info("scroll: smooth scrolling to top")
            await page.evaluate("""
                async () => {
                    const delay = ms => new Promise(r => setTimeout(r, ms));
                    while (window.scrollY > 0) {
                        window.scrollBy(0, -200);
                        await delay(100);
                    }
                }
            """)

        elif value == "smooth_bottom":
            logger.info("scroll: smooth scrolling to bottom")
            await page.evaluate("""
                async () => {
                    const delay = ms => new Promise(r => setTimeout(r, ms));
                    let prev = -1;
                    while (window.scrollY !== prev) {
                        prev = window.scrollY;
                        window.scrollBy(0, 200);
                        await delay(100);
                    }
                }
            """)

        else:
            # Try as pixel amount
            try:
                pixels = int(value)
                logger.info(f"scroll: scrolling by {pixels}px")
                await page.evaluate(f"window.scrollBy(0, {pixels})")
            except ValueError:
                return {"status": "failed", "error": f"Unknown scroll value: {value}. Use top, bottom, up, down, smooth_top, smooth_bottom, or a pixel amount."}

        await asyncio.sleep(0.3)
        return {"status": "passed"}

    except Exception as e:
        logger.error(f"scroll: failed - {str(e)}")
        return {"status": "failed", "error": f"Scroll failed: {str(e)}"}


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
    "assert_url": execute_assert_url,
    "capture_state": execute_capture_state,
    "restore_state": execute_restore_state,
    "press_key": execute_press_key,
    "screenshot": execute_screenshot,
    "back": execute_back,
    "fill_form": execute_fill_form,
    "upload": execute_upload,
    "drag": execute_drag,
    "evaluate": execute_evaluate,
    "scroll": execute_scroll,
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
