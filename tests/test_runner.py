"""Tests for the test runner (execute_test, get_retry_config) using mocked Page."""

import os
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest

import executor.runner as runner_module
from executor.runner import execute_test, execute_single_step, get_retry_config


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------



def make_mock_manager(page):
    """BrowserManager mock whose new_page() async-CM yields *page*."""
    manager = MagicMock()

    @asynccontextmanager
    async def fake_new_page(browser_id=None):
        yield page

    manager.new_page = fake_new_page
    return manager


def make_mock_page():
    page = AsyncMock()
    page.url = "https://example.com"
    page.screenshot = AsyncMock(return_value=b"PNG")
    return page


# ---------------------------------------------------------------------------
# get_retry_config
# ---------------------------------------------------------------------------


class TestGetRetryConfig:
    def test_defaults_for_click(self):
        retries, delay = get_retry_config("click", {})
        assert retries == 2

    def test_defaults_for_assert_text(self):
        """assert_text should have 0 retries by default."""
        retries, delay = get_retry_config("assert_text", {})
        assert retries == 0

    def test_defaults_for_unknown_action(self):
        retries, delay = get_retry_config("unknown_action", {})
        assert retries == 0

    def test_options_int_overrides_all_actions(self):
        retries, delay = get_retry_config("click", {"step_retries": 5})
        assert retries == 5

    def test_options_dict_overrides_specific_action(self):
        retries, delay = get_retry_config("click", {"step_retries": {"click": 7, "type": 3}})
        assert retries == 7

    def test_options_dict_falls_back_to_default_for_missing_action(self):
        retries, delay = get_retry_config("navigate", {"step_retries": {"click": 7}})
        assert retries == 2  # navigate default

    def test_env_variable_override(self, monkeypatch):
        monkeypatch.setenv("STEP_RETRY_NAVIGATE", "4")
        retries, delay = get_retry_config("navigate", {})
        assert retries == 4

    def test_custom_retry_delay_from_options(self):
        _, delay = get_retry_config("click", {"step_retry_delay_ms": 500})
        assert delay == 500

    def test_default_retry_delay(self):
        _, delay = get_retry_config("click", {})
        # Default from env or 1000
        assert delay == int(os.getenv("STEP_RETRY_DELAY_MS", "1000"))


# ---------------------------------------------------------------------------
# execute_test — happy paths
# ---------------------------------------------------------------------------


class TestExecuteTestHappyPath:
    async def test_single_step_passes(self, monkeypatch):
        page = make_mock_page()
        manager = make_mock_manager(page)

        monkeypatch.setattr(
            runner_module, "execute_action", AsyncMock(return_value={"status": "passed"})
        )

        events = []

        async def callback(event):
            events.append(event)

        result = await execute_test(
            manager,
            {"test_id": "t-001", "base_url": "https://x.com", "steps": [{"action": "navigate", "value": "/"}]},
            callback,
        )

        assert result["status"] == "passed"
        assert result["passed"] == 1
        assert result["failed"] == 0
        assert result["skipped"] == 0

        types = [e["type"] for e in events]
        assert types[0] == "started"
        assert "step_started" in types
        assert "step_completed" in types
        assert types[-1] == "completed"

    async def test_multiple_steps_all_pass(self, monkeypatch):
        page = make_mock_page()
        manager = make_mock_manager(page)

        monkeypatch.setattr(
            runner_module, "execute_action", AsyncMock(return_value={"status": "passed"})
        )

        events = []

        async def callback(event):
            events.append(event)

        result = await execute_test(
            manager,
            {
                "steps": [
                    {"action": "navigate", "value": "/"},
                    {"action": "click", "target": "Login"},
                    {"action": "assert_text", "value": "Welcome"},
                ]
            },
            callback,
        )

        assert result["status"] == "passed"
        assert result["passed"] == 3
        assert result["failed"] == 0

    async def test_zero_steps_emits_started_and_completed(self, monkeypatch):
        page = make_mock_page()
        manager = make_mock_manager(page)

        events = []

        async def callback(event):
            events.append(event)

        result = await execute_test(manager, {"steps": []}, callback)

        assert result["status"] == "passed"
        assert result["passed"] == 0
        types = [e["type"] for e in events]
        assert "started" in types
        assert "completed" in types

    async def test_auto_generates_test_id_when_missing(self, monkeypatch):
        page = make_mock_page()
        manager = make_mock_manager(page)
        monkeypatch.setattr(
            runner_module, "execute_action", AsyncMock(return_value={"status": "passed"})
        )

        events = []

        async def callback(event):
            events.append(event)

        result = await execute_test(manager, {"steps": [{"action": "navigate", "value": "/"}]}, callback)
        assert len(result["test_id"]) > 0

    async def test_screenshot_bytes_are_base64_encoded(self, monkeypatch):
        """When action returns screenshot bytes, runner should base64-encode them."""
        import base64
        page = make_mock_page()
        manager = make_mock_manager(page)

        monkeypatch.setattr(
            runner_module,
            "execute_action",
            AsyncMock(return_value={"status": "passed", "screenshot": b"PNG_BYTES"}),
        )

        events = []

        async def callback(event):
            events.append(event)

        await execute_test(manager, {"steps": [{"action": "screenshot"}]}, callback)

        completed_event = next(e for e in events if e["type"] == "step_completed")
        assert completed_event["screenshot"] == base64.b64encode(b"PNG_BYTES").decode()


