"""Smart element finding with suffix stripping.

Provides flexible element location using natural language descriptions
like "Password input field" → tries "Password input", "Password" etc.

Also supports direct CSS selectors like "#my_id", ".my_class", "[data-attr]".
"""

import re
from playwright.async_api import Page, Locator

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

    for pattern in CSS_SELECTOR_PATTERNS:
        if re.match(pattern, target):
            return True

    return False


async def find_by_selector(page: Page, selector: str) -> Locator | None:
    """Find element using CSS selector.

    Args:
        page: Playwright Page instance
        selector: CSS selector string

    Returns:
        Locator if found, None otherwise
    """
    try:
        locator = page.locator(selector)
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


async def find_element(page: Page, target: str) -> Locator | None:
    """Two-tier element finding strategy.

    Tier 0: If target is a CSS selector (#id, .class, etc.), use direct locator
    Tier 1: Try standard Playwright locators with variations
    Tier 2: Fallback to flexible text/role matching

    Args:
        page: Playwright Page instance
        target: Element description (e.g., "Submit button", "Username field")
                or CSS selector (e.g., "#my_link", ".my_button")

    Returns:
        Locator if found, None otherwise
    """
    if not target:
        return None

    # Check if target is a CSS selector
    if is_css_selector(target):
        return await find_by_selector(page, target)

    for variation in get_target_variations(target):
        # Create case-insensitive regex pattern
        pattern = re.compile(re.escape(variation), re.IGNORECASE)

        # Try role-based locators (most semantic)
        for role in ["button", "link", "textbox", "checkbox", "combobox", "menuitem"]:
            try:
                locator = page.get_by_role(role, name=pattern)
                if await locator.count() > 0:
                    return locator.first
            except Exception:
                continue

        # Try label (for form inputs)
        try:
            locator = page.get_by_label(pattern)
            if await locator.count() > 0:
                return locator.first
        except Exception:
            pass

        # Try placeholder (for inputs)
        try:
            locator = page.get_by_placeholder(pattern)
            if await locator.count() > 0:
                return locator.first
        except Exception:
            pass

        # Try text (for any visible text)
        try:
            locator = page.get_by_text(pattern)
            if await locator.count() > 0:
                return locator.first
        except Exception:
            pass

        # Try test-id patterns
        try:
            locator = page.locator(f'[data-testid*="{variation}" i]')
            if await locator.count() > 0:
                return locator.first
        except Exception:
            pass

    return None


async def find_input_element(page: Page, target: str) -> Locator | None:
    """Find an input element specifically.

    Prioritizes input-specific locators over general text matching.

    Args:
        page: Playwright Page instance
        target: Input description (e.g., "Username", "Password field")
                or CSS selector (e.g., "#username", ".email-input")

    Returns:
        Locator if found, None otherwise
    """
    if not target:
        return None

    # Check if target is a CSS selector
    if is_css_selector(target):
        return await find_by_selector(page, target)

    for variation in get_target_variations(target):
        pattern = re.compile(re.escape(variation), re.IGNORECASE)

        # Try textbox role first (most semantic for inputs)
        try:
            locator = page.get_by_role("textbox", name=pattern)
            if await locator.count() > 0:
                return locator.first
        except Exception:
            pass

        # Try label
        try:
            locator = page.get_by_label(pattern)
            if await locator.count() > 0:
                return locator.first
        except Exception:
            pass

        # Try placeholder
        try:
            locator = page.get_by_placeholder(pattern)
            if await locator.count() > 0:
                return locator.first
        except Exception:
            pass

        # Try input/textarea with name attribute
        try:
            locator = page.locator(f'input[name*="{variation}" i], textarea[name*="{variation}" i]')
            if await locator.count() > 0:
                return locator.first
        except Exception:
            pass

        # Try input/textarea with id attribute
        try:
            locator = page.locator(f'input[id*="{variation}" i], textarea[id*="{variation}" i]')
            if await locator.count() > 0:
                return locator.first
        except Exception:
            pass

    return None


async def find_clickable_element(page: Page, target: str) -> Locator | None:
    """Find a clickable element specifically.

    Prioritizes button/link roles over general text matching.

    Args:
        page: Playwright Page instance
        target: Element description (e.g., "Submit", "Login button")
                or CSS selector (e.g., "#submit-btn", ".login-link")

    Returns:
        Locator if found, None otherwise
    """
    if not target:
        return None

    # Check if target is a CSS selector
    if is_css_selector(target):
        return await find_by_selector(page, target)

    for variation in get_target_variations(target):
        pattern = re.compile(re.escape(variation), re.IGNORECASE)

        # Try button role
        try:
            locator = page.get_by_role("button", name=pattern)
            if await locator.count() > 0:
                return locator.first
        except Exception:
            pass

        # Try link role
        try:
            locator = page.get_by_role("link", name=pattern)
            if await locator.count() > 0:
                return locator.first
        except Exception:
            pass

        # Try menuitem role
        try:
            locator = page.get_by_role("menuitem", name=pattern)
            if await locator.count() > 0:
                return locator.first
        except Exception:
            pass

        # Fallback to text (for <span> styled as buttons etc.)
        try:
            locator = page.get_by_text(pattern)
            if await locator.count() > 0:
                return locator.first
        except Exception:
            pass

    return None
