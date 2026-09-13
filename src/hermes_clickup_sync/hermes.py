from __future__ import annotations

from typing import Any

import httpx

from .routing import board_payload_matches_listing, live_task_count


class HermesClient:
    def __init__(
        self,
        base_url: str,
        *,
        session_token: str | None = None,
        http: httpx.Client | None = None,
        timeout: float = 15.0,
    ):
        self.base_url = base_url.rstrip("/")
        self._board_totals: dict[str, int] = {}
        headers = {}
        if session_token:
            headers["X-Hermes-Session-Token"] = session_token
        self.http = http or httpx.Client(base_url=self.base_url, headers=headers, timeout=timeout)
        if http is not None and session_token:
            self.http.headers["X-Hermes-Session-Token"] = session_token

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        response = self.http.request(method, path, **kwargs)
        response.raise_for_status()
        return response.json()

    def list_boards(self) -> list[dict[str, Any]]:
        boards = self._request("GET", "/api/plugins/kanban/boards").get("boards", [])
        self._board_totals = {}
        for board in boards:
            slug = str(board.get("slug") or "")
            try:
                total = int(board["total"])
            except (KeyError, TypeError, ValueError):
                continue
            if slug:
                self._board_totals[slug] = total
        return boards

    def get_board(self, board: str) -> dict[str, Any]:
        payload = self._request(
            "GET",
            "/api/plugins/kanban/board",
            params={"board": board, "include_archived": "true"},
        )
        expected = self._board_totals.get(board)
        if expected is not None and not board_payload_matches_listing({"total": expected}, payload):
            actual = live_task_count(payload)
            raise RuntimeError(
                f"Hermes board routing mismatch for {board!r}: board listing reports "
                f"{expected} live task(s), but the board endpoint returned {actual}. "
                "Refusing to sync this cycle to prevent cross-board task duplication. "
                "Check whether the Hermes dashboard process has a board-specific database override."
            )
        return payload

    def get_task_detail(self, board: str, task_id: str) -> dict[str, Any] | None:
        response = self.http.get(
            f"/api/plugins/kanban/tasks/{task_id}",
            params={"board": board},
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()

    def get_task(self, board: str, task_id: str) -> dict[str, Any] | None:
        detail = self.get_task_detail(board, task_id)
        return detail.get("task") if detail else None

    def task_exists(self, board: str, task_id: str) -> bool:
        return self.get_task(board, task_id) is not None

    def create_task(self, board: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request(
            "POST",
            "/api/plugins/kanban/tasks",
            params={"board": board},
            json=payload,
        )["task"]

    def update_task(self, board: str, task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request(
            "PATCH",
            f"/api/plugins/kanban/tasks/{task_id}",
            params={"board": board},
            json=payload,
        )["task"]

    def add_comment(self, board: str, task_id: str, *, author: str, body: str) -> None:
        self._request(
            "POST",
            f"/api/plugins/kanban/tasks/{task_id}/comments",
            params={"board": board},
            json={"author": author, "body": body},
        )

    def delete_task(self, board: str, task_id: str) -> None:
        self._request(
            "DELETE",
            f"/api/plugins/kanban/tasks/{task_id}",
            params={"board": board},
        )
