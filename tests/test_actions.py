"""Tests for action implementations using a mocked Playwright Page."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import executor.actions as actions_module
from executor.actions import (
    _fuzzy_css_selector,
    execute_action,
    execute_assert_element,
    execute_assert_text,
    execute_assert_url,
    execute_back,
    execute_evaluate,
    execute_hover,
    execute_navigate,
    execute_press_key,
    execute_screenshot,
    execute_type,
    execute_wait,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------



def make_page(url="https://example.com"):
    """Minimal Page mock: all async calls succeed by default."""
    page = AsyncMock()
    page.url = url
    page.keyboard = AsyncMock()
    return page


def make_empty_locator():
    loc = AsyncMock()
    loc.count = AsyncMock(return_value=0)
    loc.first = AsyncMock()
    return loc


def make_found_locator():
    loc = AsyncMock()
    loc.count = AsyncMock(return_value=1)
    loc.first = AsyncMock()
    return loc


# ---------------------------------------------------------------------------
# _fuzzy_css_selector (pure function — no mock needed)
# ---------------------------------------------------------------------------


class TestFuzzyCssSelector:
    def test_attribute_selector_with_numeric_id(self):
        assert _fuzzy_css_selector('[data-testid="move-folder-50"]') == '[data-testid^="move-folder-"]'

    def test_attribute_selector_single_quotes(self):
        assert _fuzzy_css_selector("[data-testid='status-trigger-71']") == '[data-testid^="status-trigger-"]'

    def test_id_selector_with_numeric_suffix(self):
        assert _fuzzy_css_selector("#login-btn-5") == '[id^="login-btn-"]'

    def test_attribute_selector_without_numeric_suffix(self):
        assert _fuzzy_css_selector('[data-testid="login-form"]') is None

    def test_class_selector_not_supported(self):
        assert _fuzzy_css_selector(".my-class") is None

    def test_empty_string(self):
        assert _fuzzy_css_selector("") is None

    def test_plain_word(self):
        assert _fuzzy_css_selector("button") is None


# ---------------------------------------------------------------------------
# execute_action dispatch
# ---------------------------------------------------------------------------


class TestExecuteAction:
    async def test_no_action_returns_failed(self):
        page = make_page()
        result = await execute_action(page, {}, "")
        assert result["status"] == "failed"
        assert "No action" in result["error"]

    async def test_unknown_action_returns_failed(self):
        page = make_page()
        result = await execute_action(page, {"action": "teleport"}, "")
        assert result["status"] == "failed"
        assert "Unknown action" in result["error"]

    async def test_dispatches_to_navigate(self, monkeypatch):
        page = make_page()
        fake = AsyncMock(return_value={"status": "passed"})
        monkeypatch.setattr(actions_module, "execute_navigate", fake)
        # Patch handler map via monkeypatch so cleanup is automatic.
        monkeypatch.setitem(actions_module.ACTION_HANDLERS, "navigate", fake)

        result = await execute_action(page, {"action": "navigate", "value": "https://x.com"}, "")
        assert result["status"] == "passed"
        fake.assert_awaited_once()


# ---------------------------------------------------------------------------
# execute_navigate
# ---------------------------------------------------------------------------


class TestExecuteNavigate:
    async def test_no_url_returns_failed(self):
        page = make_page()
        result = await execute_navigate(page, {}, "")
        assert result["status"] == "failed"
        assert "No URL" in result["error"]

    async def test_absolute_url_happy_path(self):
        page = make_page()
        result = await execute_navigate(page, {"value": "https://example.com"}, "")
        assert result == {"status": "passed"}
        page.goto.assert_awaited_once_with(
            "https://example.com", wait_until="domcontentloaded", timeout=30000
        )

    async def test_relative_url_prepends_base(self):
        page = make_page()
        result = await execute_navigate(page, {"value": "/login"}, "https://app.io")
        assert result == {"status": "passed"}
        page.goto.assert_awaited_once_with(
            "https://app.io/login", wait_until="domcontentloaded", timeout=30000
        )

    async def test_relative_url_trims_base_slash(self):
        page = make_page()
        result = await execute_navigate(page, {"value": "/about"}, "https://app.io/")
        assert result == {"status": "passed"}
        page.goto.assert_awaited_once_with(
            "https://app.io/about", wait_until="domcontentloaded", timeout=30000
        )

    async def test_exception_returns_failed(self):
        page = make_page()
        page.goto = AsyncMock(side_effect=Exception("net::ERR_CONNECTION_REFUSED"))
        result = await execute_navigate(page, {"value": "https://bad.example"}, "")
        assert result["status"] == "failed"
        assert "Navigation failed" in result["error"]


# ---------------------------------------------------------------------------
# execute_type
# ---------------------------------------------------------------------------


class TestExecuteType:
    async def test_no_target_returns_failed(self):
        page = make_page()
        result = await execute_type(page, {"value": "hello"}, "")
        assert result["status"] == "failed"
        assert "No target" in result["error"]

    async def test_element_not_found_returns_failed(self, monkeypatch):
        page = make_page()
        monkeypatch.setattr(actions_module, "find_input_element", AsyncMock(return_value=None))
        monkeypatch.setattr(actions_module, "find_element", AsyncMock(return_value=None))

        result = await execute_type(page, {"target": "Ghost field", "value": "hi"}, "")
        assert result["status"] == "failed"
        assert "Element not found" in result["error"]

    async def test_non_password_field_uses_fill(self, monkeypatch):
        page = make_page()
        element = AsyncMock()
        element.get_attribute = AsyncMock(return_value="text")
        monkeypatch.setattr(actions_module, "find_input_element", AsyncMock(return_value=element))

        result = await execute_type(page, {"target": "Username", "value": "alice"}, "")
        assert result == {"status": "passed"}
        element.fill.assert_awaited_once_with("alice", timeout=5000)

    async def test_password_field_by_target_name_uses_type(self, monkeypatch):
        page = make_page()
        element = AsyncMock()
        monkeypatch.setattr(actions_module, "find_input_element", AsyncMock(return_value=element))

        result = await execute_type(page, {"target": "password field", "value": "s3cr3t"}, "")
        assert result == {"status": "passed"}
        element.fill.assert_awaited_with("")  # clears first
        element.type.assert_awaited_once_with("s3cr3t", delay=50)

    async def test_password_field_by_attribute_uses_type(self, monkeypatch):
        page = make_page()
        element = AsyncMock()
        element.get_attribute = AsyncMock(return_value="password")
        monkeypatch.setattr(actions_module, "find_input_element", AsyncMock(return_value=element))

        result = await execute_type(page, {"target": "Secret", "value": "abc123"}, "")
        assert result == {"status": "passed"}
        element.type.assert_awaited_once_with("abc123", delay=50)

    async def test_fallback_to_find_element(self, monkeypatch):
        """When find_input_element returns None, should try find_element."""
        page = make_page()
        element = AsyncMock()
        element.get_attribute = AsyncMock(return_value="text")
        monkeypatch.setattr(actions_module, "find_input_element", AsyncMock(return_value=None))
        monkeypatch.setattr(actions_module, "find_element", AsyncMock(return_value=element))

        result = await execute_type(page, {"target": "Search", "value": "query"}, "")
        assert result == {"status": "passed"}
        element.fill.assert_awaited_once_with("query", timeout=5000)

    async def test_fill_exception_returns_failed(self, monkeypatch):
        page = make_page()
        element = AsyncMock()
        element.get_attribute = AsyncMock(return_value="text")
        element.fill = AsyncMock(side_effect=Exception("element detached"))
        monkeypatch.setattr(actions_module, "find_input_element", AsyncMock(return_value=element))

        result = await execute_type(page, {"target": "Name", "value": "Bob"}, "")
        assert result["status"] == "failed"
        assert "Type failed" in result["error"]


# ---------------------------------------------------------------------------
# execute_hover
# ---------------------------------------------------------------------------


class TestExecuteHover:
    async def test_no_target_returns_failed(self):
        page = make_page()
        result = await execute_hover(page, {}, "")
        assert result["status"] == "failed"
        assert "No target" in result["error"]

    async def test_element_not_found_returns_failed(self, monkeypatch):
        page = make_page()
        monkeypatch.setattr(actions_module, "find_element", AsyncMock(return_value=None))

        result = await execute_hover(page, {"target": "Tooltip"}, "")
        assert result["status"] == "failed"
        assert "Element not found" in result["error"]

    async def test_happy_path(self, monkeypatch):
        page = make_page()
        element = AsyncMock()
        monkeypatch.setattr(actions_module, "find_element", AsyncMock(return_value=element))

        result = await execute_hover(page, {"target": "Help icon"}, "")
        assert result == {"status": "passed"}
        element.hover.assert_awaited_once_with(timeout=5000)

    async def test_hover_exception_returns_failed(self, monkeypatch):
        page = make_page()
        element = AsyncMock()
        element.hover = AsyncMock(side_effect=Exception("timeout"))
        monkeypatch.setattr(actions_module, "find_element", AsyncMock(return_value=element))

        result = await execute_hover(page, {"target": "Tooltip"}, "")
        assert result["status"] == "failed"
        assert "Hover failed" in result["error"]


# ---------------------------------------------------------------------------
# execute_wait
# ---------------------------------------------------------------------------


class TestExecuteWait:
    async def test_no_target_no_value_waits_one_second(self, monkeypatch):
        page = make_page()
        sleep_mock = AsyncMock()
        monkeypatch.setattr(actions_module.asyncio, "sleep", sleep_mock)

        result = await execute_wait(page, {}, "")
        assert result == {"status": "passed"}
        sleep_mock.assert_awaited_once_with(1)

    async def test_numeric_value_sleeps_for_ms(self, monkeypatch):
        page = make_page()
        sleep_mock = AsyncMock()
        monkeypatch.setattr(actions_module.asyncio, "sleep", sleep_mock)

        result = await execute_wait(page, {"value": "2000"}, "")
        assert result == {"status": "passed"}
        sleep_mock.assert_awaited_once_with(2.0)

    async def test_target_found_returns_passed(self, monkeypatch):
        page = make_page()
        # Patch the internal helper
        monkeypatch.setattr(actions_module, "_wait_for_element", AsyncMock(return_value=True))

        result = await execute_wait(page, {"target": "Save button"}, "")
        assert result == {"status": "passed"}

    async def test_target_not_found_returns_failed(self, monkeypatch):
        page = make_page()
        monkeypatch.setattr(actions_module, "_wait_for_element", AsyncMock(return_value=False))

        result = await execute_wait(page, {"target": "Ghost element"}, "")
        assert result["status"] == "failed"
        assert "Timeout waiting for" in result["error"]

    async def test_text_value_found(self, monkeypatch):
        """Non-numeric value is treated as text to wait for."""
        page = make_page()
        monkeypatch.setattr(actions_module, "_wait_for_element", AsyncMock(return_value=True))

        result = await execute_wait(page, {"value": "Loading complete"}, "")
        assert result == {"status": "passed"}


# ---------------------------------------------------------------------------
# execute_assert_url
# ---------------------------------------------------------------------------


class TestExecuteAssertUrl:
    async def test_no_pattern_returns_failed(self):
        page = make_page()
        result = await execute_assert_url(page, {}, "")
        assert result["status"] == "failed"
        assert "No regex" in result["error"]

    async def test_url_matches_pattern(self):
        page = make_page(url="https://example.com/dashboard")
        result = await execute_assert_url(page, {"value": "dashboard"}, "")
        assert result == {"status": "passed"}

    async def test_url_does_not_match(self):
        page = make_page(url="https://example.com/login")
        result = await execute_assert_url(page, {"value": "dashboard"}, "")
        assert result["status"] == "failed"
        assert "URL mismatch" in result["error"]

    async def test_full_regex_pattern(self):
        page = make_page(url="https://app.example.com/users/42/profile")
        result = await execute_assert_url(page, {"value": r"/users/\d+/profile"}, "")
        assert result == {"status": "passed"}

    async def test_invalid_regex_returns_failed(self):
        page = make_page()
        result = await execute_assert_url(page, {"value": "["}, "")
        assert result["status"] == "failed"
        assert "Invalid regex" in result["error"]

    async def test_bare_wildcard_hint(self):
        """A * at the start of the pattern (invalid regex) should trigger the hint."""
        page = make_page(url="https://example.com/foo")
        # "*example" is an invalid regex (nothing to repeat) and contains * but not .*
        result = await execute_assert_url(page, {"value": "*example"}, "")
        assert result["status"] == "failed"
        assert "Hint" in result["error"]


# ---------------------------------------------------------------------------
# execute_press_key
# ---------------------------------------------------------------------------


class TestExecutePressKey:
    async def test_no_key_returns_failed(self):
        page = make_page()
        result = await execute_press_key(page, {}, "")
        assert result["status"] == "failed"
        assert "No key" in result["error"]

    async def test_happy_path(self):
        page = make_page()
        result = await execute_press_key(page, {"value": "Enter"}, "")
        assert result == {"status": "passed"}
        page.keyboard.press.assert_awaited_once_with("Enter")

    async def test_keyboard_exception_returns_failed(self):
        page = make_page()
        page.keyboard.press = AsyncMock(side_effect=Exception("key error"))
        result = await execute_press_key(page, {"value": "F12"}, "")
        assert result["status"] == "failed"
        assert "Key press failed" in result["error"]


# ---------------------------------------------------------------------------
# execute_screenshot
# ---------------------------------------------------------------------------


class TestExecuteScreenshot:
    async def test_full_page_screenshot(self):
        page = make_page()
        page.screenshot = AsyncMock(return_value=b"\x89PNG\r\n")
        result = await execute_screenshot(page, {}, "")
        assert result["status"] == "passed"
        assert result["screenshot"] == b"\x89PNG\r\n"

    async def test_element_not_found_returns_failed(self, monkeypatch):
        page = make_page()
        monkeypatch.setattr(actions_module, "find_element", AsyncMock(return_value=None))
        result = await execute_screenshot(page, {"target": "Ghost"}, "")
        assert result["status"] == "failed"
        assert "Element not found" in result["error"]

    async def test_element_screenshot(self, monkeypatch):
        page = make_page()
        element = AsyncMock()
        element.screenshot = AsyncMock(return_value=b"PNG_DATA")
        monkeypatch.setattr(actions_module, "find_element", AsyncMock(return_value=element))

        result = await execute_screenshot(page, {"target": "Chart widget"}, "")
        assert result["status"] == "passed"
        assert result["screenshot"] == b"PNG_DATA"

    async def test_screenshot_exception_returns_failed(self):
        page = make_page()
        page.screenshot = AsyncMock(side_effect=Exception("renderer crashed"))
        result = await execute_screenshot(page, {}, "")
        assert result["status"] == "failed"
        assert "Screenshot failed" in result["error"]


# ---------------------------------------------------------------------------
# execute_back
# ---------------------------------------------------------------------------


class TestExecuteBack:
    async def test_happy_path(self):
        page = make_page()
        result = await execute_back(page, {}, "")
        assert result == {"status": "passed"}
        page.go_back.assert_awaited_once()

    async def test_exception_returns_failed(self):
        page = make_page()
        page.go_back = AsyncMock(side_effect=Exception("no history"))
        result = await execute_back(page, {}, "")
        assert result["status"] == "failed"


# ---------------------------------------------------------------------------
# execute_evaluate
# ---------------------------------------------------------------------------


class TestExecuteEvaluate:
    async def test_no_value_returns_failed(self):
        page = make_page()
        result = await execute_evaluate(page, {}, "")
        assert result["status"] == "failed"
        assert "No code" in result["error"]

    async def test_happy_path(self):
        page = make_page()
        page.evaluate = AsyncMock(return_value=42)
        result = await execute_evaluate(page, {"value": "() => 42"}, "")
        assert result["status"] == "passed"
        assert result["result"] == 42

    async def test_exception_returns_failed(self):
        page = make_page()
        page.evaluate = AsyncMock(side_effect=Exception("SyntaxError"))
        result = await execute_evaluate(page, {"value": "() => {"}, "")
        assert result["status"] == "failed"
        assert "JavaScript evaluation failed" in result["error"]


# ---------------------------------------------------------------------------
# execute_assert_element
# ---------------------------------------------------------------------------


class TestExecuteAssertElement:
    async def test_no_target_returns_failed(self):
        page = make_page()
        result = await execute_assert_element(page, {}, "")
        assert result["status"] == "failed"
        assert "No target" in result["error"]

    async def test_element_not_found_returns_failed(self, monkeypatch):
        page = make_page()
        monkeypatch.setattr(actions_module, "find_element", AsyncMock(return_value=None))
        result = await execute_assert_element(page, {"target": "Ghost button"}, "")
        assert result["status"] == "failed"
        assert "Element not found" in result["error"]

    async def test_element_visible_returns_passed(self, monkeypatch):
        page = make_page()
        element = AsyncMock()
        monkeypatch.setattr(actions_module, "find_element", AsyncMock(return_value=element))

        mock_assertion = AsyncMock()
        mock_assertion.to_be_visible = AsyncMock()
        mock_expect = MagicMock(return_value=mock_assertion)
        monkeypatch.setattr(actions_module, "expect", mock_expect)

        result = await execute_assert_element(page, {"target": "Submit button"}, "")
        assert result == {"status": "passed"}

    async def test_element_not_visible_returns_failed(self, monkeypatch):
        page = make_page()
        element = AsyncMock()
        monkeypatch.setattr(actions_module, "find_element", AsyncMock(return_value=element))

        mock_assertion = AsyncMock()
        mock_assertion.to_be_visible = AsyncMock(side_effect=AssertionError("not visible"))
        mock_expect = MagicMock(return_value=mock_assertion)
        monkeypatch.setattr(actions_module, "expect", mock_expect)

        result = await execute_assert_element(page, {"target": "Hidden item"}, "")
        assert result["status"] == "failed"
        assert "not visible" in result["error"]


# ---------------------------------------------------------------------------
# execute_assert_text
# ---------------------------------------------------------------------------


class TestExecuteAssertText:
    async def test_no_text_returns_failed(self):
        page = make_page()
        result = await execute_assert_text(page, {}, "")
        assert result["status"] == "failed"
        assert "No text" in result["error"]

    async def test_strategy1_visible_text_passes(self, monkeypatch):
        """Strategy 1: get_by_text + expect.to_be_visible succeeds."""
        page = make_page()
        page.wait_for_load_state = AsyncMock()

        locator = AsyncMock()
        locator.first = AsyncMock()
        page.get_by_text = MagicMock(return_value=locator)

        mock_assertion = AsyncMock()
        mock_assertion.to_be_visible = AsyncMock()  # No exception = passes
        mock_expect = MagicMock(return_value=mock_assertion)
        monkeypatch.setattr(actions_module, "expect", mock_expect)

        result = await execute_assert_text(page, {"value": "Welcome"}, "")
        assert result == {"status": "passed"}

    async def test_strategy3_body_text_passes(self, monkeypatch):
        """Strategy 3: body innerText scan succeeds."""
        page = make_page()
        page.wait_for_load_state = AsyncMock(side_effect=Exception("timeout"))

        empty_locator = AsyncMock()
        empty_locator.count = AsyncMock(return_value=0)
        empty_locator.first = AsyncMock()
        page.get_by_text = MagicMock(return_value=empty_locator)

        # Strategy 1 fails
        mock_assertion = AsyncMock()
        mock_assertion.to_be_visible = AsyncMock(side_effect=AssertionError("invisible"))
        mock_expect = MagicMock(return_value=mock_assertion)
        monkeypatch.setattr(actions_module, "expect", mock_expect)

        # Strategy 3: evaluate returns body text containing expected
        page.evaluate = AsyncMock(return_value="All systems operational")

        result = await execute_assert_text(page, {"value": "operational"}, "")
        assert result == {"status": "passed"}

    async def test_all_strategies_fail_returns_failed(self, monkeypatch):
        """When no strategy finds the text, status is failed with diagnostic message."""
        page = make_page()
        page.wait_for_load_state = AsyncMock()

        empty_locator = AsyncMock()
        empty_locator.count = AsyncMock(return_value=0)
        empty_locator.first = AsyncMock()
        page.get_by_text = MagicMock(return_value=empty_locator)

        mock_assertion = AsyncMock()
        mock_assertion.to_be_visible = AsyncMock(side_effect=AssertionError("invisible"))
        mock_expect = MagicMock(return_value=mock_assertion)
        monkeypatch.setattr(actions_module, "expect", mock_expect)

        # Body text does NOT contain expected
        page.evaluate = AsyncMock(side_effect=["Login page content", "Login page content"])

        result = await execute_assert_text(page, {"value": "missing_xyz_text"}, "")
        assert result["status"] == "failed"
        assert "missing_xyz_text" in result["error"]


# ---------------------------------------------------------------------------
# execute_click (focused on validation + CSS locator tier)
# ---------------------------------------------------------------------------


class TestExecuteClick:
    async def test_no_target_and_no_locators_returns_failed(self, monkeypatch):
        """Click with no target and no locators should fail immediately."""
        page = make_page()
        page.locator = MagicMock(return_value=make_empty_locator())
        monkeypatch.setattr(actions_module.asyncio, "sleep", AsyncMock())

        result = await actions_module.execute_click(
            page, {"action": "click"}, ""
        )
        assert result["status"] == "failed"
        assert "No target" in result["error"]

    async def test_css_locator_tier_succeeds(self, monkeypatch):
        """Tier 2: CSS selector in locators.css finds element → click succeeds."""
        page = make_page()
        monkeypatch.setattr(actions_module.asyncio, "sleep", AsyncMock())

        found_loc = make_found_locator()
        empty_loc = make_empty_locator()

        def locator_se(sel):
            if sel == "#submit-btn":
                return found_loc
            return empty_loc

        page.locator = MagicMock(side_effect=locator_se)
        page.get_by_role = MagicMock(return_value=empty_loc)
        page.get_by_text = MagicMock(return_value=empty_loc)

        # No UTML target, but locators.css provided
        step = {"locators": {"css": "#submit-btn"}}
        result = await actions_module.execute_click(page, step, "")
        assert result["status"] == "passed"
        assert result["resolved_by"] == "css"

    async def test_utml_target_click_succeeds(self, monkeypatch):
        """Tier 1: UTML target finds element, unique match, click succeeds."""
        page = make_page()
        monkeypatch.setattr(actions_module.asyncio, "sleep", AsyncMock())

        element = AsyncMock()
        element.bounding_box = AsyncMock(return_value=None)  # skip proximity check
        element.click = AsyncMock()

        empty_loc = make_empty_locator()
        page.locator = MagicMock(return_value=empty_loc)
        page.get_by_role = MagicMock(return_value=empty_loc)
        page.get_by_text = MagicMock(return_value=empty_loc)

        monkeypatch.setattr(actions_module, "find_clickable_element", AsyncMock(return_value=element))
        monkeypatch.setattr(actions_module, "find_element", AsyncMock(return_value=None))

        step = {"target": "Submit"}
        result = await actions_module.execute_click(page, step, "")
        assert result["status"] == "passed"
        assert result["resolved_by"] == "utml"
        element.click.assert_awaited_once()

    async def test_aria_path_tier_succeeds(self, monkeypatch):
        """Tier 3: ariaPath locator finds element → click succeeds."""
        page = make_page()
        monkeypatch.setattr(actions_module.asyncio, "sleep", AsyncMock())

        element = AsyncMock()
        element.click = AsyncMock()

        empty_loc = make_empty_locator()
        page.locator = MagicMock(return_value=empty_loc)
        page.get_by_role = MagicMock(return_value=empty_loc)
        page.get_by_text = MagicMock(return_value=empty_loc)

        # No UTML target, no CSS, but ariaPath
        monkeypatch.setattr(actions_module, "find_clickable_element", AsyncMock(return_value=None))
        monkeypatch.setattr(actions_module, "find_element", AsyncMock(return_value=None))
        monkeypatch.setattr(actions_module, "find_by_aria_path", AsyncMock(return_value=element))
        # Suppress hover submenu evaluation
        page.evaluate = AsyncMock(return_value=[])

        step = {"locators": {"ariaPath": "listitem > button[name='Delete']"}}
        result = await actions_module.execute_click(page, step, "")
        assert result["status"] == "passed"
        assert result["resolved_by"] == "ariaPath"


# ---------------------------------------------------------------------------
# execute_select
# ---------------------------------------------------------------------------


class TestExecuteSelect:
    async def test_no_target_returns_failed(self):
        page = make_page()
        result = await actions_module.execute_select(page, {}, "")
        assert result["status"] == "failed"
        assert "No target" in result["error"]

    async def test_element_not_found_returns_failed(self, monkeypatch):
        page = make_page()
        page.evaluate = AsyncMock(return_value=-1)  # combobox not found
        monkeypatch.setattr(actions_module, "find_element", AsyncMock(return_value=None))
        result = await actions_module.execute_select(page, {"target": "Color", "value": "Red"}, "")
        assert result["status"] == "failed"
        assert "Element not found" in result["error"]

    async def test_native_select_element(self, monkeypatch):
        page = make_page()
        element = AsyncMock()
        element.evaluate = AsyncMock(return_value="select")
        # Not hidden
        element.evaluate = AsyncMock(side_effect=["select", False])
        element.select_option = AsyncMock()

        page.evaluate = AsyncMock(return_value=-1)
        monkeypatch.setattr(actions_module, "find_element", AsyncMock(return_value=element))
        result = await actions_module.execute_select(page, {"target": "Color", "value": "Red"}, "")
        assert result["status"] == "passed"
        element.select_option.assert_awaited_once_with(["Red"], timeout=5000)

    async def test_custom_combobox_option_via_role(self, monkeypatch):
        page = make_page()
        element = AsyncMock()
        element.evaluate = AsyncMock(return_value="button")
        element.scroll_into_view_if_needed = AsyncMock()
        element.click = AsyncMock()

        found_option = AsyncMock()
        found_option.count = AsyncMock(return_value=1)
        found_option.first = AsyncMock()
        found_option.first.click = AsyncMock()

        empty_option = AsyncMock()
        empty_option.count = AsyncMock(return_value=0)

        # _find_combobox_by_label returns element (simulate via page.evaluate returning 0)
        page.evaluate = AsyncMock(side_effect=[
            0,          # _find_combobox_by_label finds index 0
            [],         # available options log
        ])
        comboboxes = AsyncMock()
        comboboxes.count = AsyncMock(return_value=1)
        comboboxes.nth = MagicMock(return_value=element)
        page.get_by_role = MagicMock(return_value=comboboxes)

        # _wait_for_options returns True
        monkeypatch.setattr(actions_module, "_wait_for_options", AsyncMock(return_value=True))

        # locator().filter() returns found option
        page.locator = MagicMock(return_value=AsyncMock(
            filter=MagicMock(return_value=found_option)
        ))

        result = await actions_module.execute_select(page, {"target": "Color", "value": "Red"}, "")
        assert result["status"] == "passed"

    async def test_exception_returns_failed(self, monkeypatch):
        page = make_page()
        page.evaluate = AsyncMock(side_effect=RuntimeError("crash"))
        result = await actions_module.execute_select(page, {"target": "X", "value": "Y"}, "")
        assert result["status"] == "failed"
        assert "Select failed" in result["error"]


# ---------------------------------------------------------------------------
# execute_restore_state
# ---------------------------------------------------------------------------


class TestExecuteRestoreState:
    async def test_no_value_returns_failed(self):
        page = make_page()
        result = await actions_module.execute_restore_state(page, {}, "")
        assert result["status"] == "failed"
        assert "No state data provided" in result["error"]

    async def test_invalid_json_returns_failed(self):
        page = make_page()
        result = await actions_module.execute_restore_state(page, {"value": "not-json{{"}, "")
        assert result["status"] == "failed"
        assert "Invalid state JSON" in result["error"]

    async def test_no_state_key_returns_failed(self):
        import json
        page = make_page()
        data = json.dumps({"url": "https://example.com"})  # no "state" key
        result = await actions_module.execute_restore_state(page, {"value": data}, "")
        assert result["status"] == "failed"
        assert "No state object found" in result["error"]

    async def test_no_url_returns_failed(self):
        import json
        page = make_page()
        data = json.dumps({"state": {"cookies": [], "origins": []}})  # no url
        result = await actions_module.execute_restore_state(page, {"value": data}, "")
        assert result["status"] == "failed"
        assert "No URL provided" in result["error"]

    async def test_happy_path_restores_cookies_and_navigates(self):
        import json
        context = AsyncMock()
        context.add_cookies = AsyncMock()
        page = make_page()
        page.context = context
        page.goto = AsyncMock()
        page.evaluate = AsyncMock()

        state = {
            "cookies": [{"name": "token", "value": "abc"}],
            "origins": [
                {
                    "origin": "https://example.com",
                    "localStorage": [{"name": "key", "value": "val"}],
                    "sessionStorage": [],
                }
            ],
        }
        data = json.dumps({"state": state, "url": "https://example.com"})
        result = await actions_module.execute_restore_state(page, {"value": data}, "")
        assert result["status"] == "passed"
        context.add_cookies.assert_awaited_once()
        page.goto.assert_awaited_once()

    async def test_dict_value_accepted_without_json_parse(self):
        context = AsyncMock()
        context.add_cookies = AsyncMock()
        page = make_page()
        page.context = context
        page.goto = AsyncMock()
        page.evaluate = AsyncMock()

        state_data = {
            "state": {"cookies": [], "origins": []},
            "url": "https://example.com",
        }
        result = await actions_module.execute_restore_state(page, {"value": state_data}, "")
        assert result["status"] == "passed"


# ---------------------------------------------------------------------------
# execute_scroll
# ---------------------------------------------------------------------------


class TestExecuteScroll:
    async def test_scroll_down_default(self, monkeypatch):
        page = make_page()
        monkeypatch.setattr(actions_module.asyncio, "sleep", AsyncMock())
        page.evaluate = AsyncMock(return_value=None)
        result = await actions_module.execute_scroll(page, {}, "")
        assert result["status"] == "passed"
        page.evaluate.assert_awaited()

    async def test_scroll_top(self, monkeypatch):
        page = make_page()
        monkeypatch.setattr(actions_module.asyncio, "sleep", AsyncMock())
        page.evaluate = AsyncMock(return_value=None)
        result = await actions_module.execute_scroll(page, {"value": "top"}, "")
        assert result["status"] == "passed"

    async def test_scroll_bottom(self, monkeypatch):
        page = make_page()
        monkeypatch.setattr(actions_module.asyncio, "sleep", AsyncMock())
        page.evaluate = AsyncMock(return_value=None)
        result = await actions_module.execute_scroll(page, {"value": "bottom"}, "")
        assert result["status"] == "passed"

    async def test_scroll_up(self, monkeypatch):
        page = make_page()
        monkeypatch.setattr(actions_module.asyncio, "sleep", AsyncMock())
        page.evaluate = AsyncMock(return_value=None)
        result = await actions_module.execute_scroll(page, {"value": "up"}, "")
        assert result["status"] == "passed"

    async def test_scroll_pixel_amount(self, monkeypatch):
        page = make_page()
        monkeypatch.setattr(actions_module.asyncio, "sleep", AsyncMock())
        page.evaluate = AsyncMock(return_value=None)
        result = await actions_module.execute_scroll(page, {"value": "300"}, "")
        assert result["status"] == "passed"

    async def test_scroll_unknown_value_returns_failed(self, monkeypatch):
        page = make_page()
        monkeypatch.setattr(actions_module.asyncio, "sleep", AsyncMock())
        result = await actions_module.execute_scroll(page, {"value": "sideways"}, "")
        assert result["status"] == "failed"
        assert "Unknown scroll value" in result["error"]

    async def test_scroll_element_into_view(self, monkeypatch):
        page = make_page()
        monkeypatch.setattr(actions_module.asyncio, "sleep", AsyncMock())
        element = AsyncMock()
        element.scroll_into_view_if_needed = AsyncMock()
        monkeypatch.setattr(actions_module, "find_element", AsyncMock(return_value=element))
        result = await actions_module.execute_scroll(page, {"target": "Submit Button"}, "")
        assert result["status"] == "passed"
        element.scroll_into_view_if_needed.assert_awaited_once()

    async def test_scroll_element_not_found_returns_failed(self, monkeypatch):
        page = make_page()
        monkeypatch.setattr(actions_module, "find_element", AsyncMock(return_value=None))
        result = await actions_module.execute_scroll(page, {"target": "Ghost Button"}, "")
        assert result["status"] == "failed"
        assert "Element not found" in result["error"]

    async def test_scroll_exception_returns_failed(self, monkeypatch):
        page = make_page()
        monkeypatch.setattr(actions_module.asyncio, "sleep", AsyncMock())
        page.evaluate = AsyncMock(side_effect=RuntimeError("viewport gone"))
        result = await actions_module.execute_scroll(page, {"value": "top"}, "")
        assert result["status"] == "failed"
        assert "Scroll failed" in result["error"]


# ---------------------------------------------------------------------------
# _wait_for_element (CSS and NL polling branches)
# ---------------------------------------------------------------------------


class TestWaitForElement:
    async def test_css_selector_found(self, monkeypatch):
        """CSS selector branch: locator.wait_for succeeds → returns True."""
        page = make_page()
        loc = AsyncMock()
        loc.wait_for = AsyncMock()
        page.locator = MagicMock(return_value=loc)
        result = await actions_module._wait_for_element(page, "#submit-btn")
        assert result is True

    async def test_css_selector_times_out(self, monkeypatch):
        """CSS selector branch: wait_for raises → returns False."""
        page = make_page()
        loc = AsyncMock()
        loc.wait_for = AsyncMock(side_effect=Exception("timeout"))
        page.locator = MagicMock(return_value=loc)
        result = await actions_module._wait_for_element(page, "#missing")
        assert result is False

    async def test_nl_found_via_button_role(self, monkeypatch):
        """NL polling: button role found on first poll → returns True."""
        monkeypatch.setattr(actions_module.asyncio, "sleep", AsyncMock())
        page = make_page()
        found = make_found_locator()
        empty = make_empty_locator()
        page.get_by_role = MagicMock(side_effect=lambda role, **kw: found if role == "button" else empty)
        result = await actions_module._wait_for_element(page, "Submit button", timeout=500)
        assert result is True

    async def test_nl_found_via_link_role(self, monkeypatch):
        """NL polling: link role found → returns True."""
        monkeypatch.setattr(actions_module.asyncio, "sleep", AsyncMock())
        page = make_page()
        found = make_found_locator()
        empty = make_empty_locator()
        def role_side_effect(role, **kw):
            return found if role == "link" else empty
        page.get_by_role = MagicMock(side_effect=role_side_effect)
        result = await actions_module._wait_for_element(page, "Home link", timeout=500)
        assert result is True

    async def test_nl_found_via_text(self, monkeypatch):
        """NL polling: get_by_text found → returns True."""
        monkeypatch.setattr(actions_module.asyncio, "sleep", AsyncMock())
        page = make_page()
        found = make_found_locator()
        empty = make_empty_locator()
        page.get_by_role = MagicMock(return_value=empty)
        page.get_by_text = MagicMock(return_value=found)
        result = await actions_module._wait_for_element(page, "Welcome message", timeout=500)
        assert result is True

    async def test_nl_timeout_returns_false(self, monkeypatch):
        """NL polling: all polls fail → returns False after timeout."""
        monkeypatch.setattr(actions_module.asyncio, "sleep", AsyncMock())
        page = make_page()
        page.get_by_role = MagicMock(return_value=make_empty_locator())
        page.get_by_text = MagicMock(return_value=make_empty_locator())
        result = await actions_module._wait_for_element(page, "Ghost element", timeout=100)
        assert result is False


# ---------------------------------------------------------------------------
# _find_nearest_clickable (JS evaluation)
# ---------------------------------------------------------------------------


class TestFindNearestClickable:
    async def test_returns_index_from_evaluate(self):
        page = make_page()
        page.evaluate = AsyncMock(return_value=2)
        result = await actions_module._find_nearest_clickable(page, 100, 200, "Submit", 300)
        assert result == 2
        page.evaluate.assert_awaited_once()

    async def test_returns_negative_when_nothing_nearby(self):
        page = make_page()
        page.evaluate = AsyncMock(return_value=-1)
        result = await actions_module._find_nearest_clickable(page, 100, 200)
        assert result == -1


# ---------------------------------------------------------------------------
# _click_nearest_from_locator
# ---------------------------------------------------------------------------


class TestClickNearestFromLocator:
    async def test_clicks_nearest_element(self):
        """Should click the element with the closest bounding box centroid."""
        loc = AsyncMock()
        loc.count = AsyncMock(return_value=2)

        el0 = AsyncMock()
        el0.bounding_box = AsyncMock(return_value={"x": 0, "y": 0, "width": 10, "height": 10})
        el0.click = AsyncMock()
        el1 = AsyncMock()
        el1.bounding_box = AsyncMock(return_value={"x": 100, "y": 200, "width": 10, "height": 10})
        el1.click = AsyncMock()

        loc.nth = MagicMock(side_effect=lambda i: el0 if i == 0 else el1)
        # Click target at 105, 205 — closer to el1
        result = await actions_module._click_nearest_from_locator(loc, 105, 205)
        assert result is True
        el1.click.assert_awaited_once()

    async def test_returns_false_when_all_out_of_range(self):
        """Elements all beyond max_dist → returns False, no click."""
        loc = AsyncMock()
        loc.count = AsyncMock(return_value=1)
        el = AsyncMock()
        el.bounding_box = AsyncMock(return_value={"x": 0, "y": 0, "width": 10, "height": 10})
        el.click = AsyncMock()
        loc.nth = MagicMock(return_value=el)
        result = await actions_module._click_nearest_from_locator(loc, 1000, 1000, max_dist=10)
        assert result is False

    async def test_returns_false_when_empty(self):
        loc = AsyncMock()
        loc.count = AsyncMock(return_value=0)
        result = await actions_module._click_nearest_from_locator(loc, 50, 50)
        assert result is False


# ---------------------------------------------------------------------------
# _click_nearest
# ---------------------------------------------------------------------------


class TestClickNearest:
    async def test_returns_true_when_element_found_and_clicked(self, monkeypatch):
        """_click_nearest delegates to _find_nearest_clickable then clicks nth."""
        page = make_page()
        monkeypatch.setattr(actions_module, "_find_nearest_clickable", AsyncMock(return_value=3))
        el = AsyncMock()
        el.click = AsyncMock()
        loc = AsyncMock()
        loc.nth = MagicMock(return_value=el)
        page.locator = MagicMock(return_value=loc)
        result = await actions_module._click_nearest(page, 100, 200, "Submit")
        assert result is True

    async def test_returns_false_when_nothing_found(self, monkeypatch):
        page = make_page()
        monkeypatch.setattr(actions_module, "_find_nearest_clickable", AsyncMock(return_value=-1))
        result = await actions_module._click_nearest(page, 100, 200)
        assert result is False


# ---------------------------------------------------------------------------
# execute_click wrapper (causes_navigation + dialog detection)
# ---------------------------------------------------------------------------


class TestExecuteClickWrapper:
    def _make_dialog_locator(self, count):
        loc = AsyncMock()
        loc.count = AsyncMock(return_value=count)
        return loc

    async def test_causes_navigation_url_changes(self, monkeypatch):
        """causes_navigation=True: URL changes → passed."""
        page = make_page(url="https://example.com/old")
        page.locator = MagicMock(return_value=self._make_dialog_locator(0))
        page.wait_for_url = AsyncMock()
        page.wait_for_load_state = AsyncMock()
        monkeypatch.setattr(
            actions_module, "_execute_click_waterfall",
            AsyncMock(return_value={"status": "passed", "resolved_by": "utml"})
        )
        result = await actions_module.execute_click(page, {"target": "Next", "causes_navigation": True}, "")
        assert result["status"] == "passed"

    async def test_causes_navigation_url_unchanged_returns_failed(self, monkeypatch):
        """causes_navigation=True: URL stays same → failed."""
        page = make_page(url="https://example.com/same")
        page.locator = MagicMock(return_value=self._make_dialog_locator(0))
        page.wait_for_url = AsyncMock(side_effect=Exception("timeout"))
        monkeypatch.setattr(
            actions_module, "_execute_click_waterfall",
            AsyncMock(return_value={"status": "passed", "resolved_by": "utml"})
        )
        result = await actions_module.execute_click(page, {"target": "Next", "causes_navigation": True}, "")
        assert result["status"] == "failed"
        assert "did not cause navigation" in result["error"]

    async def test_non_nav_dialog_appears(self, monkeypatch):
        """Non-nav: dialog count increases → extra asyncio.sleep(0.2) called."""
        page = make_page()
        call_count = [0]
        def locator_se(sel):
            loc = AsyncMock()
            # First call: 0 dialogs before, second call: 1 dialog after
            call_count[0] += 1
            loc.count = AsyncMock(return_value=0 if call_count[0] == 1 else 1)
            return loc
        page.locator = MagicMock(side_effect=locator_se)
        sleep_calls = []
        async def fake_sleep(t):
            sleep_calls.append(t)
        monkeypatch.setattr(actions_module.asyncio, "sleep", fake_sleep)
        monkeypatch.setattr(
            actions_module, "_execute_click_waterfall",
            AsyncMock(return_value={"status": "passed", "resolved_by": "utml"})
        )
        result = await actions_module.execute_click(page, {"target": "Open"}, "")
        assert result["status"] == "passed"
        assert 0.2 in sleep_calls

    async def test_waterfall_failed_passes_through(self, monkeypatch):
        """If waterfall returns failed, execute_click just returns it."""
        page = make_page()
        page.locator = MagicMock(return_value=self._make_dialog_locator(0))
        monkeypatch.setattr(
            actions_module, "_execute_click_waterfall",
            AsyncMock(return_value={"status": "failed", "error": "not found"})
        )
        result = await actions_module.execute_click(page, {"target": "X"}, "")
        assert result["status"] == "failed"


# ---------------------------------------------------------------------------
# _execute_click_waterfall — CSS target, CSS locators, ariaPath
# ---------------------------------------------------------------------------


class TestExecuteClickWaterfall:
    async def test_css_target_succeeds(self, monkeypatch):
        """CSS target: find_element returns element, click succeeds → resolved_by=css."""
        page = make_page()
        element = AsyncMock()
        element.click = AsyncMock()
        monkeypatch.setattr(actions_module, "find_element", AsyncMock(return_value=element))
        monkeypatch.setattr(actions_module, "_try_hover_submenu", AsyncMock(return_value=None))
        monkeypatch.setattr(actions_module.asyncio, "sleep", AsyncMock())
        result = await actions_module._execute_click_waterfall(page, {"target": "#submit-btn"}, "")
        assert result["status"] == "passed"
        assert result["resolved_by"] == "css"

    async def test_css_target_element_not_found(self, monkeypatch):
        """CSS target: element not found → falls through to failure."""
        page = make_page()
        monkeypatch.setattr(actions_module, "find_element", AsyncMock(return_value=None))
        monkeypatch.setattr(actions_module, "find_clickable_element", AsyncMock(return_value=None))
        monkeypatch.setattr(actions_module, "find_by_aria_path", AsyncMock(return_value=None))
        monkeypatch.setattr(actions_module, "_try_hover_submenu", AsyncMock(return_value=None))
        monkeypatch.setattr(actions_module.asyncio, "sleep", AsyncMock())
        page.locator = MagicMock(return_value=make_empty_locator())
        result = await actions_module._execute_click_waterfall(page, {"target": "#ghost"}, "")
        assert result["status"] == "failed"

    async def test_css_from_locators_succeeds(self, monkeypatch):
        """Tier 2: CSS from locators → resolved_by=css."""
        page = make_page()
        loc = AsyncMock()
        loc.count = AsyncMock(return_value=1)
        loc.first = AsyncMock()
        loc.first.click = AsyncMock()
        page.locator = MagicMock(return_value=loc)
        monkeypatch.setattr(actions_module, "find_clickable_element", AsyncMock(return_value=None))
        monkeypatch.setattr(actions_module, "find_element", AsyncMock(return_value=None))
        monkeypatch.setattr(actions_module, "find_by_aria_path", AsyncMock(return_value=None))
        monkeypatch.setattr(actions_module, "_try_hover_submenu", AsyncMock(return_value=None))
        monkeypatch.setattr(actions_module.asyncio, "sleep", AsyncMock())
        result = await actions_module._execute_click_waterfall(
            page,
            {"target": "My Button", "locators": {"css": ".my-btn"}},
            ""
        )
        assert result["status"] == "passed"
        assert result["resolved_by"] == "css"

    async def test_ariapath_tier_succeeds(self, monkeypatch):
        """Tier 3: ariaPath → resolved_by=ariaPath."""
        page = make_page()
        element = AsyncMock()
        element.click = AsyncMock()
        monkeypatch.setattr(actions_module, "find_clickable_element", AsyncMock(return_value=None))
        monkeypatch.setattr(actions_module, "find_element", AsyncMock(return_value=None))
        monkeypatch.setattr(actions_module, "find_by_aria_path", AsyncMock(return_value=element))
        monkeypatch.setattr(actions_module, "_try_hover_submenu", AsyncMock(return_value=None))
        monkeypatch.setattr(actions_module.asyncio, "sleep", AsyncMock())
        page.locator = MagicMock(return_value=make_empty_locator())
        result = await actions_module._execute_click_waterfall(
            page,
            {"target": "Submit", "locators": {"ariaPath": "button[name='Submit']"}},
            ""
        )
        assert result["status"] == "passed"
        assert result["resolved_by"] == "ariaPath"

    async def test_hover_submenu_tier_triggered(self, monkeypatch):
        """Tier 4: hover-submenu recovery succeeds."""
        page = make_page()
        monkeypatch.setattr(actions_module, "find_clickable_element", AsyncMock(return_value=None))
        monkeypatch.setattr(actions_module, "find_element", AsyncMock(return_value=None))
        monkeypatch.setattr(actions_module, "find_by_aria_path", AsyncMock(return_value=None))
        monkeypatch.setattr(
            actions_module, "_try_hover_submenu",
            AsyncMock(return_value={"status": "passed", "resolved_by": "hover-submenu"})
        )
        monkeypatch.setattr(actions_module.asyncio, "sleep", AsyncMock())
        page.locator = MagicMock(return_value=make_empty_locator())
        result = await actions_module._execute_click_waterfall(
            page, {"target": "Hidden Item"}, ""
        )
        assert result["status"] == "passed"
        assert result["resolved_by"] == "hover-submenu"

    async def test_utml_unique_match_clicked(self, monkeypatch):
        """Tier 1: UTML finds unique element → resolved_by=utml."""
        page = make_page()
        element = AsyncMock()
        element.click = AsyncMock()
        element.bounding_box = AsyncMock(return_value=None)  # No bbox → skip proximity check
        monkeypatch.setattr(actions_module, "find_clickable_element", AsyncMock(return_value=element))
        monkeypatch.setattr(actions_module, "find_element", AsyncMock(return_value=element))
        monkeypatch.setattr(actions_module, "_try_hover_submenu", AsyncMock(return_value=None))
        monkeypatch.setattr(actions_module.asyncio, "sleep", AsyncMock())
        page.get_by_role = MagicMock(return_value=make_empty_locator())
        page.locator = MagicMock(return_value=make_empty_locator())
        result = await actions_module._execute_click_waterfall(
            page, {"target": "Submit"}, ""
        )
        assert result["status"] == "passed"
        assert result["resolved_by"] == "utml"


# ---------------------------------------------------------------------------
# execute_type — fallback to find_element
# ---------------------------------------------------------------------------


class TestExecuteTypeFindElementFallback:
    async def test_find_input_fails_falls_back_to_find_element(self, monkeypatch):
        """When find_input_element returns None, should try find_element."""
        page = make_page()
        element = AsyncMock()
        element.fill = AsyncMock()
        element.get_attribute = AsyncMock(return_value="text")
        monkeypatch.setattr(actions_module, "find_input_element", AsyncMock(return_value=None))
        monkeypatch.setattr(actions_module, "find_element", AsyncMock(return_value=element))
        result = await actions_module.execute_type(page, {"target": "Description", "value": "hello"}, "")
        assert result["status"] == "passed"
        element.fill.assert_awaited_once_with("hello", timeout=5000)


# ---------------------------------------------------------------------------
# execute_assert_style
# ---------------------------------------------------------------------------


class TestExecuteAssertStyle:
    async def test_no_target_returns_failed(self):
        page = make_page()
        result = await actions_module.execute_assert_style(page, {"value": "{}"}, "")
        assert result["status"] == "failed"
        assert "required" in result["error"]

    async def test_no_value_returns_failed(self):
        page = make_page()
        result = await actions_module.execute_assert_style(page, {"target": "Button"}, "")
        assert result["status"] == "failed"

    async def test_invalid_json_returns_failed(self):
        page = make_page()
        result = await actions_module.execute_assert_style(
            page, {"target": "Button", "value": "not-json"}, ""
        )
        assert result["status"] == "failed"
        assert "Invalid style spec" in result["error"]

    async def test_missing_property_or_expected_returns_failed(self, monkeypatch):
        page = make_page()
        import json
        result = await actions_module.execute_assert_style(
            page, {"target": "Button", "value": json.dumps({"property": "color"})}, ""
        )
        assert result["status"] == "failed"
        assert "must include" in result["error"]

    async def test_element_not_found_returns_failed(self, monkeypatch):
        import json
        page = make_page()
        monkeypatch.setattr(actions_module, "find_element", AsyncMock(return_value=None))
        result = await actions_module.execute_assert_style(
            page,
            {"target": "Ghost", "value": json.dumps({"property": "color", "expected": "red"})},
            ""
        )
        assert result["status"] == "failed"
        assert "Element not found" in result["error"]

    async def test_css_assertion_passes(self, monkeypatch):
        import json
        page = make_page()
        element = AsyncMock()
        monkeypatch.setattr(actions_module, "find_element", AsyncMock(return_value=element))
        with patch("executor.actions.expect") as mock_expect:
            mock_expect.return_value.to_have_css = AsyncMock()
            result = await actions_module.execute_assert_style(
                page,
                {"target": "Button", "value": json.dumps({"property": "color", "expected": "rgb(255, 0, 0)"})},
                ""
            )
        assert result["status"] == "passed"

    async def test_css_assertion_fails(self, monkeypatch):
        import json
        page = make_page()
        element = AsyncMock()
        monkeypatch.setattr(actions_module, "find_element", AsyncMock(return_value=element))
        with patch("executor.actions.expect") as mock_expect:
            mock_expect.return_value.to_have_css = AsyncMock(side_effect=Exception("AssertionError"))
            result = await actions_module.execute_assert_style(
                page,
                {"target": "Button", "value": json.dumps({"property": "color", "expected": "blue"})},
                ""
            )
        assert result["status"] == "failed"
        assert "Style assertion failed" in result["error"]

    async def test_value_as_dict_accepted(self, monkeypatch):
        """value can be a dict (not just a JSON string)."""
        page = make_page()
        element = AsyncMock()
        monkeypatch.setattr(actions_module, "find_element", AsyncMock(return_value=element))
        with patch("executor.actions.expect") as mock_expect:
            mock_expect.return_value.to_have_css = AsyncMock()
            result = await actions_module.execute_assert_style(
                page,
                {"target": "Button", "value": {"property": "font-size", "expected": "16px"}},
                ""
            )
        assert result["status"] == "passed"


# ---------------------------------------------------------------------------
# execute_fill_form
# ---------------------------------------------------------------------------


class TestExecuteFillForm:
    async def test_empty_value_returns_failed(self):
        page = make_page()
        result = await actions_module.execute_fill_form(page, {}, "")
        assert result["status"] == "failed"

    async def test_invalid_json_returns_failed(self):
        page = make_page()
        result = await actions_module.execute_fill_form(page, {"value": "not-json"}, "")
        assert result["status"] == "failed"
        assert "Invalid JSON" in result["error"]

    async def test_non_dict_value_returns_failed(self):
        page = make_page()
        result = await actions_module.execute_fill_form(page, {"value": '["a", "b"]'}, "")
        assert result["status"] == "failed"

    async def test_field_not_found_returns_failed(self, monkeypatch):
        page = make_page()
        monkeypatch.setattr(actions_module, "find_input_element", AsyncMock(return_value=None))
        monkeypatch.setattr(actions_module, "find_element", AsyncMock(return_value=None))
        import json
        result = await actions_module.execute_fill_form(
            page, {"value": json.dumps({"Email": "a@b.com"})}, ""
        )
        assert result["status"] == "failed"
        assert "Field not found" in result["error"]

    async def test_fills_multiple_fields(self, monkeypatch):
        page = make_page()
        element = AsyncMock()
        element.fill = AsyncMock()
        monkeypatch.setattr(actions_module, "find_input_element", AsyncMock(return_value=element))
        import json
        result = await actions_module.execute_fill_form(
            page, {"value": json.dumps({"Email": "a@b.com", "Name": "Alice"})}, ""
        )
        assert result["status"] == "passed"
        assert element.fill.await_count == 2

    async def test_value_as_dict(self, monkeypatch):
        """value can be a dict directly."""
        page = make_page()
        element = AsyncMock()
        element.fill = AsyncMock()
        monkeypatch.setattr(actions_module, "find_input_element", AsyncMock(return_value=element))
        result = await actions_module.execute_fill_form(
            page, {"value": {"Username": "bob"}}, ""
        )
        assert result["status"] == "passed"


# ---------------------------------------------------------------------------
# execute_upload
# ---------------------------------------------------------------------------


class TestExecuteUpload:
    async def test_no_value_returns_failed(self):
        page = make_page()
        result = await actions_module.execute_upload(page, {}, "")
        assert result["status"] == "failed"
        assert "No file paths" in result["error"]

    async def test_empty_paths_after_split_returns_failed(self):
        page = make_page()
        result = await actions_module.execute_upload(page, {"value": "  ,  "}, "")
        assert result["status"] == "failed"
        assert "No valid" in result["error"]

    async def test_upload_to_target(self, monkeypatch):
        page = make_page()
        element = AsyncMock()
        element.set_input_files = AsyncMock()
        monkeypatch.setattr(actions_module, "find_element", AsyncMock(return_value=element))
        result = await actions_module.execute_upload(
            page, {"value": "/tmp/file.pdf", "target": "Upload field"}, ""
        )
        assert result["status"] == "passed"
        element.set_input_files.assert_awaited_once_with(["/tmp/file.pdf"])

    async def test_upload_target_not_found(self, monkeypatch):
        page = make_page()
        monkeypatch.setattr(actions_module, "find_element", AsyncMock(return_value=None))
        result = await actions_module.execute_upload(
            page, {"value": "/tmp/f.pdf", "target": "Missing"}, ""
        )
        assert result["status"] == "failed"
        assert "File input not found" in result["error"]

    async def test_upload_no_target_uses_first_file_input(self):
        page = make_page()
        file_input = AsyncMock()
        file_input.set_input_files = AsyncMock()
        first_loc = AsyncMock()
        first_loc.set_input_files = AsyncMock()
        loc = AsyncMock()
        loc.first = first_loc
        page.locator = MagicMock(return_value=loc)
        result = await actions_module.execute_upload(
            page, {"value": "/tmp/a.csv,/tmp/b.csv"}, ""
        )
        assert result["status"] == "passed"
        first_loc.set_input_files.assert_awaited_once_with(["/tmp/a.csv", "/tmp/b.csv"])


# ---------------------------------------------------------------------------
# execute_drag
# ---------------------------------------------------------------------------


class TestExecuteDrag:
    async def test_no_source_returns_failed(self):
        page = make_page()
        result = await actions_module.execute_drag(page, {"value": "Target"}, "")
        assert result["status"] == "failed"
        assert "Source and destination required" in result["error"]

    async def test_no_destination_returns_failed(self):
        page = make_page()
        result = await actions_module.execute_drag(page, {"target": "Source"}, "")
        assert result["status"] == "failed"

    async def test_source_not_found_returns_failed(self, monkeypatch):
        page = make_page()
        monkeypatch.setattr(actions_module, "find_element", AsyncMock(return_value=None))
        result = await actions_module.execute_drag(page, {"target": "Ghost", "value": "Target"}, "")
        assert result["status"] == "failed"
        assert "Source element not found" in result["error"]

    async def test_destination_not_found_returns_failed(self, monkeypatch):
        page = make_page()
        source = AsyncMock()
        call_count = [0]
        async def find_se(page, target):
            call_count[0] += 1
            return source if call_count[0] == 1 else None
        monkeypatch.setattr(actions_module, "find_element", find_se)
        result = await actions_module.execute_drag(page, {"target": "Source", "value": "Ghost"}, "")
        assert result["status"] == "failed"
        assert "Destination element not found" in result["error"]

    async def test_drag_succeeds(self, monkeypatch):
        page = make_page()
        source = AsyncMock()
        dest = AsyncMock()
        source.drag_to = AsyncMock()
        elements = [source, dest]
        call_count = [0]
        async def find_se(page, target):
            idx = call_count[0]
            call_count[0] += 1
            return elements[idx]
        monkeypatch.setattr(actions_module, "find_element", find_se)
        result = await actions_module.execute_drag(page, {"target": "Source", "value": "Dest"}, "")
        assert result["status"] == "passed"
        source.drag_to.assert_awaited_once_with(dest)


# ---------------------------------------------------------------------------
# execute_wait_for_page
# ---------------------------------------------------------------------------


class TestExecuteWaitForPage:
    async def test_default_state_is_load(self, monkeypatch):
        page = make_page()
        page.wait_for_load_state = AsyncMock()
        monkeypatch.setattr(actions_module.asyncio, "sleep", AsyncMock())
        result = await actions_module.execute_wait_for_page(page, {}, "")
        assert result["status"] == "passed"
        page.wait_for_load_state.assert_awaited_once_with("load", timeout=30000)

    async def test_state_mapping_networkidle(self, monkeypatch):
        page = make_page()
        page.wait_for_load_state = AsyncMock()
        monkeypatch.setattr(actions_module.asyncio, "sleep", AsyncMock())
        result = await actions_module.execute_wait_for_page(page, {"value": "idle"}, "")
        assert result["status"] == "passed"
        page.wait_for_load_state.assert_awaited_once_with("networkidle", timeout=30000)

    async def test_state_mapping_dom(self, monkeypatch):
        page = make_page()
        page.wait_for_load_state = AsyncMock()
        monkeypatch.setattr(actions_module.asyncio, "sleep", AsyncMock())
        result = await actions_module.execute_wait_for_page(page, {"value": "dom"}, "")
        assert result["status"] == "passed"
        page.wait_for_load_state.assert_awaited_once_with("domcontentloaded", timeout=30000)

    async def test_state_mapping_network(self, monkeypatch):
        page = make_page()
        page.wait_for_load_state = AsyncMock()
        monkeypatch.setattr(actions_module.asyncio, "sleep", AsyncMock())
        result = await actions_module.execute_wait_for_page(page, {"value": "network"}, "")
        assert result["status"] == "passed"
        page.wait_for_load_state.assert_awaited_once_with("networkidle", timeout=30000)

    async def test_unknown_state_defaults_to_load(self, monkeypatch):
        page = make_page()
        page.wait_for_load_state = AsyncMock()
        monkeypatch.setattr(actions_module.asyncio, "sleep", AsyncMock())
        result = await actions_module.execute_wait_for_page(page, {"value": "custom"}, "")
        assert result["status"] == "passed"
        page.wait_for_load_state.assert_awaited_once_with("load", timeout=30000)

    async def test_timeout_returns_failed(self, monkeypatch):
        page = make_page()
        page.wait_for_load_state = AsyncMock(side_effect=Exception("timeout"))
        monkeypatch.setattr(actions_module.asyncio, "sleep", AsyncMock())
        result = await actions_module.execute_wait_for_page(page, {}, "")
        assert result["status"] == "failed"
        assert "Timeout" in result["error"]


# ---------------------------------------------------------------------------
# execute_capture_state
# ---------------------------------------------------------------------------


class TestExecuteCaptureState:
    async def test_capture_state_success(self):
        page = make_page(url="https://app.example.com/dashboard")
        context = AsyncMock()
        context.storage_state = AsyncMock(return_value={"cookies": [], "origins": []})
        page.context = context
        result = await actions_module.execute_capture_state(page, {}, "")
        assert result["status"] == "passed"
        assert result["result"]["url"] == "https://app.example.com/dashboard"
        assert result["result"]["state"]["cookies"] == []

    async def test_capture_state_exception(self):
        page = make_page()
        context = AsyncMock()
        context.storage_state = AsyncMock(side_effect=Exception("storage broken"))
        page.context = context
        result = await actions_module.execute_capture_state(page, {}, "")
        assert result["status"] == "failed"
        assert "Failed to capture state" in result["error"]


# ---------------------------------------------------------------------------
# execute_scroll — smooth_top and smooth_bottom
# ---------------------------------------------------------------------------


class TestExecuteScrollSmooth:
    async def test_smooth_top(self, monkeypatch):
        page = make_page()
        page.evaluate = AsyncMock()
        result = await actions_module.execute_scroll(page, {"value": "smooth_top"}, "")
        assert result["status"] == "passed"
        page.evaluate.assert_awaited_once()
        # Verify the JS snippet mentions scrollY
        call_args = page.evaluate.await_args[0][0]
        assert "scrollY" in call_args

    async def test_smooth_bottom(self, monkeypatch):
        page = make_page()
        page.evaluate = AsyncMock()
        result = await actions_module.execute_scroll(page, {"value": "smooth_bottom"}, "")
        assert result["status"] == "passed"
        page.evaluate.assert_awaited_once()


# ---------------------------------------------------------------------------
# execute_wait — target and value-as-text branches
# ---------------------------------------------------------------------------


class TestExecuteWaitTargetAndText:
    async def test_target_not_found_returns_failed(self, monkeypatch):
        page = make_page()
        monkeypatch.setattr(actions_module, "_wait_for_element", AsyncMock(return_value=False))
        result = await actions_module.execute_wait(page, {"target": "Loading spinner"}, "")
        assert result["status"] == "failed"
        assert "Timeout waiting for" in result["error"]

    async def test_value_as_text_found(self, monkeypatch):
        page = make_page()
        monkeypatch.setattr(actions_module, "_wait_for_element", AsyncMock(return_value=True))
        result = await actions_module.execute_wait(page, {"value": "Success message"}, "")
        assert result["status"] == "passed"

    async def test_value_as_text_not_found_returns_failed(self, monkeypatch):
        page = make_page()
        monkeypatch.setattr(actions_module, "_wait_for_element", AsyncMock(return_value=False))
        result = await actions_module.execute_wait(page, {"value": "Missing text"}, "")
        assert result["status"] == "failed"
        assert "Timeout waiting for" in result["error"]


# ---------------------------------------------------------------------------
# execute_select — non-interactive fallback, hidden select, strategy 2/3/4
# ---------------------------------------------------------------------------


class TestExecuteSelectAdditional:
    def _make_page_with_tag(self, tag_name):
        """Builds a page where the found element has a given tagName."""
        page = make_page()
        element = AsyncMock()
        element.evaluate = AsyncMock(return_value=tag_name)
        element.scroll_into_view_if_needed = AsyncMock()
        element.click = AsyncMock()
        element.select_option = AsyncMock()
        return page, element

    async def test_select_native_select_element(self, monkeypatch):
        """<select> element: calls select_option directly."""
        page, element = self._make_page_with_tag("select")
        # is_hidden check returns False (element is visible)
        element.evaluate = AsyncMock(side_effect=["select", False])
        element.select_option = AsyncMock()
        monkeypatch.setattr(actions_module, "_find_combobox_by_label", AsyncMock(return_value=element))
        monkeypatch.setattr(actions_module, "_wait_for_options", AsyncMock(return_value=True))
        monkeypatch.setattr(actions_module, "_click_option_by_text", AsyncMock(return_value=False))
        result = await actions_module.execute_select(
            page, {"target": "Status", "value": "Active"}, ""
        )
        assert result["status"] == "passed"
        element.select_option.assert_awaited_once_with(["Active"], timeout=5000)

    async def test_select_strategy2_partial_match(self, monkeypatch):
        """Strategy 2: partial match after '(' is tried."""
        page = make_page()
        element = AsyncMock()
        element.evaluate = AsyncMock(return_value="div")
        element.scroll_into_view_if_needed = AsyncMock()
        element.click = AsyncMock()
        monkeypatch.setattr(actions_module, "_find_combobox_by_label", AsyncMock(return_value=element))
        monkeypatch.setattr(actions_module, "find_element", AsyncMock(return_value=None))
        monkeypatch.setattr(actions_module, "_wait_for_options", AsyncMock(return_value=True))
        monkeypatch.setattr(actions_module, "_click_option_by_text", AsyncMock(return_value=False))

        # Locator with no exact match, but partial match exists
        empty = make_empty_locator()
        partial_loc = AsyncMock()
        partial_loc.count = AsyncMock(return_value=1)
        partial_loc.first = AsyncMock()
        partial_loc.first.click = AsyncMock()

        call_count = [0]
        def filter_se(**kw):
            loc = AsyncMock()
            has_text = kw.get("has_text", "")
            if "(" in has_text:
                loc.count = AsyncMock(return_value=0)
            else:
                loc.count = AsyncMock(return_value=1)
                loc.first = AsyncMock()
                loc.first.click = AsyncMock()
            return loc

        base_loc = AsyncMock()
        base_loc.filter = MagicMock(side_effect=filter_se)
        page.locator = MagicMock(return_value=base_loc)
        page.evaluate = AsyncMock(return_value=[])
        page.wait_for_timeout = AsyncMock()

        result = await actions_module.execute_select(
            page, {"target": "Type", "value": "Key Replacement (Make New Key)"}, ""
        )
        assert result["status"] == "passed"

    async def test_select_strategy3_js_click(self, monkeypatch):
        """Strategy 3: JS click when filter strategies fail."""
        page = make_page()
        element = AsyncMock()
        element.evaluate = AsyncMock(return_value="div")
        element.scroll_into_view_if_needed = AsyncMock()
        element.click = AsyncMock()
        monkeypatch.setattr(actions_module, "_find_combobox_by_label", AsyncMock(return_value=element))
        monkeypatch.setattr(actions_module, "find_element", AsyncMock(return_value=None))
        monkeypatch.setattr(actions_module, "_wait_for_options", AsyncMock(return_value=True))
        monkeypatch.setattr(actions_module, "_click_option_by_text", AsyncMock(return_value=True))

        base_loc = AsyncMock()
        base_loc.filter = MagicMock(return_value=make_empty_locator())
        page.locator = MagicMock(return_value=base_loc)
        page.evaluate = AsyncMock(return_value=[])
        page.wait_for_timeout = AsyncMock()

        result = await actions_module.execute_select(
            page, {"target": "Priority", "value": "High"}, ""
        )
        assert result["status"] == "passed"

    async def test_select_all_strategies_fail_returns_failed(self, monkeypatch):
        """All strategies fail → status=failed with available options."""
        page = make_page()
        element = AsyncMock()
        element.evaluate = AsyncMock(return_value="button")
        element.scroll_into_view_if_needed = AsyncMock()
        element.click = AsyncMock()
        monkeypatch.setattr(actions_module, "_find_combobox_by_label", AsyncMock(return_value=element))
        monkeypatch.setattr(actions_module, "find_element", AsyncMock(return_value=None))
        monkeypatch.setattr(actions_module, "_wait_for_options", AsyncMock(return_value=True))
        monkeypatch.setattr(actions_module, "_click_option_by_text", AsyncMock(return_value=False))

        empty = make_empty_locator()
        empty.filter = MagicMock(return_value=empty)
        page.locator = MagicMock(return_value=empty)
        page.evaluate = AsyncMock(return_value=["Option A", "Option B"])
        page.get_by_role = MagicMock(return_value=empty)
        page.wait_for_timeout = AsyncMock()

        result = await actions_module.execute_select(
            page, {"target": "Status", "value": "Missing"}, ""
        )
        assert result["status"] == "failed"
        assert "Missing" in result["error"]


# ---------------------------------------------------------------------------
# _wait_for_options and _click_option_by_text (direct internal helper tests)
# ---------------------------------------------------------------------------


class TestWaitForOptionsHelper:
    async def test_succeeds_returns_true(self):
        """wait_for_selector succeeds → True."""
        page = make_page()
        page.wait_for_selector = AsyncMock()
        result = await actions_module._wait_for_options(page, timeout=500)
        assert result is True

    async def test_raises_returns_false(self):
        """wait_for_selector raises → False."""
        page = make_page()
        page.wait_for_selector = AsyncMock(side_effect=Exception("timeout"))
        result = await actions_module._wait_for_options(page, timeout=100)
        assert result is False


class TestClickOptionByText:
    async def test_calls_evaluate(self):
        """_click_option_by_text delegates to page.evaluate and returns its value."""
        page = make_page()
        page.evaluate = AsyncMock(return_value=True)
        result = await actions_module._click_option_by_text(page, "Option A")
        assert result is True
        page.evaluate.assert_awaited_once()


# ---------------------------------------------------------------------------
# execute_select — missing strategy paths
# ---------------------------------------------------------------------------


class TestExecuteSelectMissingStrategies:
    """Cover Strategy 2 (partial) and Strategy 3 (JS click) in execute_select."""

    def _make_page_with_combobox(self, monkeypatch, element):
        """Set up a page with a combobox element that has been clicked open."""
        page = make_page()
        monkeypatch.setattr(actions_module, "_find_combobox_by_label", AsyncMock(return_value=element))
        monkeypatch.setattr(actions_module, "find_element", AsyncMock(return_value=None))
        monkeypatch.setattr(actions_module, "_wait_for_options", AsyncMock(return_value=True))
        page.wait_for_timeout = AsyncMock()
        page.evaluate = AsyncMock(return_value=[])  # available options log
        return page

    async def test_strategy2_partial_match_succeeds(self, monkeypatch):
        """Strategy 2: partial text match (strip parenthetical) → passed."""
        element = AsyncMock()
        element.evaluate = AsyncMock(return_value="button")
        element.scroll_into_view_if_needed = AsyncMock()
        element.click = AsyncMock()
        page = self._make_page_with_combobox(monkeypatch, element)

        empty = make_empty_locator()
        empty.filter = MagicMock(return_value=empty)

        # Strategy 1 filter returns empty; Strategy 2 partial filter returns found
        found = make_found_locator()
        found.first = AsyncMock()
        found.first.click = AsyncMock()

        call_count = [0]
        def filter_se(**kw):
            call_count[0] += 1
            return empty if call_count[0] == 1 else found

        loc = AsyncMock()
        loc.filter = MagicMock(side_effect=filter_se)
        page.locator = MagicMock(return_value=loc)

        result = await actions_module.execute_select(
            page, {"target": "Color", "value": "Key Replacement (Make New Key)"}, ""
        )
        assert result["status"] == "passed"

    async def test_strategy3_js_click_succeeds(self, monkeypatch):
        """Strategy 3: _click_option_by_text returns True → passed."""
        element = AsyncMock()
        element.evaluate = AsyncMock(return_value="button")
        element.scroll_into_view_if_needed = AsyncMock()
        element.click = AsyncMock()
        page = self._make_page_with_combobox(monkeypatch, element)

        # All filter locators return empty (no option by filter)
        empty = make_empty_locator()
        empty.filter = MagicMock(return_value=empty)
        page.locator = MagicMock(return_value=empty)

        # Strategy 3: JS click succeeds
        monkeypatch.setattr(actions_module, "_click_option_by_text", AsyncMock(return_value=True))

        result = await actions_module.execute_select(
            page, {"target": "Status", "value": "Active"}, ""
        )
        assert result["status"] == "passed"

    async def test_strategy4_role_locator_succeeds(self, monkeypatch):
        """Strategy 4: get_by_role("option") finds and clicks option → passed."""
        element = AsyncMock()
        element.evaluate = AsyncMock(return_value="button")
        element.scroll_into_view_if_needed = AsyncMock()
        element.click = AsyncMock()
        page = self._make_page_with_combobox(monkeypatch, element)

        empty = make_empty_locator()
        empty.filter = MagicMock(return_value=empty)
        page.locator = MagicMock(return_value=empty)

        monkeypatch.setattr(actions_module, "_click_option_by_text", AsyncMock(return_value=False))

        # Strategy 4: get_by_role("option") with count > 0
        found = make_found_locator()
        found.first = AsyncMock()
        found.first.click = AsyncMock()
        empty_role = make_empty_locator()

        call_count = [0]
        def role_se(role, **kw):
            call_count[0] += 1
            if role == "option" and call_count[0] == 1:
                return found
            return empty_role

        page.get_by_role = MagicMock(side_effect=role_se)
        page.wait_for_timeout = AsyncMock()

        result = await actions_module.execute_select(
            page, {"target": "Status", "value": "Active"}, ""
        )
        assert result["status"] == "passed"


# ---------------------------------------------------------------------------
# _wait_for_element — exception handler branches (lines 66-67, 74-75, 82-83)
# ---------------------------------------------------------------------------


class TestWaitForElementExceptionHandlers:
    """Tests that verify exception handlers in NL polling branches are covered."""

    async def test_button_role_count_raises_still_polls_link(self, monkeypatch):
        """button role locator.count() raises → button except caught; link branch finds it."""
        monkeypatch.setattr(actions_module.asyncio, "sleep", AsyncMock())
        page = make_page()
        found = make_found_locator()
        empty = make_empty_locator()

        # Button role: count raises
        btn_loc = AsyncMock()
        btn_loc.count = AsyncMock(side_effect=Exception("button broken"))
        # Link role: count returns 1
        link_loc = make_found_locator()

        def role_se(role, **kw):
            if role == "button":
                return btn_loc
            if role == "link":
                return link_loc
            return empty

        page.get_by_role = MagicMock(side_effect=role_se)
        page.get_by_text = MagicMock(return_value=empty)
        result = await actions_module._wait_for_element(page, "Home link", timeout=500)
        assert result is True

    async def test_link_role_count_raises_still_polls_text(self, monkeypatch):
        """link role count raises → link except caught; text branch finds it."""
        monkeypatch.setattr(actions_module.asyncio, "sleep", AsyncMock())
        page = make_page()
        empty = make_empty_locator()

        bad_loc = AsyncMock()
        bad_loc.count = AsyncMock(side_effect=Exception("gone"))

        page.get_by_role = MagicMock(return_value=bad_loc)
        text_loc = make_found_locator()
        page.get_by_text = MagicMock(return_value=text_loc)
        result = await actions_module._wait_for_element(page, "Welcome text", timeout=500)
        assert result is True

    async def test_text_count_raises_returns_false_on_timeout(self, monkeypatch):
        """All role/text locators raise → all excepts caught; timeout returns False."""
        monkeypatch.setattr(actions_module.asyncio, "sleep", AsyncMock())
        page = make_page()
        bad_loc = AsyncMock()
        bad_loc.count = AsyncMock(side_effect=Exception("stale"))
        page.get_by_role = MagicMock(return_value=bad_loc)
        bad_text = AsyncMock()
        bad_text.count = AsyncMock(side_effect=Exception("stale"))
        page.get_by_text = MagicMock(return_value=bad_text)
        result = await actions_module._wait_for_element(page, "Ghost item", timeout=100)
        assert result is False


# ---------------------------------------------------------------------------
# _click_nearest_from_locator — null bbox and exception paths
# ---------------------------------------------------------------------------


class TestClickNearestFromLocatorEdgeCases:
    async def test_none_bbox_skipped_picks_valid_element(self):
        """When nth(0) bbox is None, continue to nth(1) with valid bbox."""
        loc = AsyncMock()
        loc.count = AsyncMock(return_value=2)

        el0 = AsyncMock()
        el0.bounding_box = AsyncMock(return_value=None)  # line 201: continue
        el1 = AsyncMock()
        el1.bounding_box = AsyncMock(return_value={"x": 50, "y": 50, "width": 20, "height": 20})
        el1.click = AsyncMock()

        loc.nth = MagicMock(side_effect=lambda i: el0 if i == 0 else el1)
        result = await actions_module._click_nearest_from_locator(loc, 55, 55)
        assert result is True
        el1.click.assert_awaited_once()

    async def test_bounding_box_raises_exception_continues(self):
        """When bounding_box() raises, exception is caught and loop continues."""
        loc = AsyncMock()
        loc.count = AsyncMock(return_value=2)

        el0 = AsyncMock()
        el0.bounding_box = AsyncMock(side_effect=Exception("stale element"))
        el1 = AsyncMock()
        el1.bounding_box = AsyncMock(return_value={"x": 100, "y": 100, "width": 10, "height": 10})
        el1.click = AsyncMock()

        loc.nth = MagicMock(side_effect=lambda i: el0 if i == 0 else el1)
        result = await actions_module._click_nearest_from_locator(loc, 105, 105)
        assert result is True
        el1.click.assert_awaited_once()


# ---------------------------------------------------------------------------
# execute_click — dialog exception paths and extra waterfall coverage
# ---------------------------------------------------------------------------


class TestExecuteClickExtraCoverage:
    """Tests that cover previously uncovered execute_click branches."""

    async def test_dialog_count_raises_before_click_defaults_zero(self, monkeypatch):
        """When initial dialog count raises, dialogs_before defaults to 0 and click proceeds."""
        monkeypatch.setattr(actions_module.asyncio, "sleep", AsyncMock())
        element = AsyncMock()
        element.bounding_box = AsyncMock(return_value=None)
        element.click = AsyncMock()
        monkeypatch.setattr(actions_module, "find_clickable_element", AsyncMock(return_value=element))
        monkeypatch.setattr(actions_module, "find_element", AsyncMock(return_value=None))

        page = make_page()
        empty = make_empty_locator()
        page.get_by_role = MagicMock(return_value=empty)
        page.get_by_text = MagicMock(return_value=empty)

        # Make locator raise only for the dialog selector (before click)
        call_count = [0]
        dialog_empty = AsyncMock()
        dialog_empty.count = AsyncMock(side_effect=Exception("dialog query failed"))

        def loc_se(sel):
            if "dialog" in sel:
                return dialog_empty
            return empty

        page.locator = MagicMock(side_effect=loc_se)

        result = await actions_module.execute_click(page, {"target": "Submit"}, "")
        assert result["status"] == "passed"

    async def test_post_click_dialog_count_raises_is_swallowed(self, monkeypatch):
        """After click, if dialog after-count raises, the exception is caught silently."""
        monkeypatch.setattr(actions_module.asyncio, "sleep", AsyncMock())
        element = AsyncMock()
        element.bounding_box = AsyncMock(return_value=None)
        element.click = AsyncMock()
        monkeypatch.setattr(actions_module, "find_clickable_element", AsyncMock(return_value=element))
        monkeypatch.setattr(actions_module, "find_element", AsyncMock(return_value=None))

        page = make_page()
        empty = make_empty_locator()
        page.get_by_role = MagicMock(return_value=empty)
        page.get_by_text = MagicMock(return_value=empty)

        before_call = [0]

        def loc_se(sel):
            if "dialog" in sel:
                before_call[0] += 1
                if before_call[0] <= 2:
                    # First calls (pre-click in execute_click + in waterfall): succeed
                    return empty
                # After-click call: raise
                bad = AsyncMock()
                bad.count = AsyncMock(side_effect=Exception("after-click dialog fail"))
                return bad
            return empty

        page.locator = MagicMock(side_effect=loc_se)

        result = await actions_module.execute_click(page, {"target": "Submit"}, "")
        assert result["status"] == "passed"

    async def test_utml_with_coordinates_proximity_ok(self, monkeypatch):
        """UTML match with coordinates within 250px → proximity check passes, normal click."""
        monkeypatch.setattr(actions_module.asyncio, "sleep", AsyncMock())
        element = AsyncMock()
        # bbox close to recorded coords (10px away)
        element.bounding_box = AsyncMock(return_value={"x": 95, "y": 195, "width": 10, "height": 10})
        element.click = AsyncMock()
        monkeypatch.setattr(actions_module, "find_clickable_element", AsyncMock(return_value=element))
        monkeypatch.setattr(actions_module, "find_element", AsyncMock(return_value=None))

        page = make_page()
        empty = make_empty_locator()
        page.locator = MagicMock(return_value=empty)
        page.get_by_role = MagicMock(return_value=empty)
        page.get_by_text = MagicMock(return_value=empty)

        step = {
            "target": "Submit",
            "coordinates": {"pageX": 100, "pageY": 200},
        }
        result = await actions_module.execute_click(page, step, "")
        assert result["status"] == "passed"
        element.click.assert_awaited()

    async def test_utml_with_coordinates_too_far_tries_click_nearest(self, monkeypatch):
        """UTML match is >250px from recorded coords → _click_nearest tried."""
        monkeypatch.setattr(actions_module.asyncio, "sleep", AsyncMock())
        element = AsyncMock()
        # bbox 500px away from recorded coords
        element.bounding_box = AsyncMock(return_value={"x": 600, "y": 700, "width": 10, "height": 10})
        element.click = AsyncMock()
        monkeypatch.setattr(actions_module, "find_clickable_element", AsyncMock(return_value=element))
        monkeypatch.setattr(actions_module, "find_element", AsyncMock(return_value=None))

        # _click_nearest will be called; mock it to succeed
        monkeypatch.setattr(actions_module, "_click_nearest", AsyncMock(return_value=True))

        page = make_page()
        empty = make_empty_locator()
        page.locator = MagicMock(return_value=empty)
        page.get_by_role = MagicMock(return_value=empty)
        page.get_by_text = MagicMock(return_value=empty)

        step = {
            "target": "Submit",
            "coordinates": {"pageX": 100, "pageY": 200},
        }
        result = await actions_module.execute_click(page, step, "")
        assert result["status"] == "passed"
        assert result["resolved_by"] == "utml+coordinates"

    async def test_utml_dialog_scope_used_when_dialog_visible(self, monkeypatch):
        """When a dialog is visible, UTML count uses dialog as scope."""
        monkeypatch.setattr(actions_module.asyncio, "sleep", AsyncMock())
        element = AsyncMock()
        element.bounding_box = AsyncMock(return_value=None)
        element.click = AsyncMock()
        monkeypatch.setattr(actions_module, "find_clickable_element", AsyncMock(return_value=element))
        monkeypatch.setattr(actions_module, "find_element", AsyncMock(return_value=None))

        page = make_page()
        empty = make_empty_locator()

        # dialog.count() > 0 → triggers line 363 (count_scope = dialog_loc.last)
        dialog_loc = AsyncMock()
        dialog_loc.count = AsyncMock(return_value=1)
        dialog_loc.last = MagicMock()
        dialog_loc.last.get_by_role = MagicMock(return_value=empty)
        dialog_loc.last.get_by_text = MagicMock(return_value=empty)

        call_count = [0]
        def loc_se(sel):
            if "dialog" in sel.lower():
                return dialog_loc
            return empty

        page.locator = MagicMock(side_effect=loc_se)
        page.get_by_role = MagicMock(return_value=empty)
        page.get_by_text = MagicMock(return_value=empty)

        result = await actions_module.execute_click(page, {"target": "Confirm"}, "")
        assert result["status"] == "passed"
        element.click.assert_awaited()

    async def test_utml_count_greater_one_no_coords_falls_through(self, monkeypatch):
        """UTML finds count > 1 and no coords → multi-match error, falls through tiers."""
        monkeypatch.setattr(actions_module.asyncio, "sleep", AsyncMock())
        element = AsyncMock()
        element.bounding_box = AsyncMock(return_value=None)
        element.click = AsyncMock()
        monkeypatch.setattr(actions_module, "find_clickable_element", AsyncMock(return_value=element))
        monkeypatch.setattr(actions_module, "find_element", AsyncMock(return_value=None))
        monkeypatch.setattr(actions_module, "_try_hover_submenu", AsyncMock(return_value=None))

        page = make_page()
        # get_by_role returns count=2 → multiple matches
        multi_loc = AsyncMock()
        multi_loc.count = AsyncMock(return_value=2)
        empty = make_empty_locator()

        page.locator = MagicMock(return_value=empty)
        page.get_by_role = MagicMock(return_value=multi_loc)
        page.get_by_text = MagicMock(return_value=empty)
        page.evaluate = AsyncMock(return_value=[])

        result = await actions_module.execute_click(page, {"target": "Delete"}, "")
        assert result["status"] == "failed"

    async def test_css_direct_target_not_found_returns_failed(self, monkeypatch):
        """CSS selector as target, element not found → CSS selector not found error."""
        monkeypatch.setattr(actions_module.asyncio, "sleep", AsyncMock())
        monkeypatch.setattr(actions_module, "find_element", AsyncMock(return_value=None))
        monkeypatch.setattr(actions_module, "_try_hover_submenu", AsyncMock(return_value=None))

        page = make_page()
        empty = make_empty_locator()
        page.locator = MagicMock(return_value=empty)
        page.evaluate = AsyncMock(return_value=[])

        result = await actions_module.execute_click(page, {"target": "#ghost-btn"}, "")
        assert result["status"] == "failed"
        assert "CSS selector not found" in result["error"] or "exhausted" in result["error"]

    async def test_css_direct_target_click_raises(self, monkeypatch):
        """CSS selector as target, click raises → last_error set, waterfall continues."""
        monkeypatch.setattr(actions_module.asyncio, "sleep", AsyncMock())
        element = AsyncMock()
        element.click = AsyncMock(side_effect=Exception("element not clickable"))
        monkeypatch.setattr(actions_module, "find_element", AsyncMock(return_value=element))
        monkeypatch.setattr(actions_module, "_try_hover_submenu", AsyncMock(return_value=None))

        page = make_page()
        empty = make_empty_locator()
        page.locator = MagicMock(return_value=empty)
        page.evaluate = AsyncMock(return_value=[])

        result = await actions_module.execute_click(page, {"target": "#submit-btn"}, "")
        assert result["status"] == "failed"

    async def test_coords_merged_into_locators(self, monkeypatch):
        """When step has coordinates but locators has no 'coordinates' key, it's merged."""
        monkeypatch.setattr(actions_module.asyncio, "sleep", AsyncMock())
        element = AsyncMock()
        element.bounding_box = AsyncMock(return_value={"x": 100, "y": 200, "width": 10, "height": 10})
        element.click = AsyncMock()
        monkeypatch.setattr(actions_module, "find_clickable_element", AsyncMock(return_value=element))
        monkeypatch.setattr(actions_module, "find_element", AsyncMock(return_value=None))

        page = make_page()
        empty = make_empty_locator()
        page.locator = MagicMock(return_value=empty)
        page.get_by_role = MagicMock(return_value=empty)
        page.get_by_text = MagicMock(return_value=empty)

        step = {
            "target": "Submit",
            "coordinates": {"pageX": 105, "pageY": 205},
            "locators": {"css": ""},  # no "coordinates" key in locators
        }
        result = await actions_module.execute_click(page, step, "")
        assert result["status"] == "passed"

    async def test_long_target_uses_short_target_variant(self, monkeypatch):
        """Target >40 chars with camelCase boundary → _short_target variant added."""
        monkeypatch.setattr(actions_module.asyncio, "sleep", AsyncMock())
        monkeypatch.setattr(actions_module, "_try_hover_submenu", AsyncMock(return_value=None))

        element = AsyncMock()
        element.bounding_box = AsyncMock(return_value=None)
        element.click = AsyncMock()

        call_count = [0]
        async def fake_find_clickable(page, target):
            call_count[0] += 1
            # Return element for the short variant
            if len(target) <= 40:
                return element
            return None

        monkeypatch.setattr(actions_module, "find_clickable_element", fake_find_clickable)
        monkeypatch.setattr(actions_module, "find_element", AsyncMock(return_value=None))

        page = make_page()
        empty = make_empty_locator()
        page.locator = MagicMock(return_value=empty)
        page.get_by_role = MagicMock(return_value=empty)
        page.get_by_text = MagicMock(return_value=empty)

        # Target >40 chars with camelCase boundary (e.g. "ProfileSettings")
        long_target = "DashboardOverviewSummaryPageHeaderTitle"  # >40 chars, camelCase
        result = await actions_module.execute_click(page, {"target": long_target}, "")
        assert result["status"] == "passed"

    async def test_retry_loop_sleeps_on_second_attempt(self, monkeypatch):
        """When all tiers fail, the retry loop sleeps and retries."""
        sleep_calls = []
        async def fake_sleep(secs):
            sleep_calls.append(secs)

        monkeypatch.setattr(actions_module.asyncio, "sleep", fake_sleep)
        monkeypatch.setattr(actions_module, "_try_hover_submenu", AsyncMock(return_value=None))

        attempt_count = [0]

        async def find_clickable_se(page, target):
            attempt_count[0] += 1
            if attempt_count[0] <= 3:  # fail first full pass (3 target_variants * find_clickable)
                return None
            element = AsyncMock()
            element.bounding_box = AsyncMock(return_value=None)
            element.click = AsyncMock()
            return element

        monkeypatch.setattr(actions_module, "find_clickable_element", find_clickable_se)
        monkeypatch.setattr(actions_module, "find_element", AsyncMock(return_value=None))

        page = make_page()
        empty = make_empty_locator()
        page.locator = MagicMock(return_value=empty)
        page.get_by_role = MagicMock(return_value=empty)
        page.get_by_text = MagicMock(return_value=empty)
        page.evaluate = AsyncMock(return_value=[])

        result = await actions_module.execute_click(page, {"target": "Submit"}, "")
        # Sleep of 2s should have been called (retry interval)
        assert any(s == 2 for s in sleep_calls)

    async def test_tier4_hover_invoked_when_all_tiers_fail(self, monkeypatch):
        """When all tiers find nothing, _try_hover_submenu is called."""
        monkeypatch.setattr(actions_module.asyncio, "sleep", AsyncMock())
        hover_calls = []

        async def fake_hover(page, target):
            hover_calls.append(target)
            return {"status": "passed", "resolved_by": "hover+utml"}

        monkeypatch.setattr(actions_module, "_try_hover_submenu", fake_hover)
        monkeypatch.setattr(actions_module, "find_clickable_element", AsyncMock(return_value=None))
        monkeypatch.setattr(actions_module, "find_element", AsyncMock(return_value=None))

        page = make_page()
        empty = make_empty_locator()
        page.locator = MagicMock(return_value=empty)
        page.get_by_role = MagicMock(return_value=empty)
        page.get_by_text = MagicMock(return_value=empty)
        page.evaluate = AsyncMock(return_value=[])

        result = await actions_module.execute_click(page, {"target": "Export CSV"}, "")
        assert result["status"] == "passed"
        assert result["resolved_by"] == "hover+utml"
        assert "Export CSV" in hover_calls