# ---------------------------------------------------------------------------
# execute_test — failure paths
# ---------------------------------------------------------------------------


class TestExecuteTestFailurePaths:
    async def test_step_failure_stops_and_skips_remaining(self, monkeypatch):
        page = make_mock_page()
        manager = make_mock_manager(page)

        call_count = [0]

        async def fake_execute_action(p, step, base_url):
            call_count[0] += 1
            if call_count[0] == 1:
                return {"status": "passed"}
            return {"status": "failed", "error": "element not found"}

        monkeypatch.setattr(runner_module, "execute_action", fake_execute_action)

        events = []

        async def callback(event):
            events.append(event)

        result = await execute_test(
            manager,
            {"steps": [
                {"action": "navigate", "value": "/"},
                {"action": "click", "target": "Ghost"},
                {"action": "assert_text", "value": "Never reached"},
            ]},
            callback,
        )

        assert result["status"] == "failed"
        assert result["passed"] == 1
        assert result["failed"] == 1
        assert result["skipped"] == 1  # third step never ran

        completed_events = [e for e in events if e["type"] == "step_completed"]
        assert any(e["status"] == "failed" for e in completed_events)

    async def test_exception_in_execute_action_is_caught(self, monkeypatch):
        page = make_mock_page()
        manager = make_mock_manager(page)

        monkeypatch.setattr(
            runner_module,
            "execute_action",
            AsyncMock(side_effect=RuntimeError("unexpected crash")),
        )
        monkeypatch.setattr(runner_module.asyncio, "sleep", AsyncMock())

        events = []

        async def callback(event):
            events.append(event)

        result = await execute_test(
            manager,
            {"steps": [{"action": "click", "target": "Boom"}]},
            callback,
        )

        assert result["status"] == "failed"
        assert result["failed"] == 1

        completed_event = next(e for e in events if e["type"] == "step_completed")
        assert "unexpected crash" in completed_event["error"]

    async def test_screenshot_captured_on_failure(self, monkeypatch):
        """When a step fails, runner captures screenshot from page."""
        import base64
        page = make_mock_page()
        manager = make_mock_manager(page)

        monkeypatch.setattr(
            runner_module,
            "execute_action",
            AsyncMock(return_value={"status": "failed", "error": "not found"}),
        )

        events = []

        async def callback(event):
            events.append(event)

        await execute_test(
            manager,
            {"steps": [{"action": "click", "target": "X"}], "options": {"screenshot_on_failure": True}},
            callback,
        )

        completed_event = next(e for e in events if e["type"] == "step_completed")
        # page.screenshot() returns b"PNG" (from make_mock_page)
        assert completed_event["screenshot"] == base64.b64encode(b"PNG").decode()

    async def test_no_screenshot_when_disabled(self, monkeypatch):
        page = make_mock_page()
        manager = make_mock_manager(page)

        monkeypatch.setattr(
            runner_module,
            "execute_action",
            AsyncMock(return_value={"status": "failed", "error": "nope"}),
        )

        events = []

        async def callback(event):
            events.append(event)

        await execute_test(
            manager,
            {"steps": [{"action": "click"}], "options": {"screenshot_on_failure": False}},
            callback,
        )

        completed_event = next(e for e in events if e["type"] == "step_completed")
        assert completed_event["screenshot"] is None

    async def test_retry_events_emitted_on_failure(self, monkeypatch):
        """Steps with retries should emit step_retry events before final failure."""
        page = make_mock_page()
        manager = make_mock_manager(page)

        monkeypatch.setattr(
            runner_module,
            "execute_action",
            AsyncMock(return_value={"status": "failed", "error": "click failed"}),
        )
        monkeypatch.setattr(runner_module.asyncio, "sleep", AsyncMock())

        events = []

        async def callback(event):
            events.append(event)

        # click has 2 retries by default
        await execute_test(
            manager,
            {"steps": [{"action": "click", "target": "Btn"}]},
            callback,
        )

        retry_events = [e for e in events if e["type"] == "step_retry"]
        assert len(retry_events) == 2  # 2 retries before final failure

    async def test_step_retries_option_overrides_default(self, monkeypatch):
        """options.step_retries=0 disables all retries."""
        page = make_mock_page()
        manager = make_mock_manager(page)

        monkeypatch.setattr(
            runner_module,
            "execute_action",
            AsyncMock(return_value={"status": "failed", "error": "nope"}),
        )

        events = []

        async def callback(event):
            events.append(event)

        await execute_test(
            manager,
            {"steps": [{"action": "click"}], "options": {"step_retries": 0}},
            callback,
        )

        retry_events = [e for e in events if e["type"] == "step_retry"]
        assert len(retry_events) == 0


