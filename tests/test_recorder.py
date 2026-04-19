"""Unit tests for executor/recorder.py.

Tests pure functions and session-management logic without launching a real browser.
"""

import asyncio
import json
import time
from dataclasses import dataclass, field
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import executor.recorder as recorder_module
from executor.recorder import (
    RecordingSession,
    get_session,
    list_sessions,
    stop_recording,
    _handle_console,
    _handle_response,
    _handle_navigation,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session(session_id: str = "test-session-id", stopped: bool = False) -> RecordingSession:
    """Create a minimal RecordingSession without a real browser."""
    main_frame = MagicMock()
    main_frame.url = "https://example.com"

    page = MagicMock()
    page.main_frame = main_frame
    page.url = "https://example.com"

    context = MagicMock()
    browser = MagicMock()
    pw = MagicMock()

    session = RecordingSession(
        session_id=session_id,
        base_url="https://example.com",
        playwright=pw,
        browser=browser,
        context=context,
        page=page,
        on_event=None,
    )
    session._stopped = stopped
    return session


def _inject(session: RecordingSession):
    """Register a session in the global store and return it."""
    recorder_module._sessions[session.session_id] = session
    return session


def _eject(session_id: str):
    """Remove a session from the global store (cleanup)."""
    recorder_module._sessions.pop(session_id, None)


# ---------------------------------------------------------------------------
# get_session / list_sessions
# ---------------------------------------------------------------------------


class TestGetSession:
    def test_returns_session_when_present(self):
        session = _inject(_make_session("gs-1"))
        try:
            result = get_session("gs-1")
            assert result is session
        finally:
            _eject("gs-1")

    def test_returns_none_when_missing(self):
        assert get_session("no-such-id") is None


class TestListSessions:
    def test_lists_active_sessions(self):
        s1 = _inject(_make_session("ls-1"))
        try:
            sessions = list_sessions()
            ids = [s["session_id"] for s in sessions]
            assert "ls-1" in ids
        finally:
            _eject("ls-1")

    def test_excludes_stopped_sessions(self):
        s2 = _inject(_make_session("ls-2", stopped=True))
        try:
            sessions = list_sessions()
            ids = [s["session_id"] for s in sessions]
            assert "ls-2" not in ids
        finally:
            _eject("ls-2")

    def test_returns_expected_fields(self):
        s3 = _inject(_make_session("ls-3"))
        try:
            sessions = list_sessions()
            match = next(s for s in sessions if s["session_id"] == "ls-3")
            assert "base_url" in match
            assert "event_count" in match
        finally:
            _eject("ls-3")


# ---------------------------------------------------------------------------
# _handle_console
# ---------------------------------------------------------------------------


class TestHandleConsole:
    def _msg(self, text: str) -> MagicMock:
        msg = MagicMock()
        msg.text = text
        return msg

    def test_ignores_non_recorder_prefix(self):
        session = _make_session("hc-1")
        _handle_console(session, self._msg("regular log message"))
        assert session.events == []

    def test_ignores_when_stopped(self):
        session = _make_session("hc-2", stopped=True)
        payload = json.dumps({"type": "click"})
        _handle_console(session, self._msg(f"__RECORDER__:{payload}"))
        assert session.events == []

    def test_appends_valid_event(self):
        session = _make_session("hc-3")
        payload = json.dumps({"type": "click", "selector": "#btn"})
        _handle_console(session, self._msg(f"__RECORDER__:{payload}"))
        assert len(session.events) == 1
        assert session.events[0]["type"] == "click"

    def test_calls_on_event_callback(self):
        session = _make_session("hc-4")
        tasks_created = []

        loop = asyncio.new_event_loop()
        try:
            async def cb(event):
                tasks_created.append(event)

            session.on_event = cb
            payload = json.dumps({"type": "type", "value": "hello"})

            # Simulate a running event loop
            mock_loop = MagicMock()
            mock_loop.create_task = MagicMock()

            with patch("executor.recorder.asyncio.get_running_loop", return_value=mock_loop):
                _handle_console(session, self._msg(f"__RECORDER__:{payload}"))

            assert mock_loop.create_task.called
        finally:
            loop.close()

    def test_handles_malformed_json_gracefully(self):
        session = _make_session("hc-5")
        _handle_console(session, self._msg("__RECORDER__:not-valid-json{{"))
        # Should not raise; events list stays empty
        assert session.events == []


# ---------------------------------------------------------------------------
# _handle_response
# ---------------------------------------------------------------------------


class TestHandleResponse:
    def _make_response(self, status: int, url: str, location: str = "", same_frame: bool = True):
        response = MagicMock()
        response.status = status
        response.url = url
        response.headers = {"location": location} if location else {}
        return response

    def test_ignores_non_redirect(self):
        session = _make_session("hr-1")
        resp = self._make_response(200, "https://example.com")
        resp.frame = session.page.main_frame
        _handle_response(session, resp)
        assert len(session._redirect_urls) == 0

    def test_tracks_redirect_url(self):
        session = _make_session("hr-2")
        resp = self._make_response(302, "https://example.com/old", "https://example.com/new")
        resp.frame = session.page.main_frame
        _handle_response(session, resp)
        assert "https://example.com/old" in session._redirect_urls
        assert "https://example.com/new" in session._redirect_urls

    def test_ignores_when_stopped(self):
        session = _make_session("hr-3", stopped=True)
        resp = self._make_response(302, "https://example.com/old", "https://example.com/new")
        resp.frame = session.page.main_frame
        _handle_response(session, resp)
        assert len(session._redirect_urls) == 0

    def test_ignores_non_main_frame(self):
        session = _make_session("hr-4")
        other_frame = MagicMock()
        resp = self._make_response(302, "https://example.com/old")
        resp.frame = other_frame  # not main frame
        _handle_response(session, resp)
        assert len(session._redirect_urls) == 0

    def test_handles_frame_access_exception(self):
        """If accessing response.frame raises (detached frame), should not crash."""
        session = _make_session("hr-5")
        resp = MagicMock()
        resp.status = 301
        resp.url = "https://example.com/a"
        resp.headers = {}
        type(resp).frame = property(lambda self: (_ for _ in ()).throw(Exception("detached")))
        # Should not raise
        _handle_response(session, resp)


# ---------------------------------------------------------------------------
# _handle_navigation
# ---------------------------------------------------------------------------


class TestHandleNavigation:
    def test_ignores_non_main_frame(self):
        session = _make_session("hn-1")
        other_frame = MagicMock()
        other_frame.url = "https://sub.example.com"
        _handle_navigation(session, other_frame)
        assert session.events == []

    def test_ignores_when_stopped(self):
        session = _make_session("hn-2", stopped=True)
        frame = session.page.main_frame
        frame.url = "https://example.com/new"
        _handle_navigation(session, frame)
        assert session.events == []

    def test_skips_redirect_hop_url(self):
        session = _make_session("hn-3")
        session._redirect_urls.add("https://example.com/redirect")
        frame = session.page.main_frame
        frame.url = "https://example.com/redirect"

        loop = asyncio.new_event_loop()
        try:
            with patch("executor.recorder.asyncio.get_running_loop", return_value=loop):
                loop.create_task = MagicMock()
                _handle_navigation(session, frame)
            # Redirect URL is skipped → no navigate event appended
            assert session.events == []
            # And the redirect URL is removed from the set
            assert "https://example.com/redirect" not in session._redirect_urls
        finally:
            loop.close()

    def test_emits_navigate_event(self):
        session = _make_session("hn-4")
        frame = session.page.main_frame
        frame.url = "https://example.com/page2"

        loop = asyncio.new_event_loop()
        try:
            with patch("executor.recorder.asyncio.get_running_loop", return_value=loop):
                loop.create_task = MagicMock()
                _handle_navigation(session, frame)
            assert len(session.events) == 1
            assert session.events[0]["type"] == "navigate"
            assert session.events[0]["value"] == "https://example.com/page2"
        finally:
            loop.close()

    def test_on_event_callback_scheduled_via_create_task(self):
        """When session.on_event is set, loop.create_task is called with it."""
        session = _make_session("hn-6")
        session.on_event = AsyncMock()
        frame = session.page.main_frame
        frame.url = "https://example.com/callback-page"

        loop = asyncio.new_event_loop()
        try:
            with patch("executor.recorder.asyncio.get_running_loop", return_value=loop):
                loop.create_task = MagicMock()
                _handle_navigation(session, frame)
            assert loop.create_task.called
        finally:
            loop.close()

    def test_no_running_loop_does_nothing(self):
        session = _make_session("hn-5")
        frame = session.page.main_frame
        frame.url = "https://example.com/x"

        with patch("executor.recorder.asyncio.get_running_loop", side_effect=RuntimeError("no loop")):
            _handle_navigation(session, frame)
        assert session.events == []


# ---------------------------------------------------------------------------
# stop_recording
# ---------------------------------------------------------------------------


class TestStopRecording:
    async def test_raises_for_unknown_session(self):
        with pytest.raises(ValueError, match="No session"):
            await stop_recording("nonexistent-session")

    async def test_returns_summary_and_removes_session(self):
        session = _inject(_make_session("sr-1"))
        session.events = [{"type": "click"}, {"type": "navigate"}]

        # Mock all the close calls to avoid needing a real browser
        session.page.close = AsyncMock()
        session.context.close = AsyncMock()
        session.browser.close = AsyncMock()
        session.playwright.stop = AsyncMock()

        result = await stop_recording("sr-1")
        assert result["session_id"] == "sr-1"
        assert result["event_count"] == 2
        assert len(result["events"]) == 2
        # Should be removed from the global store
        assert get_session("sr-1") is None

    async def test_handles_close_exceptions_gracefully(self):
        session = _inject(_make_session("sr-2"))
        session.events = []

        # Simulate close failures on all resources
        session.page.close = AsyncMock(side_effect=Exception("page gone"))
        session.context.close = AsyncMock(side_effect=Exception("context gone"))
        session.browser.close = AsyncMock(side_effect=Exception("browser gone"))
        session.playwright.stop = AsyncMock(side_effect=Exception("pw gone"))

        # Should not raise despite all errors
        result = await stop_recording("sr-2")
        assert result["session_id"] == "sr-2"
        assert get_session("sr-2") is None


# ---------------------------------------------------------------------------
# _handle_console — on_event callback paths (lines 164-165)
# ---------------------------------------------------------------------------


class TestHandleConsoleOnEventPaths:
    async def test_on_event_called_when_running_loop_exists(self):
        """When a running event loop exists, on_event task is created."""
        events_received = []

        async def on_event(ev):
            events_received.append(ev)

        session = _make_session("hc-e1")
        session.on_event = on_event

        msg = MagicMock()
        msg.text = recorder_module.RECORDER_EVENT_PREFIX + '{"type":"click","target":"#btn"}'
        _handle_console(session, msg)
        # Yield to allow task to run
        await asyncio.sleep(0)

        assert len(events_received) == 1
        assert events_received[0]["type"] == "click"

    def test_on_event_no_running_loop_silently_passes(self):
        """When no running loop, RuntimeError is caught silently."""
        async def on_event(ev):
            pass

        session = _make_session("hc-e2")
        session.on_event = on_event

        msg = MagicMock()
        msg.text = recorder_module.RECORDER_EVENT_PREFIX + '{"type":"navigate"}'

        # Call outside an event loop
        with patch("executor.recorder.asyncio.get_running_loop", side_effect=RuntimeError("no loop")):
            _handle_console(session, msg)

        # Should have appended the event even though task creation failed
        assert len(session.events) == 1
        assert session.events[0]["type"] == "navigate"


# ---------------------------------------------------------------------------
# start_recording — mock playwright
# ---------------------------------------------------------------------------


class TestStartRecording:
    async def test_start_recording_creates_session(self, monkeypatch):
        """start_recording should register a session and return it."""
        from executor.recorder import start_recording

        # Mock async_playwright
        mock_pw = AsyncMock()
        mock_browser = AsyncMock()
        mock_context = AsyncMock()
        mock_page = AsyncMock()
        mock_page.main_frame = MagicMock()

        mock_context.new_page = AsyncMock(return_value=mock_page)
        mock_browser.new_context = AsyncMock(return_value=mock_context)
        mock_pw.chromium = AsyncMock()
        mock_pw.chromium.launch = AsyncMock(return_value=mock_browser)

        mock_ap_instance = AsyncMock()
        mock_ap_instance.start = AsyncMock(return_value=mock_pw)

        monkeypatch.setattr(recorder_module, "async_playwright", MagicMock(return_value=mock_ap_instance))

        with patch("pathlib.Path.read_text", return_value="// recorder script"):
            session = await start_recording("https://example.com")
        try:
            assert session.base_url == "https://example.com"
            assert session.session_id in recorder_module._sessions
            assert session.page is mock_page
            assert session.browser is mock_browser
        finally:
            _eject(session.session_id)

    async def test_start_recording_handles_navigation_exception(self, monkeypatch):
        """If goto raises on initial navigation, session is still returned."""
        from executor.recorder import start_recording

        mock_pw = AsyncMock()
        mock_browser = AsyncMock()
        mock_context = AsyncMock()
        mock_page = AsyncMock()
        mock_page.main_frame = MagicMock()
        mock_page.goto = AsyncMock(side_effect=Exception("net::ERR_CONNECTION_REFUSED"))

        mock_context.new_page = AsyncMock(return_value=mock_page)
        mock_browser.new_context = AsyncMock(return_value=mock_context)
        mock_pw.chromium.launch = AsyncMock(return_value=mock_browser)

        mock_ap_instance = AsyncMock()
        mock_ap_instance.start = AsyncMock(return_value=mock_pw)

        monkeypatch.setattr(recorder_module, "async_playwright", MagicMock(return_value=mock_ap_instance))

        with patch("pathlib.Path.read_text", return_value="// recorder script"):
            session = await start_recording("https://unreachable.example.com")
        try:
            # Should still return a valid session despite goto failure
            assert session is not None
            assert session.base_url == "https://unreachable.example.com"
        finally:
            _eject(session.session_id)

    async def test_start_recording_with_viewport(self, monkeypatch):
        """Custom viewport is passed through to new_context."""
        from executor.recorder import start_recording

        mock_pw = AsyncMock()
        mock_browser = AsyncMock()
        mock_context = AsyncMock()
        mock_page = AsyncMock()
        mock_page.main_frame = MagicMock()

        mock_context.new_page = AsyncMock(return_value=mock_page)
        mock_browser.new_context = AsyncMock(return_value=mock_context)
        mock_pw.chromium.launch = AsyncMock(return_value=mock_browser)

        mock_ap_instance = AsyncMock()
        mock_ap_instance.start = AsyncMock(return_value=mock_pw)

        monkeypatch.setattr(recorder_module, "async_playwright", MagicMock(return_value=mock_ap_instance))

        vp = {"width": 1920, "height": 1080}
        with patch("pathlib.Path.read_text", return_value="// script"):
            session = await start_recording("https://example.com", viewport=vp)
        try:
            mock_browser.new_context.assert_awaited_once_with(viewport=vp)
        finally:
            _eject(session.session_id)

    async def test_start_recording_with_chromium_executable_path(self, monkeypatch):
        """CHROMIUM_EXECUTABLE_PATH env var is forwarded to launch opts."""
        from executor.recorder import start_recording

        mock_pw = AsyncMock()
        mock_browser = AsyncMock()
        mock_context = AsyncMock()
        mock_page = AsyncMock()
        mock_page.main_frame = MagicMock()

        mock_context.new_page = AsyncMock(return_value=mock_page)
        mock_browser.new_context = AsyncMock(return_value=mock_context)
        mock_pw.chromium.launch = AsyncMock(return_value=mock_browser)

        mock_ap_instance = AsyncMock()
        mock_ap_instance.start = AsyncMock(return_value=mock_pw)

        monkeypatch.setattr(recorder_module, "async_playwright", MagicMock(return_value=mock_ap_instance))
        monkeypatch.setenv("CHROMIUM_EXECUTABLE_PATH", "/usr/bin/chromium-browser")

        with patch("pathlib.Path.read_text", return_value="// script"):
            session = await start_recording("https://example.com")
        try:
            call_kwargs = mock_pw.chromium.launch.call_args
            assert call_kwargs.kwargs.get("executable_path") == "/usr/bin/chromium-browser"
        finally:
            _eject(session.session_id)