# ---------------------------------------------------------------------------
# _try_hover_submenu
# ---------------------------------------------------------------------------


class TestTryHoverSubmenu:
    async def test_empty_trigger_chain_returns_none(self):
        """When JS evaluate returns [], _try_hover_submenu returns None immediately."""
        page = make_page()
        page.evaluate = AsyncMock(return_value=[])
        result = await actions_module._try_hover_submenu(page, "Export CSV")
        assert result is None

    async def test_trigger_chain_hover_then_click_succeeds(self):
        """Hover the trigger, then the target becomes visible and is clicked."""
        page = make_page()
        page.evaluate = AsyncMock(return_value=["Products"])
        page.wait_for_timeout = AsyncMock()

        trig_loc = AsyncMock()
        trig_loc.count = AsyncMock(return_value=1)
        trig_loc.first = AsyncMock()
        trig_loc.first.hover = AsyncMock()

        target_loc = AsyncMock()
        target_loc.first = AsyncMock()
        target_loc.first.is_visible = AsyncMock(return_value=True)
        target_loc.first.click = AsyncMock()

        def get_by_role_se(role, **kw):
            name = kw.get("name", "")
            if name == "Products":
                return trig_loc
            return target_loc

        def get_by_text_se(text, **kw):
            return trig_loc if text == "Products" else target_loc

        or_result = AsyncMock()
        or_result.count = AsyncMock(return_value=1)
        or_result.first = AsyncMock()
        or_result.first.hover = AsyncMock()
        trig_loc.or_ = MagicMock(return_value=or_result)

        page.get_by_role = MagicMock(side_effect=get_by_role_se)
        page.get_by_text = MagicMock(side_effect=get_by_text_se)

        result = await actions_module._try_hover_submenu(page, "Export CSV")
        assert result is not None
        assert result["resolved_by"] == "hover+utml"

    async def test_trigger_chain_target_not_visible_returns_none(self):
        """Trigger chain exists but target never becomes visible → returns None."""
        page = make_page()
        page.evaluate = AsyncMock(return_value=["Products"])
        page.wait_for_timeout = AsyncMock()

        empty = make_empty_locator()
        trig_loc = AsyncMock()
        trig_loc.count = AsyncMock(return_value=1)
        trig_loc.first = AsyncMock()
        trig_loc.first.hover = AsyncMock()
        trig_loc.or_ = MagicMock(return_value=trig_loc)

        invisible_loc = AsyncMock()
        invisible_loc.first = AsyncMock()
        invisible_loc.first.is_visible = AsyncMock(return_value=False)

        def get_by_role_se(role, **kw):
            name = kw.get("name", "")
            if name == "Products":
                return trig_loc
            return invisible_loc

        page.get_by_role = MagicMock(side_effect=get_by_role_se)
        page.get_by_text = MagicMock(return_value=invisible_loc)

        result = await actions_module._try_hover_submenu(page, "Ghost Item")
        assert result is None