# ---------------------------------------------------------------------------
# get_retry_config — env var override branch
# ---------------------------------------------------------------------------


class TestGetRetryConfigEnvVar:
    def test_env_var_overrides_default_when_no_options(self, monkeypatch):
        """STEP_RETRY_{ACTION} env variable sets max_retries when options has no step_retries."""
        monkeypatch.setenv("STEP_RETRY_CLICK", "7")
        retries, _ = get_retry_config("click", {})
        assert retries == 7

    def test_env_var_not_set_falls_back_to_default_table(self, monkeypatch):
        monkeypatch.delenv("STEP_RETRY_CLICK", raising=False)
        retries, _ = get_retry_config("click", {})
        assert retries == 2

    def test_step_retries_invalid_type_falls_back_to_default(self):
        """If step_retries is neither int nor dict, use default table."""
        retries, _ = get_retry_config("click", {"step_retries": "invalid"})
        assert retries == 2  # DEFAULT_RETRIES_BY_ACTION["click"]


# ---------------------------------------------------------------------------
# execute_test — result field passthrough + base64 screenshot already encoded
# ---------------------------------------------------------------------------


class TestExecuteTestResultPassthrough:
    async def test_result_field_passed_through_on_success(self, monkeypatch):
        """When execute_action returns a 'result' field, it should appear in step_completed."""
        page = make_mock_page()
        manager = make_mock_manager(page)
        state_payload = {"url": "https://x.com", "state": {"cookies": []}}
        monkeypatch.setattr(
            runner_module, "execute_action",
            AsyncMock(return_value={"status": "passed", "result": state_payload})
        )

        events = []

        async def callback(event):
            events.append(event)

        await execute_test(
            manager,
            {"steps": [{"action": "capture_state"}]},
            callback,
        )

        completed = next(e for e in events if e["type"] == "step_completed")
        assert completed["result"] == state_payload

    async def test_screenshot_already_base64_passed_through(self, monkeypatch):
        """When execute_action returns screenshot as a base64 string, don't double-encode."""
        import base64
        page = make_mock_page()
        manager = make_mock_manager(page)
        b64_screenshot = base64.b64encode(b"FAKE_PNG").decode("utf-8")
        monkeypatch.setattr(
            runner_module, "execute_action",
            AsyncMock(return_value={"status": "passed", "screenshot": b64_screenshot})
        )

        events = []

        async def callback(event):
            events.append(event)

        await execute_test(
            manager,
            {"steps": [{"action": "screenshot"}]},
            callback,
        )

        completed = next(e for e in events if e["type"] == "step_completed")
        assert completed["screenshot"] == b64_screenshot

    async def test_exception_during_step_emits_step_completed_failed(self, monkeypatch):
        """If execute_action raises, the step should be marked failed."""
        page = make_mock_page()
        manager = make_mock_manager(page)
        monkeypatch.setattr(
            runner_module, "execute_action",
            AsyncMock(side_effect=RuntimeError("unexpected crash"))
        )
        # Disable retries for the action being tested
        monkeypatch.setattr(runner_module.asyncio, "sleep", AsyncMock())

        events = []

        async def callback(event):
            events.append(event)

        await execute_test(
            manager,
            # assert_text has 0 retries by default, so exception goes straight to final fail
            {"steps": [{"action": "assert_text", "value": "x"}]},
            callback,
        )

        completed = next(e for e in events if e["type"] == "step_completed")
        assert completed["status"] == "failed"
        assert "unexpected crash" in completed["error"]


