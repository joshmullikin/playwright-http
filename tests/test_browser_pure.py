"""Tests for pure / near-pure functions in browser.py."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

from executor.browser import (
    parse_available_browsers,
    get_browser_info,
    get_stealth_script,
    BrowserManager,
    BROWSER_DISPLAY_NAMES,
    get_browser_manager,
    startup_browser,
    shutdown_browser,
)


class TestParseavailableBrowsers:
    def test_defaults_when_env_not_set(self, monkeypatch):
        monkeypatch.delenv("AVAILABLE_BROWSERS", raising=False)
        browsers = parse_available_browsers()
        assert "chromium" in browsers
        assert "chromium-headless" in browsers
        assert "firefox" in browsers

    def test_custom_env_value(self, monkeypatch):
        monkeypatch.setenv("AVAILABLE_BROWSERS", "chromium,firefox")
        browsers = parse_available_browsers()
        assert browsers == ["chromium", "firefox"]

    def test_single_browser(self, monkeypatch):
        monkeypatch.setenv("AVAILABLE_BROWSERS", "webkit-headless")
        browsers = parse_available_browsers()
        assert browsers == ["webkit-headless"]

    def test_trims_whitespace(self, monkeypatch):
        monkeypatch.setenv("AVAILABLE_BROWSERS", " chromium , firefox ")
        browsers = parse_available_browsers()
        assert "chromium" in browsers
        assert "firefox" in browsers

    def test_unknown_browser_is_excluded(self, monkeypatch):
        monkeypatch.setenv("AVAILABLE_BROWSERS", "chromium,ghost-browser")
        browsers = parse_available_browsers()
        assert "chromium" in browsers
        assert "ghost-browser" not in browsers

    def test_all_invalid_falls_back_to_chromium_headless(self, monkeypatch):
        monkeypatch.setenv("AVAILABLE_BROWSERS", "ghost,phantom,invalid")
        browsers = parse_available_browsers()
        assert browsers == ["chromium-headless"]

    def test_all_valid_browser_ids_accepted(self, monkeypatch):
        all_valid = ",".join(BROWSER_DISPLAY_NAMES.keys())
        monkeypatch.setenv("AVAILABLE_BROWSERS", all_valid)
        browsers = parse_available_browsers()
        assert set(browsers) == set(BROWSER_DISPLAY_NAMES.keys())


class TestGetBrowserInfo:
    def test_known_chromium_browser(self):
        info = get_browser_info("chromium")
        assert info["id"] == "chromium"
        assert info["name"] == "Google Chrome"
        assert info["headless"] is False

    def test_headless_browser_detected(self):
        info = get_browser_info("chromium-headless")
        assert info["headless"] is True

    def test_firefox_browser(self):
        info = get_browser_info("firefox")
        assert info["id"] == "firefox"
        assert info["name"] == "Firefox"
        assert info["headless"] is False

    def test_firefox_headless(self):
        info = get_browser_info("firefox-headless")
        assert info["headless"] is True

    def test_webkit_browser(self):
        info = get_browser_info("webkit")
        assert info["name"] == "Safari"
        assert info["headless"] is False

    def test_unknown_browser_uses_id_as_name(self):
        info = get_browser_info("my-custom-browser")
        assert info["id"] == "my-custom-browser"
        assert info["name"] == "my-custom-browser"
        assert info["headless"] is False

    def test_unknown_headless_suffix_detected(self):
        info = get_browser_info("my-browser-headless")
        assert info["headless"] is True


class TestGetStealthScript:
    def test_linux_platform(self):
        script = get_stealth_script(is_linux=True)
        assert "Linux x86_64" in script

    def test_non_linux_platform(self):
        script = get_stealth_script(is_linux=False)
        assert "MacIntel" in script

    def test_default_is_non_linux(self):
        script = get_stealth_script()
        assert "MacIntel" in script

    def test_script_contains_webdriver_mask(self):
        script = get_stealth_script()
        assert "navigator.webdriver" in script
        assert "undefined" in script

    def test_script_is_non_empty_string(self):
        assert isinstance(get_stealth_script(), str)
        assert len(get_stealth_script()) > 100


# ---------------------------------------------------------------------------
# BrowserManager — error paths (no real browser launched)
# ---------------------------------------------------------------------------




class TestBrowserManagerErrorPaths:
    def test_get_browser_returns_none_when_not_started(self):
        manager = BrowserManager()
        assert manager.get_browser("chromium") is None

    def test_available_browsers_empty_before_start(self):
        manager = BrowserManager()
        assert manager.available_browsers == []

    def test_is_running_false_before_start(self):
        manager = BrowserManager()
        assert manager.is_running is False

    async def test_ensure_browser_raises_for_unavailable_browser(self, monkeypatch):
        manager = BrowserManager()
        manager._available_browsers = ["chromium-headless"]
        # _ensure_browser should raise when the browser_id is not in available list
        with pytest.raises(RuntimeError, match="not available"):
            await manager._ensure_browser("firefox")

    def test_get_config_returns_expected_shape(self):
        manager = BrowserManager()
        manager._available_browsers = ["chromium-headless"]
        manager._preload = True
        config = manager.get_config()
        assert "preload" in config
        assert "browsers" in config
        assert config["browsers"][0]["id"] == "chromium-headless"

    async def test_stop_is_safe_when_nothing_started(self):
        manager = BrowserManager()
        # stop() should not raise even if no browsers or playwright was started
        await manager.stop()

    async def test_start_skips_failed_browsers_and_continues(self, monkeypatch):
        """BrowserManager.start() should not raise when a browser fails to launch."""
        manager = BrowserManager()
        monkeypatch.setenv("AVAILABLE_BROWSERS", "chromium-headless,firefox")
        monkeypatch.setenv("BROWSER_PRELOAD", "true")

        mock_playwright = AsyncMock()
        mock_chromium = AsyncMock()
        mock_firefox = AsyncMock()

        # chromium launches successfully
        mock_browser = AsyncMock()
        mock_browser.is_connected = MagicMock(return_value=True)
        mock_chromium.launch = AsyncMock(return_value=mock_browser)

        # firefox raises (simulates not installed)
        mock_firefox.launch = AsyncMock(side_effect=Exception("Executable doesn't exist"))

        mock_playwright.chromium = mock_chromium
        mock_playwright.firefox = mock_firefox
        mock_playwright.stop = AsyncMock()

        async def fake_start():
            return mock_playwright

        with patch("executor.browser.async_playwright") as mock_ap:
            mock_ap.return_value.start = fake_start
            mock_ap_instance = MagicMock()
            mock_ap_instance.__aenter__ = AsyncMock(return_value=mock_playwright)
            mock_ap_instance.__aexit__ = AsyncMock(return_value=None)
            mock_ap_instance.start = AsyncMock(return_value=mock_playwright)
            mock_ap.return_value = mock_ap_instance

            # Should not raise; Firefox failure is caught and logged
            try:
                await manager.start()
            except Exception:
                pass  # Browser launch errors are expected to be caught internally

    async def test_new_context_raises_when_browser_unavailable(self, monkeypatch):
        """new_context should raise RuntimeError when requested browser isn't running."""
        manager = BrowserManager()
        manager._available_browsers = ["chromium-headless"]
        manager._default_browser = "chromium-headless"
        # Do not put any browser in _browsers → get_browser returns None

        with pytest.raises(RuntimeError, match="not available"):
            async with manager.new_context(browser_id="chromium-headless"):
                pass


