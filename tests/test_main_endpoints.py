import json
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

import executor.main as main_module


class DummyBrowserManager:
    def __init__(self, is_running=True):
        self.is_running = is_running
        self.available_browsers = ["chromium", "firefox"]
        self.default_browser = "chromium"


def test_health_happy_path(monkeypatch):
    monkeypatch.setattr(main_module, "get_browser_manager", lambda: DummyBrowserManager(is_running=True))

    client = TestClient(main_module.app)
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "browsers": ["chromium", "firefox"],
        "default_browser": "chromium",
    }


def test_health_degraded_when_manager_not_running(monkeypatch):
    monkeypatch.setattr(main_module, "get_browser_manager", lambda: DummyBrowserManager(is_running=False))

    client = TestClient(main_module.app)
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "degraded"


def test_browsers_endpoint_maps_browser_info(monkeypatch):
    monkeypatch.setattr(main_module, "get_browser_manager", lambda: DummyBrowserManager())

    def fake_browser_info(browser_id):
        return {
            "id": browser_id,
            "name": browser_id.title(),
            "headless": browser_id.endswith("headless"),
        }

    monkeypatch.setattr(main_module, "get_browser_info", fake_browser_info)

    client = TestClient(main_module.app)
    response = client.get("/browsers")

    assert response.status_code == 200
    body = response.json()
    assert body["default"] == "chromium"
    assert body["browsers"][0]["id"] == "chromium"
    assert body["browsers"][1]["id"] == "firefox"


def test_execute_sync_happy_path(monkeypatch):
    events = [
        {"type": "started"},
        {"type": "completed", "status": "passed"},
    ]

    async def fake_execute_test(_manager, _request, callback):
        for event in events:
            await callback(event)
        return {"status": "passed", "steps": 2}

    monkeypatch.setattr(main_module, "get_browser_manager", lambda: DummyBrowserManager())
    monkeypatch.setattr(main_module, "execute_test", fake_execute_test)

    client = TestClient(main_module.app)
    response = client.post(
        "/execute/sync",
        json={
            "test_id": "t-1",
            "base_url": "https://example.com",
            "steps": [{"action": "navigate", "value": "/"}],
            "options": {"timeout": 5000},
        },
    )

    assert response.status_code == 200
    assert response.json()["result"]["status"] == "passed"
    assert response.json()["events"] == events


def test_execute_stream_happy_path(monkeypatch):
    async def fake_execute_test(_manager, _request, callback):
        await callback({"type": "started"})
        await callback({"type": "step_completed", "status": "passed"})

    monkeypatch.setattr(main_module, "get_browser_manager", lambda: DummyBrowserManager())
    monkeypatch.setattr(main_module, "execute_test", fake_execute_test)

    client = TestClient(main_module.app)
    response = client.post(
        "/execute",
        json={
            "test_id": "stream-1",
            "base_url": "https://example.com",
            "steps": [{"action": "navigate", "value": "/"}],
        },
    )

    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]
    lines = [line for line in response.text.splitlines() if line.startswith("data: ")]
    parsed = [json.loads(line[len("data: "):]) for line in lines]
    assert parsed[0]["type"] == "started"
    assert parsed[1]["type"] == "step_completed"


def test_execute_stream_error_path(monkeypatch):
    async def fake_execute_test(_manager, _request, _callback):
        raise RuntimeError("boom")

    monkeypatch.setattr(main_module, "get_browser_manager", lambda: DummyBrowserManager())
    monkeypatch.setattr(main_module, "execute_test", fake_execute_test)

    client = TestClient(main_module.app)
    response = client.post(
        "/execute",
        json={
            "test_id": "stream-err",
            "base_url": "https://example.com",
            "steps": [{"action": "navigate", "value": "/"}],
        },
    )

    assert response.status_code == 200
    lines = [line for line in response.text.splitlines() if line.startswith("data: ")]
    parsed = [json.loads(line[len("data: "):]) for line in lines]
    assert parsed[-1]["type"] == "error"
    assert "boom" in parsed[-1]["error"]


def test_recorder_stop_not_found(monkeypatch):
    monkeypatch.setattr(main_module, "stop_recording", AsyncMock(side_effect=ValueError("Session not found")))

    client = TestClient(main_module.app)
    response = client.post("/recorder/stop", json={"session_id": "missing"})

    assert response.status_code == 404
    assert response.json()["detail"] == "Session not found"


def test_recorder_get_events_happy_and_sad(monkeypatch):
    class Session:
        events = [{"type": "click"}, {"type": "type"}]

    monkeypatch.setattr(main_module, "get_session", lambda session_id: Session() if session_id == "ok" else None)

    client = TestClient(main_module.app)

    ok_response = client.get("/recorder/events/ok")
    assert ok_response.status_code == 200
    assert ok_response.json()["count"] == 2

    missing_response = client.get("/recorder/events/missing")
    assert missing_response.status_code == 404
    assert missing_response.json()["detail"] == "Session not found"
