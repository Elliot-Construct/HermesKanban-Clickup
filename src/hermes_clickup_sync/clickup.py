from __future__ import annotations

from typing import Any

import httpx

from .metadata import upsert_managed_section


class ClickUpClient:
    def __init__(self, token: str, *, http: httpx.Client | None = None, timeout: float = 15.0):
        headers = {"Authorization": token, "Content-Type": "application/json"}
        self.http = http or httpx.Client(base_url="https://api.clickup.com", headers=headers, timeout=timeout)
        if http is not None:
            self.http.headers.update(headers)

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        response = self.http.request(method, path, **kwargs)
        response.raise_for_status()
        return response.json()

    def list_folders(self, space_id: str) -> list[dict[str, Any]]:
        return self._request("GET", f"/api/v2/space/{space_id}/folder", params={"archived": "false"}).get("folders", [])

    def create_folder(self, space_id: str, name: str) -> dict[str, Any]:
        return self._request("POST", f"/api/v2/space/{space_id}/folder", json={"name": name})

    def list_lists(self, folder_id: str) -> list[dict[str, Any]]:
        return self._request("GET", f"/api/v2/folder/{folder_id}/list", params={"archived": "false"}).get("lists", [])

    def create_list(self, folder_id: str, name: str) -> dict[str, Any]:
        return self._request("POST", f"/api/v2/folder/{folder_id}/list", json={"name": name})

    def list_tasks(self, list_id: str) -> list[dict[str, Any]]:
        tasks: list[dict[str, Any]] = []
        page = 0
        while True:
            data = self._request(
                "GET",
                f"/api/v2/list/{list_id}/task",
                params={
                    "archived": "false",
                    "include_closed": "true",
                    "include_markdown_description": "true",
                    "page": page,
                },
            )
            batch = data.get("tasks", [])
            tasks.extend(batch)
            if len(batch) < 100:
                break
            page += 1
        return tasks

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        response = self.http.get(
            f"/api/v2/task/{task_id}",
            params={"include_markdown_description": "true"},
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()

    def task_exists(self, task_id: str) -> bool:
        return self.get_task(task_id) is not None

    def create_task(
        self,
        list_id: str,
        *,
        name: str,
        body: str,
        status: str,
        priority: int,
        board: str,
        hermes_task_id: str,
        agent: str | None,
        run_id: str | None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "name": name,
            "markdown_description": upsert_managed_section(
                body,
                board=board,
                task_id=hermes_task_id,
                agent=agent,
                run_id=run_id,
            ),
            "status": status,
        }
        if 1 <= priority <= 4:
            payload["priority"] = priority
        return self._request("POST", f"/api/v2/list/{list_id}/task", json=payload)

    def update_task(self, task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        payload = dict(payload)
        if "markdown_description" in payload:
            payload["markdown_content"] = payload.pop("markdown_description")
        return self._request("PUT", f"/api/v2/task/{task_id}", json=payload)

    def list_comments(self, task_id: str) -> list[dict[str, Any]]:
        comments: list[dict[str, Any]] = []
        params: dict[str, Any] = {}
        while True:
            data = self._request("GET", f"/api/v2/task/{task_id}/comment", params=params)
            batch = data.get("comments", [])
            comments.extend(batch)
            if len(batch) < 25:
                break
            last = batch[-1]
            if not last.get("id") or not last.get("date"):
                break
            params = {"start": last["date"], "start_id": last["id"]}
        return comments

    def add_comment(self, task_id: str, text: str) -> str | None:
        data = self._request(
            "POST",
            f"/api/v2/task/{task_id}/comment",
            json={"comment_text": text, "notify_all": False},
        )
        ident = data.get("id")
        if ident is None and isinstance(data.get("comment"), dict):
            ident = data["comment"].get("id")
        return None if ident is None else str(ident)

    def delete_task(self, task_id: str) -> None:
        response = self.http.delete(f"/api/v2/task/{task_id}")
        response.raise_for_status()