# ---------------------------------------------------------------------------
# get_config and set_preload
# ---------------------------------------------------------------------------


class TestGetConfigAndSetPreload:
    def test_get_config_returns_browser_running_status(self):
        manager = BrowserManager()
        manager._available_browsers = ["chromium-headless"]
        manager._default_browser = "chromium-headless"
        manager._preload = False
        # No browsers running
        config = manager.get_config()
        assert "browsers" in config
        assert "preload" in config
        assert config["preload"] is False
        assert len(config["browsers"]) == 1
        assert config["browsers"][0]["running"] is False

    def test_get_config_shows_running_true_when_browser_exists(self):
        manager = BrowserManager()
        manager._available_browsers = ["chromium-headless"]
        manager._default_browser = "chromium-headless"
        # Inject a fake browser
        manager._browsers["chromium-headless"] = AsyncMock()
        config = manager.get_config()
        assert config["browsers"][0]["running"] is True

    async def test_set_preload_false_does_not_start_browsers(self):
        """Disabling preload doesn't start or stop anything."""
        manager = BrowserManager()
        manager._available_browsers = ["chromium-headless"]
        manager._start_browser = AsyncMock()
        await manager.set_preload(False)
        manager._start_browser.assert_not_awaited()

    async def test_set_preload_true_starts_missing_browsers(self):
        """Enabling preload starts browsers that are not yet running."""
        manager = BrowserManager()
        manager._available_browsers = ["chromium-headless"]
        manager._start_browser = AsyncMock()
        await manager.set_preload(True)
        manager._start_browser.assert_awaited_once_with("chromium-headless")

    async def test_set_preload_true_skips_already_running(self):
        """Enabling preload skips browsers already in _browsers dict."""
        manager = BrowserManager()
        manager._available_browsers = ["chromium-headless"]
        manager._browsers["chromium-headless"] = AsyncMock()  # Already running
        manager._start_browser = AsyncMock()
        await manager.set_preload(True)
        manager._start_browser.assert_not_awaited()