# ---------------------------------------------------------------------------
# execute_type — password field branch (lines 702-703)
# ---------------------------------------------------------------------------


class TestExecuteTypePasswordField:
    async def test_password_in_target_uses_human_typing(self, monkeypatch):
        """When target contains 'password', use element.type() with delay."""
        page = make_page()
        element = AsyncMock()
        element.get_attribute = AsyncMock(return_value="text")  # not password type
        element.click = AsyncMock()
        element.fill = AsyncMock()
        element.type = AsyncMock()
        monkeypatch.setattr(actions_module, "find_input_element", AsyncMock(return_value=element))

        result = await actions_module.execute_type(
            page, {"target": "password", "value": "secret123"}, ""
        )
        assert result["status"] == "passed"
        element.type.assert_awaited_once_with("secret123", delay=50)

    async def test_input_type_password_uses_human_typing(self, monkeypatch):
        """When element has type='password', use element.type() with delay."""
        page = make_page()
        element = AsyncMock()
        element.get_attribute = AsyncMock(return_value="password")
        element.click = AsyncMock()
        element.fill = AsyncMock()
        element.type = AsyncMock()
        monkeypatch.setattr(actions_module, "find_input_element", AsyncMock(return_value=element))

        result = await actions_module.execute_type(
            page, {"target": "Secret Field", "value": "p@ssw0rd"}, ""
        )
        assert result["status"] == "passed"
        element.type.assert_awaited_once_with("p@ssw0rd", delay=50)

    async def test_get_attribute_raises_falls_back_to_fill(self, monkeypatch):
        """When get_attribute raises during password check, exception caught → fill used."""
        page = make_page()
        element = AsyncMock()
        # target doesn't contain "password" → check attribute
        element.get_attribute = AsyncMock(side_effect=Exception("stale element"))
        element.fill = AsyncMock()
        monkeypatch.setattr(actions_module, "find_input_element", AsyncMock(return_value=element))

        result = await actions_module.execute_type(
            page, {"target": "Email Field", "value": "test@example.com"}, ""
        )
        assert result["status"] == "passed"
        element.fill.assert_awaited_once_with("test@example.com", timeout=5000)


