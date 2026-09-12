import json

import httpx

from hermes_clickup_sync.clickup import ClickUpClient
from hermes_clickup_sync.hermes import HermesClient


def test_hermes_task_detail_exposes_comments_and_runs():
    def handler(request):
        return httpx.Response(
            200,
            json={
                "task": {"id": "h1"},
                "comments": [{"id": 1}],
                "runs": [{"id": 2}],
            },
        )

    http = httpx.Client(
        base_url="http://hermes.local", transport=httpx.MockTransport(handler)
    )
    detail = HermesClient("http://hermes.local", http=http).get_task_detail(
        "board", "h1"
    )

    assert detail["comments"][0]["id"] == 1
    assert detail["runs"][0]["id"] == 2


def test_hermes_add_comment_posts_author_and_body():
    seen = {}

    def handler(request):
        seen["method"] = request.method
        seen["url"] = str(request.url)
        seen["json"] = request.read().decode()
        return httpx.Response(200, json={"ok": True})

    http = httpx.Client(
        base_url="http://hermes.local", transport=httpx.MockTransport(handler)
    )
    HermesClient("http://hermes.local", http=http).add_comment(
        "board",
        "h1",
        author="clickup:9:Operator",
        body="Do this",
    )

    assert seen["method"] == "POST"
    assert "/api/plugins/kanban/tasks/h1/comments" in seen["url"]
    assert json.loads(seen["json"]) == {
        "author": "clickup:9:Operator",
        "body": "Do this",
    }


def test_clickup_lists_all_comment_pages_and_adds_comment():
    calls = []

    def handler(request):
        calls.append((request.method, str(request.url), request.read().decode()))
        if request.method == "GET" and "start_id=" not in str(request.url):
            return httpx.Response(
                200,
                json={
                    "comments": [
                        {
                            "id": str(i),
                            "date": str(1000 - i),
                            "comment": [{"text": str(i)}],
                        }
                        for i in range(25)
                    ]
                },
            )
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "comments": [
                        {
                            "id": "older",
                            "date": "1",
                            "comment": [{"text": "old"}],
                        }
                    ]
                },
            )
        return httpx.Response(200, json={"id": 777})

    http = httpx.Client(
        base_url="https://api.clickup.com", transport=httpx.MockTransport(handler)
    )
    client = ClickUpClient("token", http=http)

    comments = client.list_comments("c1")

    assert len(comments) == 26
    assert "start_id=24" in calls[1][1]
    assert client.add_comment("c1", "hello") == "777"
    assert json.loads(calls[-1][2]) == {
        "comment_text": "hello",
        "notify_all": False,
    }