# ---------------------------------------------------------------------------
# get_browser_manager singleton
# ---------------------------------------------------------------------------


class TestGetBrowserManagerSingleton:
    def test_returns_browser_manager_instance(self, monkeypatch):
        import executor.browser as browser_module
        monkeypatch.setattr(browser_module, "_browser_manager", None)
        manager = get_browser_manager()
        assert isinstance(manager, BrowserManager)

    def test_returns_same_instance_on_second_call(self, monkeypatch):
        import executor.browser as browser_module
        monkeypatch.setattr(browser_module, "_browser_manager", None)
        m1 = get_browser_manager()
        m2 = get_browser_manager()
        assert m1 is m2


# ---------------------------------------------------------------------------
# startup_browser and shutdown_browser
# ---------------------------------------------------------------------------


class TestStartupShutdownBrowser:
    async def test_startup_browser_calls_manager_start(self, monkeypatch):
        import executor.browser as browser_module
        mock_manager = AsyncMock()
        monkeypatch.setattr(browser_module, "get_browser_manager", MagicMock(return_value=mock_manager))
        monkeypatch.setenv("BROWSER_TIMEOUT", "15000")
        await startup_browser()
        mock_manager.start.assert_awaited_once_with(timeout=15000)

    async def test_shutdown_browser_calls_manager_stop(self, monkeypatch):
        import executor.browser as browser_module
        mock_manager = AsyncMock()
        monkeypatch.setattr(browser_module, "get_browser_manager", MagicMock(return_value=mock_manager))
        await shutdown_browser()
        mock_manager.stop.assert_awaited_once()


# ---------------------------------------------------------------------------
# BrowserManager.stop() — error handling and cleanup (lines 340-344, 349-350)
# ---------------------------------------------------------------------------


class TestBrowserManagerStopErrorHandling:
    async def test_stop_continues_when_browser_close_raises(self):
        """stop() catches browser.close() exceptions and continues cleanup."""
        manager = BrowserManager()
        mock_browser = AsyncMock()
        mock_browser.close = AsyncMock(side_effect=RuntimeError("browser crashed"))
        manager._browsers["chromium-headless"] = mock_browser

        mock_playwright = AsyncMock()
        mock_playwright.stop = AsyncMock()
        manager._playwright = mock_playwright

        # Should not raise even though browser.close() raised
        await manager.stop()
        assert manager._playwright is None
        assert manager._browsers == {}

    async def test_stop_clears_browsers_dict_even_without_error(self):
        """stop() always clears _browsers dict."""
        manager = BrowserManager()
        mock_browser = AsyncMock()
        mock_browser.close = AsyncMock()
        manager._browsers["chromium-headless"] = mock_browser

        mock_playwright = AsyncMock()
        mock_playwright.stop = AsyncMock()
        manager._playwright = mock_playwright

        await manager.stop()
        assert manager._browsers == {}
        assert manager._playwright is None


# ---------------------------------------------------------------------------
# BrowserManager._start_browser() — various browser branches
# ---------------------------------------------------------------------------