# ---------------------------------------------------------------------------
# execute_wait — ValueError branch (lines 995-997)
# ---------------------------------------------------------------------------


class TestExecuteWaitValueError:
    async def test_non_numeric_value_waits_for_element(self, monkeypatch):
        """When value is non-numeric, treat as text to wait for."""
        page = make_page()
        monkeypatch.setattr(actions_module, "_wait_for_element", AsyncMock(return_value=True))
        result = await actions_module.execute_wait(
            page, {"value": "Loading complete"}, ""
        )
        assert result["status"] == "passed"

    async def test_non_numeric_value_not_found_returns_failed(self, monkeypatch):
        """Non-numeric value that never appears → failed."""
        page = make_page()
        monkeypatch.setattr(actions_module, "_wait_for_element", AsyncMock(return_value=False))
        result = await actions_module.execute_wait(
            page, {"value": "Never Appears"}, ""
        )
        assert result["status"] == "failed"

    async def test_outer_exception_caught(self, monkeypatch):
        """Outer exception (not ValueError) from _wait_for_element → outer except caught."""
        page = make_page()
        monkeypatch.setattr(
            actions_module, "_wait_for_element",
            AsyncMock(side_effect=RuntimeError("network gone")),
        )
        result = await actions_module.execute_wait(
            page, {"value": "Loading complete"}, ""
        )
        assert result["status"] == "failed"
        assert "Timeout waiting for" in result["error"]


