"""Smart element finding with modal-scoping and suffix stripping.

Provides flexible element location using natural language descriptions
like "Password input field" → tries "Password input", "Password" etc.

Also supports direct CSS selectors like "#my_id", ".my_class", "[data-attr]".

Modal scoping: When a dialog/modal is visible, elements inside it are searched
first. This prevents matching elements behind the overlay (e.g. sidebar buttons
with similar text). Falls back to full-page search if not found in modal.
"""

import re
from typing import Union

from playwright.async_api import Page, Locator

# Search scope: either the full page or a locator scoped to a modal/section.
# Both Page and Locator support get_by_role, get_by_text, get_by_label, etc.
Scope = Union[Page, Locator]

# Common element type suffixes that users add to descriptions
ELEMENT_TYPE_SUFFIXES = [
    " link", " button", " btn", " input", " field", " text",
    " image", " img", " icon", " checkbox", " radio", " dropdown",
    " menu", " tab", " option", " label", " heading", " title",
]

# Patterns that indicate a CSS selector rather than natural language
CSS_SELECTOR_PATTERNS = [
    r"^#[\w-]+",           # ID selector: #my_id
    r"^\.[\w-]+",          # Class selector: .my_class
    r"^\[[\w-]+=",         # Attribute selector: [data-test=value]
    r"^\[[\w-]+\]",        # Attribute presence: [data-test]
    r"^[\w-]+\[",          # Tag with attribute: div[class=...]
    r"^[\w-]+#",           # Tag with ID: div#my_id
    r"^[\w-]+\.",          # Tag with class: div.my_class
]


def is_css_selector(target: str) -> bool:
    """Check if target looks like a CSS selector.

    Args:
        target: The target string to check

    Returns:
        True if target appears to be a CSS selector
    """
    if not target:
        return False

    # Natural language descriptions always contain spaces or commas ("e.g., Camry",
    # "Login button"). Real CSS selectors we care about (#id, .class, [attr]) never do.
    if " " in target or "," in target:
        return False

    for pattern in CSS_SELECTOR_PATTERNS:
        if re.match(pattern, target):
            return True

    return False


async def _get_modal_scope(page: Page) -> Locator | None:
    """Return the topmost visible modal dialog, if any.

    Radix UI dialogs render in a portal at the end of <body> with
    role="dialog" and data-state="open". When a modal is open, elements
    inside it should be searched first to avoid matching page elements
    behind the overlay (e.g. "Test" matching a sidebar link instead of
    the "Test" folder button inside the Move to Folder dialog).
    """
    try:
        dialog = page.locator("[role='dialog']:visible, [role='alertdialog']:visible")
        count = await dialog.count()
        if count > 0:
            # Last visible dialog is the topmost (stacked modals)
            return dialog.nth(count - 1)
    except Exception:
        pass
    return None


async def _search_scopes(page: Page) -> list[Scope]:
    """Return search scopes in priority order: modal first, then full page."""
    scopes: list[Scope] = []
    modal = await _get_modal_scope(page)
    if modal:
        scopes.append(modal)
    scopes.append(page)
    return scopes


async def find_by_selector(page: Page, selector: str) -> Locator | None:
    """Find element using CSS selector.

    Args:
        page: Playwright Page instance
        selector: CSS selector string

    Returns:
        Locator if found, None otherwise
    """
    for scope in await _search_scopes(page):
        try:
            locator = scope.locator(selector)
            if await locator.count() > 0:
                return locator.first
        except Exception:
            pass

    return None


def get_target_variations(target: str) -> list[str]:
    """Generate variations by recursively stripping suffixes.

    Examples:
        "Password input field" → ["Password input field", "Password input", "Password"]
        "Submit button" → ["Submit button", "Submit"]
        "credentials link" → ["credentials link", "credentials"]

    Args:
        target: Original target description

    Returns:
        List of variations from most specific to least
    """
    if not target:
        return []

    variations = [target]
    current = target

    while True:
        found = False
        current_lower = current.lower()

        for suffix in ELEMENT_TYPE_SUFFIXES:
            if current_lower.endswith(suffix):
                stripped = current[: len(current) - len(suffix)].strip()
                if stripped and stripped not in variations:
                    variations.append(stripped)
                    current = stripped
                    found = True
                    break

        if not found:
            break

    return variations


async def _find_element_in(scope: Scope, target: str) -> Locator | None:
    """Core element-finding logic within a given scope (Page or Locator).

    Uses exact-first matching: tries exact name match before substring.
    This prevents "Test" from matching "Smoke Tests" or "Test Data".
    """
    for variation in get_target_variations(target):
        exact = re.compile(r"^" + re.escape(variation) + r"$", re.IGNORECASE)
        fuzzy = re.compile(re.escape(variation), re.IGNORECASE)

        for pattern in [exact, fuzzy]:
            # Try role-based locators (most semantic)
            for role in ["button", "link", "textbox", "checkbox", "combobox", "menuitem"]:
                try:
                    locator = scope.get_by_role(role, name=pattern)
                    if await locator.count() > 0:
                        return locator.first
                except Exception:
                    continue

            # Try label (for form inputs)
            try:
                locator = scope.get_by_label(pattern)
                if await locator.count() > 0:
                    return locator.first
            except Exception:
                pass

            # Try placeholder (for inputs)
            try:
                locator = scope.get_by_placeholder(pattern)
                if await locator.count() > 0:
                    return locator.first
            except Exception:
                pass

            # Try text (for any visible text)
            try:
                locator = scope.get_by_text(pattern)
                if await locator.count() > 0:
                    return locator.first
            except Exception:
                pass

        # Try test-id patterns (always substring — IDs are unique enough)
        try:
            locator = scope.locator(f'[data-testid*="{variation}" i]')
            if await locator.count() > 0:
                return locator.first
        except Exception:
            pass

    return None