# ---------------------------------------------------------------------------
# execute_single_step
# ---------------------------------------------------------------------------


class TestExecuteSingleStep:
    async def test_passed_step_returns_status_and_duration(self, monkeypatch):
        page = make_mock_page()
        monkeypatch.setattr(
            runner_module, "execute_action",
            AsyncMock(return_value={"status": "passed"})
        )
        result = await execute_single_step(page, {"action": "navigate", "value": "/"}, "https://x.com")
        assert result["status"] == "passed"
        assert "duration" in result
        assert result["error"] is None

    async def test_failed_step_captures_screenshot(self, monkeypatch):
        import base64
        page = make_mock_page()
        page.screenshot = AsyncMock(return_value=b"SCREENSHOT")
        monkeypatch.setattr(
            runner_module, "execute_action",
            AsyncMock(return_value={"status": "failed", "error": "not found"})
        )
        result = await execute_single_step(page, {"action": "click", "target": "X"}, "")
        assert result["status"] == "failed"
        assert result["screenshot"] == base64.b64encode(b"SCREENSHOT").decode("utf-8")

    async def test_failed_step_no_screenshot_when_disabled(self, monkeypatch):
        page = make_mock_page()
        monkeypatch.setattr(
            runner_module, "execute_action",
            AsyncMock(return_value={"status": "failed", "error": "err"})
        )
        result = await execute_single_step(page, {"action": "click"}, "", screenshot_on_failure=False)
        assert result["status"] == "failed"
        assert "screenshot" not in result

    async def test_exception_in_action_returns_failed(self, monkeypatch):
        page = make_mock_page()
        monkeypatch.setattr(
            runner_module, "execute_action",
            AsyncMock(side_effect=RuntimeError("crash"))
        )
        result = await execute_single_step(page, {"action": "navigate"}, "")
        assert result["status"] == "failed"
        assert "crash" in result["error"]

    async def test_exception_with_retry_emits_step_retry_events(self, monkeypatch):
        """Exception on a step with retries should emit step_retry events (covers exception retry path)."""
        page = make_mock_page()
        manager = make_mock_manager(page)
        monkeypatch.setattr(
            runner_module, "execute_action",
            AsyncMock(side_effect=RuntimeError("crash"))
        )
        monkeypatch.setattr(runner_module.asyncio, "sleep", AsyncMock())

        events = []

        async def callback(event):
            events.append(event)

        # click has 2 retries by default — exception should trigger retry path
        await execute_test(
            manager,
            {"steps": [{"action": "click", "target": "Btn"}]},
            callback,
        )

        retry_events = [e for e in events if e["type"] == "step_retry"]
        assert len(retry_events) == 2  # 2 retries before final failure
        completed = next(e for e in events if e["type"] == "step_completed")
        assert completed["status"] == "failed"