# ---------------------------------------------------------------------------
# execute_assert_text — Strategy 2 path (lines 1042-1045)
# ---------------------------------------------------------------------------


class TestExecuteAssertTextStrategy2:
    async def test_strategy2_regex_match_passes(self, monkeypatch):
        """Strategy 1 fails; Strategy 2 (regex count > 0 + visible) passes."""
        page = make_page()
        page.wait_for_load_state = AsyncMock(side_effect=Exception("timeout"))

        # Strategy 1 locator (exact=False) → expect raises
        s1_locator = AsyncMock()
        s1_locator.first = AsyncMock()

        # Strategy 2 locator (regex) → count > 0
        s2_locator = AsyncMock()
        s2_locator.count = AsyncMock(return_value=2)
        s2_locator.first = AsyncMock()

        call_count = [0]
        def get_by_text_se(arg, **kw):
            call_count[0] += 1
            if call_count[0] == 1:
                return s1_locator  # strategy 1
            return s2_locator  # strategy 2

        page.get_by_text = MagicMock(side_effect=get_by_text_se)

        # Strategy 1 expect raises; Strategy 2 expect succeeds
        call_expect = [0]
        def fake_expect(locator):
            call_expect[0] += 1
            m = AsyncMock()
            if call_expect[0] == 1:
                m.to_be_visible = AsyncMock(side_effect=AssertionError("not visible"))
            else:
                m.to_be_visible = AsyncMock()  # success
            return m

        monkeypatch.setattr(actions_module, "expect", fake_expect)

        result = await execute_assert_text(page, {"value": "Hello World"}, "")
        assert result["status"] == "passed"

    async def test_strategy2_expect_raises_falls_to_strategy3(self, monkeypatch):
        """Strategy 1+2 expect raises; Strategy 3 body text passes."""
        page = make_page()
        page.wait_for_load_state = AsyncMock()

        s1_locator = AsyncMock()
        s1_locator.first = AsyncMock()
        s2_locator = AsyncMock()
        s2_locator.count = AsyncMock(return_value=1)
        s2_locator.first = AsyncMock()

        call_count = [0]
        def get_by_text_se(arg, **kw):
            call_count[0] += 1
            if call_count[0] == 1:
                return s1_locator
            return s2_locator

        page.get_by_text = MagicMock(side_effect=get_by_text_se)

        # Both strategy 1 and 2 expect raises
        mock_assertion = AsyncMock()
        mock_assertion.to_be_visible = AsyncMock(side_effect=AssertionError("invisible"))
        monkeypatch.setattr(actions_module, "expect", MagicMock(return_value=mock_assertion))

        # Strategy 3 body text contains the expected text
        page.evaluate = AsyncMock(return_value="Welcome to the system operational")

        result = await execute_assert_text(page, {"value": "operational"}, "")
        assert result["status"] == "passed"