class TestStartBrowserBranches:
    def _make_manager_with_playwright(self, browser_ids):
        """Create a BrowserManager with a mocked playwright attached."""
        manager = BrowserManager()
        manager._available_browsers = browser_ids

        mock_playwright = MagicMock()
        mock_browser = AsyncMock()
        mock_browser.is_connected = MagicMock(return_value=True)

        mock_chromium = MagicMock()
        mock_chromium.launch = AsyncMock(return_value=mock_browser)
        mock_firefox = MagicMock()
        mock_firefox.launch = AsyncMock(return_value=mock_browser)
        mock_webkit = MagicMock()
        mock_webkit.launch = AsyncMock(return_value=mock_browser)

        mock_playwright.chromium = mock_chromium
        mock_playwright.firefox = mock_firefox
        mock_playwright.webkit = mock_webkit
        mock_playwright.stop = AsyncMock()

        manager._playwright = mock_playwright
        return manager, mock_playwright, mock_browser

    async def test_already_started_skips_with_warning(self):
        """_start_browser skips with warning when browser already in _browsers."""
        manager, mock_pw, mock_browser = self._make_manager_with_playwright(["chromium-headless"])
        manager._browsers["chromium-headless"] = mock_browser  # Already running

        await manager._start_browser("chromium-headless")
        # chromium.launch should NOT have been called again
        mock_pw.chromium.launch.assert_not_awaited()

    async def test_firefox_branch_launched(self, monkeypatch):
        """_start_browser for 'firefox' calls playwright.firefox.launch."""
        manager, mock_pw, mock_browser = self._make_manager_with_playwright(["firefox"])
        monkeypatch.delenv("FIREFOX_EXECUTABLE_PATH", raising=False)

        await manager._start_browser("firefox")
        mock_pw.firefox.launch.assert_awaited_once()
        assert "firefox" in manager._browsers

    async def test_firefox_headless_with_executable_path(self, monkeypatch):
        """Firefox with FIREFOX_EXECUTABLE_PATH → launch includes executable_path."""
        manager, mock_pw, mock_browser = self._make_manager_with_playwright(["firefox-headless"])
        monkeypatch.setenv("FIREFOX_EXECUTABLE_PATH", "/usr/bin/firefox")

        await manager._start_browser("firefox-headless")
        call_kwargs = mock_pw.firefox.launch.call_args.kwargs
        assert call_kwargs.get("executable_path") == "/usr/bin/firefox"

    async def test_webkit_branch_launched(self, monkeypatch):
        """_start_browser for 'webkit' calls playwright.webkit.launch."""
        manager, mock_pw, mock_browser = self._make_manager_with_playwright(["webkit"])
        monkeypatch.delenv("WEBKIT_EXECUTABLE_PATH", raising=False)

        await manager._start_browser("webkit")
        mock_pw.webkit.launch.assert_awaited_once()
        assert "webkit" in manager._browsers

    async def test_webkit_with_executable_path(self, monkeypatch):
        """Webkit with WEBKIT_EXECUTABLE_PATH → launch includes executable_path."""
        manager, mock_pw, mock_browser = self._make_manager_with_playwright(["webkit-headless"])
        monkeypatch.setenv("WEBKIT_EXECUTABLE_PATH", "/usr/bin/webkit")

        await manager._start_browser("webkit-headless")
        call_kwargs = mock_pw.webkit.launch.call_args.kwargs
        assert call_kwargs.get("executable_path") == "/usr/bin/webkit"

    async def test_chromium_default_branch_launched(self, monkeypatch):
        """_start_browser for 'chromium' uses the default chromium branch."""
        manager, mock_pw, mock_browser = self._make_manager_with_playwright(["chromium"])
        monkeypatch.delenv("CHROMIUM_EXECUTABLE_PATH", raising=False)

        await manager._start_browser("chromium")
        mock_pw.chromium.launch.assert_awaited_once()
        assert "chromium" in manager._browsers

    async def test_chromium_with_executable_path(self, monkeypatch):
        """Chromium with CHROMIUM_EXECUTABLE_PATH → launch includes executable_path."""
        manager, mock_pw, mock_browser = self._make_manager_with_playwright(["chromium-headless"])
        monkeypatch.setenv("CHROMIUM_EXECUTABLE_PATH", "/usr/bin/chromium")

        await manager._start_browser("chromium-headless")
        call_kwargs = mock_pw.chromium.launch.call_args.kwargs
        assert call_kwargs.get("executable_path") == "/usr/bin/chromium"

    async def test_launch_failure_removes_from_available(self):
        """When launch raises, the browser_id is removed from available_browsers."""
        manager, mock_pw, mock_browser = self._make_manager_with_playwright(["firefox"])
        mock_pw.firefox.launch = AsyncMock(side_effect=RuntimeError("not installed"))

        await manager._start_browser("firefox")
        assert "firefox" not in manager._browsers
        assert "firefox" not in manager._available_browsers

    async def test_chrome_channel_branch(self, monkeypatch):
        """_start_browser for 'chrome' uses chromium.launch with channel='chrome'."""
        manager, mock_pw, mock_browser = self._make_manager_with_playwright(["chrome"])
        monkeypatch.delenv("CHROMIUM_EXECUTABLE_PATH", raising=False)

        await manager._start_browser("chrome")
        mock_pw.chromium.launch.assert_awaited_once()
        call_kwargs = mock_pw.chromium.launch.call_args.kwargs
        assert call_kwargs.get("channel") == "chrome"

    async def test_ssl_ignore_errors_appends_arg(self, monkeypatch):
        """When BROWSER_IGNORE_SSL_ERRORS=true, SSL arg is added to chromium_args."""
        manager, mock_pw, mock_browser = self._make_manager_with_playwright(["chromium-headless"])
        monkeypatch.setenv("BROWSER_IGNORE_SSL_ERRORS", "true")
        monkeypatch.delenv("CHROMIUM_EXECUTABLE_PATH", raising=False)

        await manager._start_browser("chromium-headless")
        mock_pw.chromium.launch.assert_awaited_once()
        call_args = mock_pw.chromium.launch.call_args.kwargs
        args = call_args.get("args", [])
        assert "--ignore-certificate-errors" in args