class TestExecuteTestScreenshotAlreadyBase64:
    async def test_screenshot_bytes_already_string_not_double_encoded(self, monkeypatch):
        """When action returns screenshot as str (already b64), it passes through unchanged."""
        import base64
        page = make_mock_page()
        manager = make_mock_manager(page)
        b64 = base64.b64encode(b"IMG").decode()
        monkeypatch.setattr(
            runner_module, "execute_action",
            AsyncMock(return_value={"status": "passed", "screenshot": b64})
        )

        events = []

        async def cb(e):
            events.append(e)

        await execute_test(manager, {"steps": [{"action": "screenshot"}]}, cb)

        completed = next(e for e in events if e["type"] == "step_completed")
        assert completed["screenshot"] == b64


class TestScreenshotCaptureExceptionPaths:
    """Cover the except-Exception:pass blocks when page.screenshot() raises."""

    async def test_failed_step_screenshot_raises_is_silenced(self, monkeypatch):
        """execute_test: page.screenshot() raises on failed step — silently ignored."""
        page = make_mock_page()
        page.screenshot = AsyncMock(side_effect=RuntimeError("screenshot unavailable"))
        manager = make_mock_manager(page)

        monkeypatch.setattr(
            runner_module, "execute_action",
            AsyncMock(return_value={"status": "failed", "error": "element not found"})
        )

        events = []

        async def cb(e):
            events.append(e)

        # Should not raise, screenshot exception is silenced
        await execute_test(manager, {"steps": [{"action": "click", "target": "X"}]}, cb)
        completed = next(e for e in events if e["type"] == "step_completed")
        assert completed["status"] == "failed"
        assert completed["screenshot"] is None

    async def test_exception_path_screenshot_raises_is_silenced(self, monkeypatch):
        """execute_test: page.screenshot() raises in exception handler — silently ignored."""
        page = make_mock_page()
        page.screenshot = AsyncMock(side_effect=RuntimeError("no page"))
        manager = make_mock_manager(page)

        monkeypatch.setattr(
            runner_module, "execute_action",
            AsyncMock(side_effect=RuntimeError("execute_action blew up"))
        )
        monkeypatch.setattr(runner_module.asyncio, "sleep", AsyncMock())

        events = []

        async def cb(e):
            events.append(e)

        # click has 2 retries — exception raised on every attempt, screenshot also raises
        await execute_test(manager, {"steps": [{"action": "click", "target": "X"}]}, cb)
        completed = next(e for e in events if e["type"] == "step_completed")
        assert completed["status"] == "failed"
        assert completed["screenshot"] is None

    async def test_single_step_failed_screenshot_raises_is_silenced(self, monkeypatch):
        """execute_single_step: page.screenshot() raises on failed result — silently ignored."""
        page = make_mock_page()
        page.screenshot = AsyncMock(side_effect=RuntimeError("no screen"))

        monkeypatch.setattr(
            runner_module, "execute_action",
            AsyncMock(return_value={"status": "failed", "error": "boom"})
        )

        result = await execute_single_step(page, {"action": "click", "target": "X"}, "https://example.com")
        assert result["status"] == "failed"
        assert result.get("screenshot") is None

    async def test_single_step_exception_screenshot_raises_is_silenced(self, monkeypatch):
        """execute_single_step: page.screenshot() raises in exception handler — silently ignored."""
        page = make_mock_page()
        page.screenshot = AsyncMock(side_effect=RuntimeError("no screen"))

        monkeypatch.setattr(
            runner_module, "execute_action",
            AsyncMock(side_effect=RuntimeError("action failed"))
        )

        result = await execute_single_step(page, {"action": "click", "target": "X"}, "https://example.com")
        assert result["status"] == "failed"
        assert result.get("screenshot") is None