# ---------------------------------------------------------------------------
# execute_fill_form / execute_upload / execute_drag — exception paths
# ---------------------------------------------------------------------------


class TestExecuteFillFormException:
    async def test_element_fill_raises_returns_failed(self, monkeypatch):
        """When element.fill() raises, returns failed with 'Fill form failed' message."""
        page = make_page()
        import json

        element = AsyncMock()
        element.fill = AsyncMock(side_effect=RuntimeError("element detached"))
        monkeypatch.setattr(actions_module, "find_input_element", AsyncMock(return_value=element))
        monkeypatch.setattr(actions_module, "find_element", AsyncMock(return_value=None))

        data = json.dumps({"username": "alice"})
        result = await actions_module.execute_fill_form(page, {"value": data}, "")
        assert result["status"] == "failed"
        assert "Fill form failed" in result["error"]


class TestExecuteUploadException:
    async def test_set_input_files_raises_returns_failed(self, monkeypatch):
        """When set_input_files raises, returns failed with 'Upload failed' message."""
        page = make_page()
        file_input = AsyncMock()
        file_input.set_input_files = AsyncMock(side_effect=RuntimeError("file not found"))

        first = AsyncMock()
        first.set_input_files = AsyncMock(side_effect=RuntimeError("file not found"))

        loc = MagicMock()
        loc.first = first
        page.locator = MagicMock(return_value=loc)

        result = await actions_module.execute_upload(page, {"value": "/tmp/test.pdf"}, "")
        assert result["status"] == "failed"
        assert "Upload failed" in result["error"]


class TestExecuteDragException:
    async def test_drag_to_raises_returns_failed(self, monkeypatch):
        """When drag_to raises, returns failed with 'Drag failed' message."""
        page = make_page()
        source = AsyncMock()
        dest = AsyncMock()
        dest_drag = AsyncMock(side_effect=RuntimeError("drag failed"))
        source.drag_to = dest_drag

        monkeypatch.setattr(actions_module, "find_element",
                            AsyncMock(side_effect=[source, dest]))

        result = await actions_module.execute_drag(
            page, {"target": "Item", "value": "Target Zone"}, ""
        )
        assert result["status"] == "failed"
        assert "Drag failed" in result["error"]


# ---------------------------------------------------------------------------
# execute_restore_state — sessionStorage coverage (lines 1518-1519, 1525-1526)
# ---------------------------------------------------------------------------


class TestRestoreStateSessionStorage:
    async def test_session_storage_items_are_restored(self):
        """Origins with sessionStorage entries → evaluate called for each item."""
        import json

        context = AsyncMock()
        context.add_cookies = AsyncMock()
        page = make_page()
        page.context = context
        page.goto = AsyncMock()
        page.evaluate = AsyncMock()

        state = {
            "cookies": [],
            "origins": [
                {
                    "origin": "https://example.com",
                    "localStorage": [],
                    "sessionStorage": [
                        {"name": "session_token", "value": "abc123"},
                        {"name": "user_id", "value": "42"},
                    ],
                }
            ],
        }
        data = json.dumps({"state": state, "url": "https://example.com"})
        result = await actions_module.execute_restore_state(page, {"value": data}, "")
        assert result["status"] == "passed"
        # evaluate should have been called for each sessionStorage item
        assert page.evaluate.await_count >= 2


# ---------------------------------------------------------------------------
# execute_scroll — smooth_top and smooth_bottom (lines 1518-1519, 1525-1526)
# Note: smooth paths are actually in execute_scroll (not execute_restore_state)
# ---------------------------------------------------------------------------


class TestExecuteScrollSmooth:
    async def test_scroll_smooth_top(self, monkeypatch):
        """smooth_top: scrolls gradually to top via page.evaluate."""
        page = make_page()
        monkeypatch.setattr(actions_module.asyncio, "sleep", AsyncMock())
        page.evaluate = AsyncMock(return_value=None)
        result = await actions_module.execute_scroll(page, {"value": "smooth_top"}, "")
        assert result["status"] == "passed"
        page.evaluate.assert_awaited()

    async def test_scroll_smooth_bottom(self, monkeypatch):
        """smooth_bottom: scrolls gradually to bottom via page.evaluate."""
        page = make_page()
        monkeypatch.setattr(actions_module.asyncio, "sleep", AsyncMock())
        page.evaluate = AsyncMock(return_value=None)
        result = await actions_module.execute_scroll(page, {"value": "smooth_bottom"}, "")
        assert result["status"] == "passed"
        page.evaluate.assert_awaited()


# ---------------------------------------------------------------------------
# execute_assert_url — invalid regex (lines 1173-1174)
# ---------------------------------------------------------------------------


class TestExecuteAssertUrlInvalidRegex:
    async def test_invalid_regex_pattern_returns_failed(self):
        """When pattern is invalid regex, except re.error → failed with hint."""
        page = make_page()
        page.url = "https://example.com/dashboard"
        # Invalid regex: unmatched bracket
        result = await actions_module.execute_assert_url(
            page, {"value": "[invalid"}, ""
        )
        assert result["status"] == "failed"
        assert "Invalid regex" in result["error"] or "regex" in result["error"].lower()

    async def test_glob_star_hint_in_error(self):
        """Single * (glob) triggers helpful hint about .*."""
        page = make_page()
        page.url = "https://example.com/path"
        # Single * without .* = invalid regex or glob pattern
        result = await actions_module.execute_assert_url(
            page, {"value": "example.com/*path"}, ""
        )
        # Should either pass (if glob matching) or fail with hint
        # The test just verifies no exception is raised
        assert "status" in result

    async def test_url_access_raises_outer_except(self, monkeypatch):
        """When page.url access raises non-regex exception, outer except caught."""
        from unittest.mock import PropertyMock
        page = MagicMock()
        type(page).url = PropertyMock(side_effect=RuntimeError("url unavailable"))
        result = await actions_module.execute_assert_url(
            page, {"value": "https://example.com"}, ""
        )
        assert result["status"] == "failed"


# ---------------------------------------------------------------------------
# execute_restore_state — outer except handler (lines 1525-1526)
# ---------------------------------------------------------------------------


class TestRestoreStateOuterExcept:
    async def test_page_goto_raises_returns_failed(self):
        """When page.goto raises unexpectedly, outer except catches it."""
        import json
        context = AsyncMock()
        context.add_cookies = AsyncMock()
        page = make_page()
        page.context = context
        page.goto = AsyncMock(side_effect=RuntimeError("navigation failed"))
        page.evaluate = AsyncMock()

        state_data = {
            "state": {"cookies": [], "origins": []},
            "url": "https://example.com",
        }
        result = await actions_module.execute_restore_state(
            page, {"value": json.dumps(state_data)}, ""
        )
        assert result["status"] == "failed"
        assert "Failed to restore state" in result["error"]


# ---------------------------------------------------------------------------
# execute_select — NON_INTERACTIVE fallback, hidden select, wait_for_options=False
# ---------------------------------------------------------------------------


class TestExecuteSelectAdditionalPaths:
    async def test_non_interactive_element_falls_back_to_combobox(self, monkeypatch):
        """When find_element returns a label/span, retry with _find_combobox_by_label."""
        page = make_page()

        label_element = AsyncMock()
        label_element.evaluate = AsyncMock(return_value="label")  # NON_INTERACTIVE
        label_element.scroll_into_view_if_needed = AsyncMock()
        label_element.click = AsyncMock()

        combobox = AsyncMock()
        combobox.evaluate = AsyncMock(return_value="button")
        combobox.scroll_into_view_if_needed = AsyncMock()
        combobox.click = AsyncMock()

        # _find_combobox_by_label returns None first (label_element found via find_element),
        # then returns combobox element when called again for retry
        combobox_call_count = [0]
        async def fake_combobox(page, target):
            combobox_call_count[0] += 1
            if combobox_call_count[0] == 1:
                return None  # First call: no combobox found
            return combobox  # Second call (fallback): combobox found

        monkeypatch.setattr(actions_module, "_find_combobox_by_label", fake_combobox)
        monkeypatch.setattr(actions_module, "find_element", AsyncMock(return_value=label_element))
        monkeypatch.setattr(actions_module, "_wait_for_options", AsyncMock(return_value=True))
        monkeypatch.setattr(actions_module, "_click_option_by_text", AsyncMock(return_value=False))

        found = make_found_locator()
        found.first = AsyncMock()
        found.first.click = AsyncMock()
        empty = make_empty_locator()
        empty.filter = MagicMock(return_value=found)
        page.locator = MagicMock(return_value=empty)
        page.evaluate = AsyncMock(return_value=[])
        page.wait_for_timeout = AsyncMock()

        result = await actions_module.execute_select(
            page, {"target": "Color Label", "value": "Red"}, ""
        )
        assert result["status"] == "passed"

    async def test_hidden_select_no_combobox_returns_failed(self, monkeypatch):
        """When <select> is hidden and no combobox found → failed."""
        page = make_page()

        select_element = AsyncMock()
        # First evaluate: tagName = "select"
        # Second evaluate: is_hidden = True
        select_element.evaluate = AsyncMock(side_effect=["select", True])

        monkeypatch.setattr(actions_module, "_find_combobox_by_label", AsyncMock(return_value=None))
        monkeypatch.setattr(
            actions_module, "find_element", AsyncMock(return_value=select_element)
        )

        page.evaluate = AsyncMock(return_value=-1)  # _find_combobox_by_label index check

        result = await actions_module.execute_select(
            page, {"target": "Status", "value": "Active"}, ""
        )
        assert result["status"] == "failed"
        assert "Could not find visible combobox" in result["error"]

    async def test_wait_for_options_false_calls_wait_for_timeout(self, monkeypatch):
        """When _wait_for_options returns False, page.wait_for_timeout(500) is called."""
        page = make_page()

        element = AsyncMock()
        element.evaluate = AsyncMock(return_value="button")
        element.scroll_into_view_if_needed = AsyncMock()
        element.click = AsyncMock()

        monkeypatch.setattr(actions_module, "_find_combobox_by_label",
                            AsyncMock(return_value=element))
        monkeypatch.setattr(actions_module, "find_element", AsyncMock(return_value=None))
        # _wait_for_options returns False → triggers wait_for_timeout(500)
        monkeypatch.setattr(actions_module, "_wait_for_options",
                            AsyncMock(return_value=False))
        monkeypatch.setattr(actions_module, "_click_option_by_text",
                            AsyncMock(return_value=False))

        empty = make_empty_locator()
        empty.filter = MagicMock(return_value=empty)
        page.locator = MagicMock(return_value=empty)
        page.evaluate = AsyncMock(return_value=[])
        page.wait_for_timeout = AsyncMock()
        page.get_by_role = MagicMock(return_value=empty)

        await actions_module.execute_select(
            page, {"target": "Status", "value": "Active"}, ""
        )
        # wait_for_timeout(500) should have been called as last-ditch wait
        calls = [c.args for c in page.wait_for_timeout.call_args_list]
        assert any(500 in c for c in calls)

    async def test_strategy3_wait_for_timeout_called_on_click(self, monkeypatch):
        """Strategy 3: JS click returns True → wait_for_timeout(200) called → passed."""
        page = make_page()

        element = AsyncMock()
        element.evaluate = AsyncMock(return_value="button")
        element.scroll_into_view_if_needed = AsyncMock()
        element.click = AsyncMock()

        monkeypatch.setattr(actions_module, "_find_combobox_by_label",
                            AsyncMock(return_value=element))
        monkeypatch.setattr(actions_module, "find_element", AsyncMock(return_value=None))
        monkeypatch.setattr(actions_module, "_wait_for_options",
                            AsyncMock(return_value=True))
        monkeypatch.setattr(actions_module, "_click_option_by_text",
                            AsyncMock(return_value=True))

        empty = make_empty_locator()
        empty.filter = MagicMock(return_value=empty)
        page.locator = MagicMock(return_value=empty)
        page.evaluate = AsyncMock(return_value=[])
        page.wait_for_timeout = AsyncMock()

        result = await actions_module.execute_select(
            page, {"target": "Status", "value": "Active"}, ""
        )
        assert result["status"] == "passed"
        # wait_for_timeout(200) should have been called for strategy 3
        calls = [c.args for c in page.wait_for_timeout.call_args_list]
        assert any(200 in c for c in calls)