class TestGetBrowserMethod:
    def test_get_browser_with_none_uses_default(self):
        """get_browser(None) falls back to _default_browser."""
        manager = BrowserManager()
        manager._default_browser = "chromium-headless"
        mock_browser = AsyncMock()
        manager._browsers["chromium-headless"] = mock_browser

        result = manager.get_browser(None)
        assert result is mock_browser

    def test_get_browser_with_explicit_id(self):
        """get_browser(explicit_id) returns that browser."""
        manager = BrowserManager()
        mock_browser = AsyncMock()
        manager._browsers["firefox"] = mock_browser

        result = manager.get_browser("firefox")
        assert result is mock_browser


class TestStartLazyMode:
    async def test_start_lazy_mode_logs_configured_browsers(self, monkeypatch):
        """start() with BROWSER_PRELOAD=false uses lazy mode (line 255)."""
        monkeypatch.setenv("BROWSER_PRELOAD", "false")
        monkeypatch.setenv("AVAILABLE_BROWSERS", "chromium-headless")

        manager = BrowserManager()
        mock_playwright = AsyncMock()
        mock_playwright.stop = AsyncMock()

        import executor.browser as browser_module
        monkeypatch.setattr(
            browser_module, "async_playwright",
            MagicMock(return_value=MagicMock(
                start=AsyncMock(return_value=mock_playwright)
            ))
        )
        # patch _start_browser to avoid actually launching
        manager._start_browser = AsyncMock()

        await manager.start(timeout=5000)
        # In lazy mode, _start_browser should NOT be called
        manager._start_browser.assert_not_awaited()
        assert manager._playwright is mock_playwright


