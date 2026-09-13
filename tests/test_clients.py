from __future__ import annotations

import json

import httpx

from hermes_clickup_sync.clickup import ClickUpClient
from hermes_clickup_sync.hermes import HermesClient


def test_hermes_board_requests_archived_tasks_and_session_header():
    seen = {}

    def handler(request: httpx.Request):
        seen["url"] = str(request.url)
        seen["token"] = request.headers.get("X-Hermes-Session-Token")
        return httpx.Response(200, json={"columns": []})

    http = httpx.Client(base_url="http://hermes.local", transport=httpx.MockTransport(handler))
    client = HermesClient("http://hermes.local", session_token="session-token", http=http)

    client.get_board("board-a")

    assert "board=board-a" in seen["url"]
    assert "include_archived=true" in seen["url"]
    assert seen["token"] == "session-token"


def test_hermes_get_task_returns_none_on_404():
    http = httpx.Client(base_url="http://hermes.local", transport=httpx.MockTransport(lambda request: httpx.Response(404)))
    client = HermesClient("http://hermes.local", http=http)
    assert client.get_task("board-a", "missing") is None


def test_clickup_get_task_returns_none_on_404():
    http = httpx.Client(base_url="https://api.clickup.com", transport=httpx.MockTransport(lambda request: httpx.Response(404)))
    client = ClickUpClient("token", http=http)
    assert client.get_task("missing") is None


def test_clickup_reads_request_markdown_descriptions():
    seen = []

    def handler(request: httpx.Request):
        seen.append(str(request.url))
        if "/list/" in request.url.path:
            return httpx.Response(200, json={"tasks": []})
        return httpx.Response(200, json={"id": "task-1"})

    http = httpx.Client(base_url="https://api.clickup.com", transport=httpx.MockTransport(handler))
    client = ClickUpClient("token", http=http)

    client.list_tasks("list-1")
    client.get_task("task-1")

    assert all("include_markdown_description=true" in url for url in seen)


def test_clickup_update_translates_markdown_description_to_markdown_content():
    seen = {}

    def handler(request: httpx.Request):
        seen["payload"] = json.loads(request.content.decode())
        return httpx.Response(200, json={"id": "task-1"})

    http = httpx.Client(base_url="https://api.clickup.com", transport=httpx.MockTransport(handler))
    client = ClickUpClient("token", http=http)

    client.update_task("task-1", {"name": "Task", "markdown_description": "**body**"})

    assert seen["payload"] == {"name": "Task", "markdown_content": "**body**"}


def test_clickup_delete_uses_delete_endpoint():
    seen = {}

    def handler(request: httpx.Request):
        seen["method"] = request.method
        seen["path"] = request.url.path
        return httpx.Response(204)

    http = httpx.Client(base_url="https://api.clickup.com", transport=httpx.MockTransport(handler))
    client = ClickUpClient("token", http=http)

    client.delete_task("task-1")

    assert seen == {"method": "DELETE", "path": "/api/v2/task/task-1"}