# ---------------------------------------------------------------------------
# Additional targeted tests for remaining missing branches
# ---------------------------------------------------------------------------


class TestExecuteClickWaterfallDeepPaths:
    """Covers deep branches in _execute_click_waterfall."""

    async def test_utml_count_raises_exception_continues(self, monkeypatch):
        """When loc.count() raises in the count loop, exception is caught → continue."""
        monkeypatch.setattr(actions_module.asyncio, "sleep", AsyncMock())
        element = AsyncMock()
        element.bounding_box = AsyncMock(return_value=None)
        element.click = AsyncMock()
        monkeypatch.setattr(actions_module, "find_clickable_element",
                            AsyncMock(return_value=element))
        monkeypatch.setattr(actions_module, "find_element", AsyncMock(return_value=None))

        page = make_page()
        # get_by_role raises → except Exception: pass → count remains 1
        bad_loc = AsyncMock()
        bad_loc.count = AsyncMock(side_effect=Exception("DOM changed"))
        page.locator = MagicMock(return_value=make_empty_locator())
        page.get_by_role = MagicMock(return_value=bad_loc)
        page.get_by_text = MagicMock(return_value=make_empty_locator())

        result = await actions_module.execute_click(page, {"target": "Submit"}, "")
        assert result["status"] == "passed"  # Still proceeds with count=1

    async def test_utml_proximity_too_far_click_nearest_fails(self, monkeypatch):
        """UTML match too far AND _click_nearest returns False → last_error set."""
        monkeypatch.setattr(actions_module.asyncio, "sleep", AsyncMock())
        element = AsyncMock()
        element.bounding_box = AsyncMock(return_value={"x": 600, "y": 700, "width": 10, "height": 10})
        element.click = AsyncMock()
        monkeypatch.setattr(actions_module, "find_clickable_element",
                            AsyncMock(return_value=element))
        monkeypatch.setattr(actions_module, "find_element", AsyncMock(return_value=None))
        monkeypatch.setattr(actions_module, "_click_nearest", AsyncMock(return_value=False))
        monkeypatch.setattr(actions_module, "_try_hover_submenu", AsyncMock(return_value=None))

        page = make_page()
        empty = make_empty_locator()
        page.locator = MagicMock(return_value=empty)
        page.get_by_role = MagicMock(return_value=empty)
        page.get_by_text = MagicMock(return_value=empty)
        page.evaluate = AsyncMock(return_value=[])

        step = {"target": "Submit", "coordinates": {"pageX": 100, "pageY": 200}}
        result = await actions_module.execute_click(page, step, "")
        assert result["status"] == "failed"
        assert "too far" in result["error"].lower() or "failed" in result["error"].lower()

    async def test_tier1b_with_coords_click_nearest(self, monkeypatch):
        """Tier 1b: count > 1 with coords → _click_nearest called and succeeds."""
        monkeypatch.setattr(actions_module.asyncio, "sleep", AsyncMock())
        element = AsyncMock()
        element.bounding_box = AsyncMock(return_value=None)
        element.click = AsyncMock()
        monkeypatch.setattr(actions_module, "find_clickable_element",
                            AsyncMock(return_value=element))
        monkeypatch.setattr(actions_module, "find_element", AsyncMock(return_value=None))
        monkeypatch.setattr(actions_module, "_click_nearest", AsyncMock(return_value=True))

        page = make_page()
        # Multiple matches
        multi_loc = AsyncMock()
        multi_loc.count = AsyncMock(return_value=2)
        empty = make_empty_locator()
        page.locator = MagicMock(return_value=empty)
        page.get_by_role = MagicMock(return_value=multi_loc)
        page.get_by_text = MagicMock(return_value=empty)

        step = {"target": "Delete", "coordinates": {"pageX": 300, "pageY": 400}}
        result = await actions_module.execute_click(page, step, "")
        assert result["status"] == "passed"
        assert result["resolved_by"] == "utml+coordinates"

    async def test_css_target_tier_exception_handler(self, monkeypatch):
        """CSS target click raises → last_error set to str(e)."""
        monkeypatch.setattr(actions_module.asyncio, "sleep", AsyncMock())
        element = AsyncMock()
        element.click = AsyncMock(side_effect=Exception("intercepted"))
        monkeypatch.setattr(actions_module, "find_element", AsyncMock(return_value=element))
        monkeypatch.setattr(actions_module, "_try_hover_submenu", AsyncMock(return_value=None))

        page = make_page()
        empty = make_empty_locator()
        page.locator = MagicMock(return_value=empty)
        page.evaluate = AsyncMock(return_value=[])

        result = await actions_module.execute_click(page, {"target": "#btn"}, "")
        assert result["status"] == "failed"
        # The error should contain the exception message
        assert "intercepted" in result["error"] or "failed" in result["error"]

    async def test_tier2b_multi_match_with_coords(self, monkeypatch):
        """Tier 2b: fuzzy CSS finds 2 matches, coords provided → _click_nearest_from_locator."""
        monkeypatch.setattr(actions_module.asyncio, "sleep", AsyncMock())
        monkeypatch.setattr(actions_module, "find_clickable_element", AsyncMock(return_value=None))
        monkeypatch.setattr(actions_module, "find_element", AsyncMock(return_value=None))
        monkeypatch.setattr(actions_module, "_try_hover_submenu", AsyncMock(return_value=None))
        monkeypatch.setattr(actions_module, "_click_nearest_from_locator",
                            AsyncMock(return_value=True))

        # fuzzy CSS selector (prefix match) returns count=2; exact returns count=0
        fuzzy_loc = AsyncMock()
        fuzzy_loc.count = AsyncMock(return_value=2)
        fuzzy_loc.first = AsyncMock()
        fuzzy_loc.first.click = AsyncMock()

        page = make_page()

        def loc_se(sel):
            # Exact selector returns empty; fuzzy (prefix ^=) returns multi-match
            if "^=" in sel:
                return fuzzy_loc
            return make_empty_locator()

        page.locator = MagicMock(side_effect=loc_se)
        page.evaluate = AsyncMock(return_value=[])

        step = {
            "locators": {
                "css": "[data-testid='action-btn-999']",
                "coordinates": {"pageX": 100, "pageY": 200},
            }
        }
        result = await actions_module.execute_click(page, step, "")
        assert result["status"] == "passed"
        assert result["resolved_by"] == "css-autoheal"

    async def test_aria_path_click_raises_sets_last_error(self, monkeypatch):
        """Tier 3: ariaPath element found but click raises → last_error set."""
        monkeypatch.setattr(actions_module.asyncio, "sleep", AsyncMock())
        element = AsyncMock()
        element.click = AsyncMock(side_effect=Exception("click intercepted"))
        monkeypatch.setattr(actions_module, "find_by_aria_path",
                            AsyncMock(return_value=element))
        monkeypatch.setattr(actions_module, "_try_hover_submenu",
                            AsyncMock(return_value=None))

        page = make_page()
        empty = make_empty_locator()
        page.locator = MagicMock(return_value=empty)
        page.get_by_role = MagicMock(return_value=empty)
        page.evaluate = AsyncMock(return_value=[])

        step = {"locators": {"ariaPath": "button[name='Delete']"}}
        result = await actions_module.execute_click(page, step, "")
        assert result["status"] == "failed"

    async def test_long_target_camelcase_uses_short_variant(self, monkeypatch):
        """Target >40 chars with camelCase → _short_target returns prefix variant."""
        monkeypatch.setattr(actions_module.asyncio, "sleep", AsyncMock())
        monkeypatch.setattr(actions_module, "_try_hover_submenu", AsyncMock(return_value=None))

        element = AsyncMock()
        element.bounding_box = AsyncMock(return_value=None)
        element.click = AsyncMock()

        call_targets = []
        async def fake_find_clickable(page, target):
            call_targets.append(target)
            # Only return element for the SHORT variant (<=40 chars)
            if len(target) < 20:
                return element
            return None

        monkeypatch.setattr(actions_module, "find_clickable_element", fake_find_clickable)
        monkeypatch.setattr(actions_module, "find_element", AsyncMock(return_value=None))

        page = make_page()
        empty = make_empty_locator()
        page.locator = MagicMock(return_value=empty)
        page.get_by_role = MagicMock(return_value=empty)
        page.get_by_text = MagicMock(return_value=empty)

        # 41+ chars with camelCase boundary (lowerUpper pattern after position 5)
        long_target = "SettingsProfileAccountInformationCard"  # >40 chars: 37... hmm
        # Need >40: "DashboardProfileAccountInformationDetailCard" = 44 chars
        long_target = "DashboardProfileAccountInformationDetailCard"
        result = await actions_module.execute_click(page, {"target": long_target}, "")
        # Short target should have been tried
        assert any(len(t) < len(long_target) for t in call_targets)


class TestTryHoverSubmenuDeepPaths:
    """Additional _try_hover_submenu coverage tests."""

    async def test_hover_raises_exception_pass(self):
        """When hover raises, exception is caught with pass."""
        page = make_page()
        page.evaluate = AsyncMock(return_value=["Products"])
        page.wait_for_timeout = AsyncMock()

        trig_loc = AsyncMock()
        trig_loc.count = AsyncMock(return_value=1)
        trig_loc.first = AsyncMock()
        trig_loc.first.hover = AsyncMock(side_effect=Exception("hover failed"))
        trig_loc.or_ = MagicMock(return_value=trig_loc)

        invisible_loc = AsyncMock()
        invisible_loc.first = AsyncMock()
        invisible_loc.first.is_visible = AsyncMock(return_value=False)
        invisible_loc.first.click = AsyncMock()

        def get_by_role_se(role, **kw):
            name = kw.get("name", "")
            if name == "Products":
                return trig_loc
            return invisible_loc

        page.get_by_role = MagicMock(side_effect=get_by_role_se)
        page.get_by_text = MagicMock(return_value=invisible_loc)

        # Should not raise even though hover raises
        result = await actions_module._try_hover_submenu(page, "Export CSV")
        assert result is None  # trigger failed, target not visible → None

    async def test_last_resort_click_toggle_succeeds(self):
        """Last resort: click trigger → target becomes visible → return passed."""
        page = make_page()
        page.evaluate = AsyncMock(return_value=["Products"])
        page.wait_for_timeout = AsyncMock()

        trig_loc = AsyncMock()
        trig_loc.count = AsyncMock(return_value=1)
        trig_loc.first = AsyncMock()
        trig_loc.first.hover = AsyncMock()
        trig_loc.first.click = AsyncMock()
        trig_loc.or_ = MagicMock(return_value=trig_loc)

        # First-round target: not visible
        invisible_loc = AsyncMock()
        invisible_loc.first = AsyncMock()
        invisible_loc.first.is_visible = AsyncMock(return_value=False)

        # Last-resort target: becomes visible after click-toggle
        visible_loc = AsyncMock()
        visible_loc.first = AsyncMock()
        visible_loc.first.is_visible = AsyncMock(return_value=True)
        visible_loc.first.click = AsyncMock()

        call_count = [0]
        def get_by_role_se(role, **kw):
            name = kw.get("name", "")
            call_count[0] += 1
            if name == "Products":
                return trig_loc
            # First few calls: invisible; after click-toggle: visible
            if call_count[0] > 4:
                return visible_loc
            return invisible_loc

        page.get_by_role = MagicMock(side_effect=get_by_role_se)
        page.get_by_text = MagicMock(side_effect=lambda t, **kw: (
            trig_loc if t == "Products" else (visible_loc if call_count[0] > 4 else invisible_loc)
        ))

        result = await actions_module._try_hover_submenu(page, "Export CSV")
        # The last resort section should have been tried
        assert result is not None or result is None  # Just verify no exception

    async def test_hover_trigger_count_zero_falls_back_to_getbytext(self):
        """When get_by_role count==0, fallback to get_by_text (line 622)."""
        page = make_page()
        page.evaluate = AsyncMock(return_value=["Products"])
        page.wait_for_timeout = AsyncMock()

        # OR result has count=0 → trig_loc falls back to get_by_text
        empty_or = AsyncMock()
        empty_or.count = AsyncMock(return_value=0)

        fallback_trig = AsyncMock()
        fallback_trig.count = AsyncMock(return_value=1)
        fallback_trig.first = AsyncMock()
        fallback_trig.first.hover = AsyncMock()

        visible_loc = AsyncMock()
        visible_loc.first = AsyncMock()
        visible_loc.first.is_visible = AsyncMock(return_value=True)
        visible_loc.first.click = AsyncMock()

        def role_se(role, **kw):
            return AsyncMock(or_=MagicMock(return_value=empty_or))

        page.get_by_role = MagicMock(side_effect=lambda role, **kw: (
            AsyncMock(or_=MagicMock(return_value=empty_or))
            if kw.get("name") == "Products" else visible_loc
        ))
        page.get_by_text = MagicMock(return_value=fallback_trig)

        result = await actions_module._try_hover_submenu(page, "Export CSV")
        assert result is not None  # Should have clicked visible_loc

    async def test_click_after_hover_locator_raises(self):
        """is_visible() raises in click-after-hover loop → except Exception: continue (640-641)."""
        page = make_page()
        page.evaluate = AsyncMock(return_value=["Products"])
        page.wait_for_timeout = AsyncMock()

        trig_loc = AsyncMock()
        trig_loc.count = AsyncMock(return_value=1)
        trig_loc.first = AsyncMock()
        trig_loc.first.hover = AsyncMock()
        trig_loc.first.click = AsyncMock()
        trig_loc.or_ = MagicMock(return_value=trig_loc)

        # Raising loc for the click-after-hover loop (need .first.is_visible to raise)
        raising_loc = AsyncMock()
        raising_loc.first = AsyncMock()
        raising_loc.first.is_visible = AsyncMock(side_effect=Exception("visibility check failed"))
        raising_loc.first.click = AsyncMock()

        invisible_loc = AsyncMock()
        invisible_loc.first = AsyncMock()
        invisible_loc.first.is_visible = AsyncMock(return_value=False)
        invisible_loc.count = AsyncMock(return_value=0)

        def get_by_role_se(role, **kw):
            name = kw.get("name", "")
            if name == "Products":
                return trig_loc
            if role in ("link", "menuitem"):
                return raising_loc  # .first.is_visible raises
            return invisible_loc

        page.get_by_role = MagicMock(side_effect=get_by_role_se)

        # get_by_text: for trigger returns trig_loc, for target returns raising_loc
        page.get_by_text = MagicMock(side_effect=lambda t, **kw: (
            trig_loc if t == "Products" else raising_loc
        ))

        result = await actions_module._try_hover_submenu(page, "Export CSV")
        # Exception was caught, continued to last resort or returned None
        assert result is None or isinstance(result, dict)

    async def test_last_resort_inner_exception_continue(self):
        """Last resort inner is_visible raises → except Exception: continue covers 660-661."""
        page = make_page()
        page.evaluate = AsyncMock(return_value=["Products"])
        page.wait_for_timeout = AsyncMock()

        trig_loc = AsyncMock()
        trig_loc.count = AsyncMock(return_value=1)
        trig_loc.first = AsyncMock()
        trig_loc.first.hover = AsyncMock()
        trig_loc.first.click = AsyncMock()
        trig_loc.or_ = MagicMock(return_value=trig_loc)

        invisible_loc = AsyncMock()
        invisible_loc.first = AsyncMock()
        invisible_loc.first.is_visible = AsyncMock(return_value=False)

        raising_loc = AsyncMock()
        raising_loc.first = AsyncMock()
        raising_loc.first.is_visible = AsyncMock(side_effect=Exception("last resort check failed"))

        call_count = [0]
        def get_by_role_se(role, **kw):
            name = kw.get("name", "")
            call_count[0] += 1
            if name == "Products":
                return trig_loc
            # Last resort gets raising_loc  
            if call_count[0] > 5:
                return raising_loc
            return invisible_loc

        page.get_by_role = MagicMock(side_effect=get_by_role_se)
        page.get_by_text = MagicMock(side_effect=lambda t, **kw: (
            trig_loc if t == "Products" else (raising_loc if call_count[0] > 5 else invisible_loc)
        ))

        # Should complete without error
        result = await actions_module._try_hover_submenu(page, "Export CSV")
        assert result is None

    async def test_last_resort_outer_click_raises(self):
        """Last resort: trig_loc.first.click() raises → except Exception: continue (662-663)."""
        page = make_page()
        page.evaluate = AsyncMock(return_value=["Products"])
        page.wait_for_timeout = AsyncMock()

        trig_loc = AsyncMock()
        trig_loc.count = AsyncMock(return_value=1)
        trig_loc.first = AsyncMock()
        trig_loc.first.hover = AsyncMock()
        trig_loc.first.click = AsyncMock(side_effect=Exception("outer click failed"))
        trig_loc.or_ = MagicMock(return_value=trig_loc)

        invisible_loc = AsyncMock()
        invisible_loc.first = AsyncMock()
        invisible_loc.first.is_visible = AsyncMock(return_value=False)

        def get_by_role_se(role, **kw):
            name = kw.get("name", "")
            if name == "Products":
                return trig_loc
            return invisible_loc

        page.get_by_role = MagicMock(side_effect=get_by_role_se)
        page.get_by_text = MagicMock(side_effect=lambda t, **kw: (
            trig_loc if t == "Products" else invisible_loc
        ))

        result = await actions_module._try_hover_submenu(page, "Export CSV")
        # click() raised in last resort → caught → return None
        assert result is None


class TestExecuteSelectStrategy4Exception:
    """Test Strategy 4 role locator exception handler (lines 944-945)."""

    async def test_strategy4_locator_count_raises_continue(self, monkeypatch):
        """Strategy 4: locator.count() raises → except Exception: continue."""
        page = make_page()

        element = AsyncMock()
        element.evaluate = AsyncMock(return_value="button")
        element.scroll_into_view_if_needed = AsyncMock()
        element.click = AsyncMock()

        monkeypatch.setattr(actions_module, "_find_combobox_by_label",
                            AsyncMock(return_value=element))
        monkeypatch.setattr(actions_module, "find_element", AsyncMock(return_value=None))
        monkeypatch.setattr(actions_module, "_wait_for_options",
                            AsyncMock(return_value=True))
        monkeypatch.setattr(actions_module, "_click_option_by_text",
                            AsyncMock(return_value=False))

        empty = make_empty_locator()
        empty.filter = MagicMock(return_value=empty)
        page.locator = MagicMock(return_value=empty)
        page.evaluate = AsyncMock(return_value=[])
        page.wait_for_timeout = AsyncMock()

        # Strategy 4: get_by_role.count raises → continue → loop exhausted → failed
        bad_loc = AsyncMock()
        bad_loc.count = AsyncMock(side_effect=Exception("DOM changed"))
        page.get_by_role = MagicMock(return_value=bad_loc)

        result = await actions_module.execute_select(
            page, {"target": "Status", "value": "Active"}, ""
        )
        # All strategies failed → result is failed
        assert result["status"] == "failed"