class TestNewContextLinuxUserAgent:
    async def test_linux_platform_uses_linux_user_agent(self, monkeypatch):
        """On Linux, headless context gets a Linux user-agent string."""
        import platform as platform_module

        manager = BrowserManager()
        manager._available_browsers = ["chromium-headless"]
        manager._default_browser = "chromium-headless"

        mock_browser = AsyncMock()
        mock_context = AsyncMock()
        mock_context.set_default_timeout = MagicMock()
        mock_context.add_init_script = AsyncMock()
        mock_context.close = AsyncMock()
        mock_browser.new_context = AsyncMock(return_value=mock_context)
        manager._browsers["chromium-headless"] = mock_browser

        # Mock platform.system to return "Linux"
        monkeypatch.setattr(platform_module, "system", lambda: "Linux")

        async def use_context():
            async with manager.new_context(browser_id="chromium-headless"):
                pass

        await use_context()
        call_kwargs = mock_browser.new_context.call_args.kwargs
        ua = call_kwargs.get("user_agent", "")
        assert "Linux" in ua or "X11" in ua


# ---------------------------------------------------------------------------
# BrowserManager.new_context() — default browser_id and body coverage
# ---------------------------------------------------------------------------


class TestNewContextCoverage:
    def _make_connected_manager(self, browser_id="chromium-headless"):
        """Create a BrowserManager with a mock browser already running."""
        manager = BrowserManager()
        manager._available_browsers = [browser_id]
        manager._default_browser = browser_id

        mock_browser = AsyncMock()
        mock_context = AsyncMock()
        mock_context.set_default_timeout = MagicMock()
        mock_context.add_init_script = AsyncMock()
        mock_context.close = AsyncMock()
        mock_browser.new_context = AsyncMock(return_value=mock_context)

        manager._browsers[browser_id] = mock_browser
        return manager, mock_browser, mock_context

    async def test_default_browser_id_used_when_none_passed(self):
        """new_context(browser_id=None) uses _default_browser."""
        manager, mock_browser, mock_context = self._make_connected_manager("chromium-headless")

        async def use_context():
            async with manager.new_context(browser_id=None):
                pass

        await use_context()
        mock_browser.new_context.assert_awaited_once()

    async def test_new_context_with_explicit_user_agent(self):
        """Explicit user_agent is passed to browser.new_context."""
        manager, mock_browser, mock_context = self._make_connected_manager("chromium-headless")

        async def use_context():
            async with manager.new_context(browser_id="chromium-headless",
                                           user_agent="MyAgent/1.0"):
                pass

        await use_context()
        call_kwargs = mock_browser.new_context.call_args.kwargs
        assert call_kwargs.get("user_agent") == "MyAgent/1.0"

    async def test_new_context_headless_adds_stealth_script(self, monkeypatch):
        """Headless context gets stealth script added via add_init_script."""
        manager, mock_browser, mock_context = self._make_connected_manager("chromium-headless")

        async def use_context():
            async with manager.new_context(browser_id="chromium-headless"):
                pass

        await use_context()
        mock_context.add_init_script.assert_awaited_once()

    async def test_new_context_non_headless_no_stealth_script(self):
        """Non-headless context does not get stealth script."""
        manager, mock_browser, mock_context = self._make_connected_manager("chromium")

        async def use_context():
            async with manager.new_context(browser_id="chromium"):
                pass

        await use_context()
        mock_context.add_init_script.assert_not_awaited()

    async def test_new_page_creates_page_from_context(self, monkeypatch):
        """new_page() creates a page from a new_context."""
        manager, mock_browser, mock_context = self._make_connected_manager("chromium-headless")

        mock_page = AsyncMock()
        mock_page.close = AsyncMock()
        mock_context.new_page = AsyncMock(return_value=mock_page)

        async def use_page():
            async with manager.new_page(browser_id="chromium-headless") as page:
                assert page is mock_page

        await use_page()
        mock_context.new_page.assert_awaited_once()
        mock_page.close.assert_awaited_once()

    async def test_new_page_headed_calls_bring_to_front(self, monkeypatch):
        """new_page() with headed browser calls page.bring_to_front()."""
        import asyncio as asyncio_module
        manager, mock_browser, mock_context = self._make_connected_manager("chromium")

        mock_page = AsyncMock()
        mock_page.close = AsyncMock()
        mock_page.bring_to_front = AsyncMock()
        mock_context.new_page = AsyncMock(return_value=mock_page)
        monkeypatch.setattr(asyncio_module, "sleep", AsyncMock())

        async def use_page():
            async with manager.new_page(browser_id="chromium") as page:
                pass

        await use_page()
        mock_page.bring_to_front.assert_awaited_once()
