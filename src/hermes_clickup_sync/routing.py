from __future__ import annotations

from typing import Any


def live_task_count(board_payload: dict[str, Any]) -> int:
    return sum(
        len(column.get("tasks", []))
        for column in board_payload.get("columns", [])
        if column.get("name") != "archived"
    )


def board_payload_matches_listing(board_meta: dict[str, Any], board_payload: dict[str, Any]) -> bool:
    expected = board_meta.get("total")
    if expected is None:
        return True
    try:
        expected_count = int(expected)
    except (TypeError, ValueError):
        return True
    return live_task_count(board_payload) == expected_count