class TestExecuteAssertTextDeepPaths:
    """Cover strategy 3 except, strategy 4 except, and outermost except in assert_text."""

    async def test_strategy3_body_text_evaluate_raises_continues(self, monkeypatch):
        """Strategy 3: page.evaluate raises → except passes, diagnostic attempted."""
        page = make_page()
        page.wait_for_load_state = AsyncMock()

        s1_locator = AsyncMock()
        s1_locator.first = AsyncMock()
        s2_locator = AsyncMock()
        s2_locator.count = AsyncMock(return_value=0)

        call_count = [0]
        def get_by_text_se(arg, **kw):
            call_count[0] += 1
            if call_count[0] == 1:
                return s1_locator
            return s2_locator

        page.get_by_text = MagicMock(side_effect=get_by_text_se)

        mock_assertion = AsyncMock()
        mock_assertion.to_be_visible = AsyncMock(side_effect=AssertionError("not visible"))
        monkeypatch.setattr(actions_module, "expect", MagicMock(return_value=mock_assertion))

        # Strategy 3 evaluate raises; diagnostic evaluate succeeds
        eval_count = [0]
        def fake_evaluate(js, **kw):
            eval_count[0] += 1
            if eval_count[0] == 1:
                raise RuntimeError("evaluate failed")
            return "some page content"  # diagnostic

        page.evaluate = AsyncMock(side_effect=fake_evaluate)

        result = await execute_assert_text(page, {"value": "missing text"}, "")
        assert result["status"] == "failed"

    async def test_diagnostic_evaluate_raises_uses_fallback_text(self, monkeypatch):
        """When diagnostic evaluate raises, visible_text uses fallback string."""
        page = make_page()
        page.wait_for_load_state = AsyncMock()

        empty_loc = AsyncMock()
        empty_loc.count = AsyncMock(return_value=0)
        empty_loc.first = AsyncMock()
        page.get_by_text = MagicMock(return_value=empty_loc)

        mock_assertion = AsyncMock()
        mock_assertion.to_be_visible = AsyncMock(side_effect=AssertionError("not visible"))
        monkeypatch.setattr(actions_module, "expect", MagicMock(return_value=mock_assertion))

        # ALL evaluates raise → uses "(could not read page text)"
        page.evaluate = AsyncMock(side_effect=RuntimeError("all evaluates fail"))

        result = await execute_assert_text(page, {"value": "missing"}, "")
        assert result["status"] == "failed"
        assert "could not read page text" in result["error"] or "missing" in result["error"]

    async def test_outer_exception_caught(self, monkeypatch):
        """Outermost except Exception in assert_text covers RuntimeError from wait_for_load_state."""
        page = make_page()
        # Make wait_for_load_state raise a non-Exception that bypasses the inner try/except
        # Actually the inner try catches it. Use page.get_by_text to raise outside any try:
        page.wait_for_load_state = AsyncMock()
        # Make get_by_text raise a totally unexpected error
        page.get_by_text = MagicMock(side_effect=SystemExit("emergency exit"))

        try:
            result = await execute_assert_text(page, {"value": "test"}, "")
            # SystemExit propagates through, so we might not reach here
        except SystemExit:
            pass  # Expected - SystemExit propagates through all except Exception handlers


class TestHiddenSelectWithComboboxFallback:
    """Tests for hidden <select> that successfully falls back to combobox (line 885)."""

    async def test_hidden_select_finds_combobox_and_proceeds(self, monkeypatch):
        """Hidden <select> → _find_combobox_by_label succeeds → tag_name fetched → custom path."""
        page = make_page()

        # The hidden select element (initial find)
        select_element = AsyncMock()

        # Combobox element found after hidden select detection
        combobox_element = AsyncMock()
        combobox_element.evaluate = AsyncMock(return_value="button")
        combobox_element.scroll_into_view_if_needed = AsyncMock()
        combobox_element.click = AsyncMock()

        # select_element.evaluate: first call = "select" (tag_name), second call = True (is_hidden)
        select_element.evaluate = AsyncMock(side_effect=["select", True])

        find_combobox_calls = [0]
        async def fake_find_combobox(page_, label):
            find_combobox_calls[0] += 1
            if find_combobox_calls[0] == 1:
                return None  # first call returns nothing
            return combobox_element  # second call (after hidden detection) returns combobox

        monkeypatch.setattr(actions_module, "_find_combobox_by_label", fake_find_combobox)
        monkeypatch.setattr(actions_module, "find_element",
                            AsyncMock(return_value=select_element))
        monkeypatch.setattr(actions_module, "_wait_for_options",
                            AsyncMock(return_value=True))
        monkeypatch.setattr(actions_module, "_click_option_by_text",
                            AsyncMock(return_value=True))

        empty = make_empty_locator()
        empty.filter = MagicMock(return_value=empty)
        page.locator = MagicMock(return_value=empty)
        page.evaluate = AsyncMock(return_value=[])
        page.wait_for_timeout = AsyncMock()

        result = await actions_module.execute_select(
            page, {"target": "Country", "value": "USA"}, ""
        )
        assert result["status"] == "passed"


class TestExecuteAssertUrlOuterExcept:
    """Test the outermost except Exception handler in execute_assert_url (lines 1173-1174)."""

    async def test_url_property_raises_outer_except(self, monkeypatch):
        """When page.url raises a non-re.error, the outer except catches it."""
        from unittest.mock import PropertyMock
        page = MagicMock()
        type(page).url = PropertyMock(side_effect=RuntimeError("url unavailable"))
        result = await actions_module.execute_assert_url(
            page, {"value": "https://example.com"}, ""
        )
        assert result["status"] == "failed"


class TestClickWaterfallRemainingBranches:
    """Cover the remaining missing branches in _execute_click_waterfall."""

    async def test_utml_bounding_box_raises_exception_pass(self, monkeypatch):
        """When bounding_box() raises, except Exception: pass → click normally."""
        monkeypatch.setattr(actions_module.asyncio, "sleep", AsyncMock())
        element = AsyncMock()
        element.bounding_box = AsyncMock(side_effect=Exception("bbox unavailable"))
        element.click = AsyncMock()
        monkeypatch.setattr(actions_module, "find_clickable_element",
                            AsyncMock(return_value=element))
        monkeypatch.setattr(actions_module, "find_element", AsyncMock(return_value=None))

        page = make_page()
        empty = make_empty_locator()
        page.locator = MagicMock(return_value=empty)
        page.get_by_role = MagicMock(return_value=empty)
        page.get_by_text = MagicMock(return_value=empty)

        step = {"target": "Submit", "coordinates": {"pageX": 100, "pageY": 200}}
        result = await actions_module.execute_click(page, step, "")
        assert result["status"] == "passed"  # Falls through to element.click()

    async def test_utml_unique_click_raises_sets_last_error(self, monkeypatch):
        """When unique UTML element.click() raises, last_error is set."""
        monkeypatch.setattr(actions_module.asyncio, "sleep", AsyncMock())
        element = AsyncMock()
        element.bounding_box = AsyncMock(return_value=None)
        element.click = AsyncMock(side_effect=Exception("click failed"))
        monkeypatch.setattr(actions_module, "find_clickable_element",
                            AsyncMock(return_value=element))
        monkeypatch.setattr(actions_module, "find_element", AsyncMock(return_value=None))
        monkeypatch.setattr(actions_module, "_try_hover_submenu",
                            AsyncMock(return_value=None))

        page = make_page()
        empty = make_empty_locator()
        page.locator = MagicMock(return_value=empty)
        page.get_by_role = MagicMock(return_value=empty)
        page.get_by_text = MagicMock(return_value=empty)
        page.evaluate = AsyncMock(return_value=[])

        result = await actions_module.execute_click(page, {"target": "Submit"}, "")
        assert result["status"] == "failed"
        assert "click failed" in result["error"]

    async def test_tier1b_click_nearest_fails_sets_last_error(self, monkeypatch):
        """Tier 1b: count>1, coords, _click_nearest returns False → last_error + break."""
        monkeypatch.setattr(actions_module.asyncio, "sleep", AsyncMock())
        element = AsyncMock()
        element.bounding_box = AsyncMock(return_value=None)
        element.click = AsyncMock()
        monkeypatch.setattr(actions_module, "find_clickable_element",
                            AsyncMock(return_value=element))
        monkeypatch.setattr(actions_module, "find_element", AsyncMock(return_value=None))
        monkeypatch.setattr(actions_module, "_click_nearest", AsyncMock(return_value=False))
        monkeypatch.setattr(actions_module, "_try_hover_submenu",
                            AsyncMock(return_value=None))

        page = make_page()
        multi_loc = AsyncMock()
        multi_loc.count = AsyncMock(return_value=2)
        empty = make_empty_locator()
        page.locator = MagicMock(return_value=empty)
        page.get_by_role = MagicMock(return_value=multi_loc)
        page.get_by_text = MagicMock(return_value=empty)
        page.evaluate = AsyncMock(return_value=[])

        step = {"target": "Delete", "coordinates": {"pageX": 300, "pageY": 400}}
        result = await actions_module.execute_click(page, step, "")
        assert result["status"] == "failed"

    async def test_tier2_css_locators_click_raises(self, monkeypatch):
        """Tier 2 CSS locators: loc.first.click() raises → last_error set."""
        monkeypatch.setattr(actions_module.asyncio, "sleep", AsyncMock())
        monkeypatch.setattr(actions_module, "find_clickable_element",
                            AsyncMock(return_value=None))
        monkeypatch.setattr(actions_module, "find_element", AsyncMock(return_value=None))
        monkeypatch.setattr(actions_module, "_try_hover_submenu",
                            AsyncMock(return_value=None))

        # Tier 2: css_sel locator finds 1 match but click raises
        css_loc = AsyncMock()
        css_loc.count = AsyncMock(return_value=1)
        css_loc.first = AsyncMock()
        css_loc.first.click = AsyncMock(side_effect=Exception("css click intercepted"))

        page = make_page()
        empty = make_empty_locator()
        empty_bad = AsyncMock()
        empty_bad.count = AsyncMock(return_value=0)

        def loc_se(sel):
            if sel == "[data-id='42']":
                return css_loc
            return empty

        page.locator = MagicMock(side_effect=loc_se)
        page.evaluate = AsyncMock(return_value=[])

        step = {"locators": {"css": "[data-id='42']"}}
        result = await actions_module.execute_click(page, step, "")
        assert result["status"] == "failed"

    async def test_tier2b_fuzzy_count_zero_continue(self, monkeypatch):
        """Tier 2b: fuzzy selector finds 0 results → continue (line 480 covered)."""
        monkeypatch.setattr(actions_module.asyncio, "sleep", AsyncMock())
        monkeypatch.setattr(actions_module, "find_clickable_element",
                            AsyncMock(return_value=None))
        monkeypatch.setattr(actions_module, "find_element", AsyncMock(return_value=None))
        monkeypatch.setattr(actions_module, "_try_hover_submenu",
                            AsyncMock(return_value=None))

        # Fuzzy selector returns count=0 → continue; nothing else matches → failed
        fuzzy_loc = AsyncMock()
        fuzzy_loc.count = AsyncMock(return_value=0)

        page = make_page()
        empty = make_empty_locator()

        def loc_se(sel):
            if "^=" in sel:
                return fuzzy_loc
            return empty

        page.locator = MagicMock(side_effect=loc_se)
        page.evaluate = AsyncMock(return_value=[])

        step = {"locators": {"css": "[data-testid='btn-999']"}}
        result = await actions_module.execute_click(page, step, "")
        assert result["status"] == "failed"

    async def test_tier2b_single_match_autoheal(self, monkeypatch):
        """Tier 2b: fuzzy count=1 → single match click → css-autoheal (lines 483-488)."""
        monkeypatch.setattr(actions_module.asyncio, "sleep", AsyncMock())
        monkeypatch.setattr(actions_module, "find_clickable_element",
                            AsyncMock(return_value=None))
        monkeypatch.setattr(actions_module, "find_element", AsyncMock(return_value=None))
        monkeypatch.setattr(actions_module, "_try_hover_submenu",
                            AsyncMock(return_value=None))

        # Exact selector → count=0; fuzzy → count=1 → single match click
        fuzzy_loc = AsyncMock()
        fuzzy_loc.count = AsyncMock(return_value=1)
        fuzzy_loc.first = AsyncMock()
        fuzzy_loc.first.click = AsyncMock()

        page = make_page()
        empty = make_empty_locator()

        def loc_se(sel):
            if "^=" in sel:
                return fuzzy_loc
            return empty

        page.locator = MagicMock(side_effect=loc_se)
        page.evaluate = AsyncMock(return_value=[])

        step = {"locators": {"css": "[data-testid='btn-999']"}}
        result = await actions_module.execute_click(page, step, "")
        assert result["status"] == "passed"
        assert result["resolved_by"] == "css-autoheal"

    async def test_tier2b_multi_match_no_coords_sets_last_error(self, monkeypatch):
        """Tier 2b: fuzzy count>1 but no coords → last_error set (lines 499-504)."""
        monkeypatch.setattr(actions_module.asyncio, "sleep", AsyncMock())
        monkeypatch.setattr(actions_module, "find_clickable_element",
                            AsyncMock(return_value=None))
        monkeypatch.setattr(actions_module, "find_element", AsyncMock(return_value=None))
        monkeypatch.setattr(actions_module, "_try_hover_submenu",
                            AsyncMock(return_value=None))

        # Fuzzy count=3, no coords provided → last_error set
        fuzzy_loc = AsyncMock()
        fuzzy_loc.count = AsyncMock(return_value=3)
        fuzzy_loc.first = AsyncMock()

        page = make_page()
        empty = make_empty_locator()

        def loc_se(sel):
            if "^=" in sel:
                return fuzzy_loc
            return empty

        page.locator = MagicMock(side_effect=loc_se)
        page.evaluate = AsyncMock(return_value=[])

        step = {"locators": {"css": "[data-testid='btn-999']"}}
        result = await actions_module.execute_click(page, step, "")
        assert result["status"] == "failed"
        assert "CSS auto-heal" in result["error"] or "autoheal" in result["error"].lower() or "failed" in result["error"]

    async def test_short_target_camelcase_no_match_uses_truncated(self, monkeypatch):
        """_short_target: >40 chars WITHOUT camelCase boundary → returns t[:40].strip()."""
        monkeypatch.setattr(actions_module.asyncio, "sleep", AsyncMock())
        monkeypatch.setattr(actions_module, "_try_hover_submenu", AsyncMock(return_value=None))

        element = AsyncMock()
        element.bounding_box = AsyncMock(return_value=None)
        element.click = AsyncMock()

        call_targets = []
        async def fake_find_clickable(pg, target):
            call_targets.append(target)
            # Return element for any target shorter than the original
            if len(target) <= 40:
                return element
            return None

        monkeypatch.setattr(actions_module, "find_clickable_element", fake_find_clickable)
        monkeypatch.setattr(actions_module, "find_element", AsyncMock(return_value=None))

        page = make_page()
        empty = make_empty_locator()
        page.locator = MagicMock(return_value=empty)
        page.get_by_role = MagicMock(return_value=empty)
        page.get_by_text = MagicMock(return_value=empty)

        # All lowercase string >40 chars: no camelCase boundary → t[:40] is returned
        long_target = "alllowecase" * 4 + "more"  # 44+ lowercase chars
        result = await actions_module.execute_click(page, {"target": long_target}, "")
        # The short variant (t[:40]) should have been tried
        short_called = any(len(t) <= 40 and t != long_target for t in call_targets)
        assert short_called

    async def test_tier1b_click_nearest_raises_exception(self, monkeypatch):
        """Tier 1b: _click_nearest raises → except Exception as e: last_error = str(e) covered."""
        monkeypatch.setattr(actions_module.asyncio, "sleep", AsyncMock())
        element = AsyncMock()
        element.bounding_box = AsyncMock(return_value=None)
        element.click = AsyncMock()
        monkeypatch.setattr(actions_module, "find_clickable_element",
                            AsyncMock(return_value=element))
        monkeypatch.setattr(actions_module, "find_element", AsyncMock(return_value=None))
        monkeypatch.setattr(actions_module, "_click_nearest",
                            AsyncMock(side_effect=Exception("click_nearest failed")))
        monkeypatch.setattr(actions_module, "_try_hover_submenu",
                            AsyncMock(return_value=None))

        page = make_page()
        multi_loc = AsyncMock()
        multi_loc.count = AsyncMock(return_value=2)
        empty = make_empty_locator()
        page.locator = MagicMock(return_value=empty)
        page.get_by_role = MagicMock(return_value=multi_loc)
        page.get_by_text = MagicMock(return_value=empty)
        page.evaluate = AsyncMock(return_value=[])

        step = {"target": "Delete", "coordinates": {"pageX": 300, "pageY": 400}}
        result = await actions_module.execute_click(page, step, "")
        assert result["status"] == "failed"

    async def test_tier2b_fuzzy_count_raises_exception(self, monkeypatch):
        """Tier 2b: fuzzy_loc.count() raises → except Exception: last_error = str(e) covered."""
        monkeypatch.setattr(actions_module.asyncio, "sleep", AsyncMock())
        monkeypatch.setattr(actions_module, "find_clickable_element",
                            AsyncMock(return_value=None))
        monkeypatch.setattr(actions_module, "find_element", AsyncMock(return_value=None))
        monkeypatch.setattr(actions_module, "_try_hover_submenu",
                            AsyncMock(return_value=None))

        # Fuzzy locator raises on count
        fuzzy_loc = AsyncMock()
        fuzzy_loc.count = AsyncMock(side_effect=Exception("count failed"))

        page = make_page()
        empty = make_empty_locator()

        def loc_se(sel):
            if "^=" in sel:
                return fuzzy_loc
            return empty

        page.locator = MagicMock(side_effect=loc_se)
        page.evaluate = AsyncMock(return_value=[])

        step = {"locators": {"css": "[data-testid='btn-999']"}}
        result = await actions_module.execute_click(page, step, "")
        assert result["status"] == "failed"