async def find_element(page: Page, target: str) -> Locator | None:
    """Find element with modal scoping and suffix stripping.

    When a dialog is visible, searches inside it first before falling
    back to the full page. This prevents matching elements behind
    the modal overlay.

    Args:
        page: Playwright Page instance
        target: Element description or CSS selector

    Returns:
        Locator if found, None otherwise
    """
    if not target:
        return None

    if is_css_selector(target):
        return await find_by_selector(page, target)

    for scope in await _search_scopes(page):
        result = await _find_element_in(scope, target)
        if result:
            return result

    return None


async def _find_input_in(scope: Scope, target: str) -> Locator | None:
    """Core input-finding logic within a given scope."""
    for variation in get_target_variations(target):
        exact = re.compile(r"^" + re.escape(variation) + r"$", re.IGNORECASE)
        fuzzy = re.compile(re.escape(variation), re.IGNORECASE)

        for pattern in [exact, fuzzy]:
            # Try textbox role first (most semantic for inputs)
            try:
                locator = scope.get_by_role("textbox", name=pattern)
                if await locator.count() > 0:
                    return locator.first
            except Exception:
                pass

            # Try label
            try:
                locator = scope.get_by_label(pattern)
                if await locator.count() > 0:
                    return locator.first
            except Exception:
                pass

            # Try placeholder
            try:
                locator = scope.get_by_placeholder(pattern)
                if await locator.count() > 0:
                    return locator.first
            except Exception:
                pass

        # Try input/textarea with name attribute (always substring)
        try:
            locator = scope.locator(f'input[name*="{variation}" i], textarea[name*="{variation}" i]')
            if await locator.count() > 0:
                return locator.first
        except Exception:
            pass

        # Try input/textarea with id attribute (always substring)
        try:
            locator = scope.locator(f'input[id*="{variation}" i], textarea[id*="{variation}" i]')
            if await locator.count() > 0:
                return locator.first
        except Exception:
            pass

    return None


async def find_input_element(page: Page, target: str) -> Locator | None:
    """Find an input element with modal scoping.

    Prioritizes input-specific locators over general text matching.

    Args:
        page: Playwright Page instance
        target: Input description or CSS selector

    Returns:
        Locator if found, None otherwise
    """
    if not target:
        return None

    if is_css_selector(target):
        return await find_by_selector(page, target)

    for scope in await _search_scopes(page):
        result = await _find_input_in(scope, target)
        if result:
            return result

    return None


async def find_by_aria_path(page: Page, aria_path: str) -> Locator | None:
    """Resolve an aria contextual path to a Playwright locator.

    Aria paths are recorded as: "role[name='Name'] > role[name='Name'] > ..."
    Each segment becomes a chained Playwright role locator.

    Tries modal scope first if a dialog is visible.

    Args:
        page: Playwright Page instance
        aria_path: Recorded path like "listitem[name='TC #47'] > button[name='Draft']"

    Returns:
        Locator if exactly one match found, None otherwise
    """
    if not aria_path:
        return None

    segments = [s.strip() for s in aria_path.split(">") if s.strip()]
    if not segments:
        return None

    for scope in await _search_scopes(page):
        try:
            locator = None
            for segment in segments:
                # Parse "role[name='value']" or just "role"
                match = re.match(r"^(\w+)(?:\[name='(.+?)'\])?$", segment)
                if not match:
                    break
                role = match.group(1)
                name = match.group(2)

                kwargs = {}
                if name:
                    kwargs["name"] = name

                if locator is None:
                    locator = scope.get_by_role(role, **kwargs)
                else:
                    locator = locator.get_by_role(role, **kwargs)

            if locator and await locator.count() == 1:
                return locator.first
        except Exception:
            continue

    return None


async def _find_clickable_in(scope: Scope, target: str) -> Locator | None:
    """Core clickable-finding logic within a given scope.

    Uses exact-first matching: tries exact name match before substring.
    This prevents "Test" from matching "Smoke Tests" or "Test Data".
    """
    for variation in get_target_variations(target):
        exact = re.compile(r"^" + re.escape(variation) + r"$", re.IGNORECASE)
        fuzzy = re.compile(re.escape(variation), re.IGNORECASE)

        for pattern in [exact, fuzzy]:
            # Try button role
            try:
                locator = scope.get_by_role("button", name=pattern)
                if await locator.count() > 0:
                    return locator.first
            except Exception:
                pass

            # Try link role
            try:
                locator = scope.get_by_role("link", name=pattern)
                if await locator.count() > 0:
                    return locator.first
            except Exception:
                pass

            # Try menuitem role
            try:
                locator = scope.get_by_role("menuitem", name=pattern)
                if await locator.count() > 0:
                    return locator.first
            except Exception:
                pass

            # Fallback to text (for <span> styled as buttons etc.)
            try:
                locator = scope.get_by_text(pattern)
                if await locator.count() > 0:
                    return locator.first
            except Exception:
                pass

    return None


async def find_clickable_element(page: Page, target: str) -> Locator | None:
    """Find a clickable element with modal scoping.

    Prioritizes button/link roles over general text matching.
    When a dialog is visible, searches inside it first.

    Args:
        page: Playwright Page instance
        target: Element description or CSS selector

    Returns:
        Locator if found, None otherwise
    """
    if not target:
        return None

    if is_css_selector(target):
        return await find_by_selector(page, target)

    for scope in await _search_scopes(page):
        result = await _find_clickable_in(scope, target)
        if result:
            return result

    return None
