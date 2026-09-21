from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .models import TaskSnapshot


@dataclass(frozen=True)
class TaskMapping:
    board_slug: str
    hermes_task_id: str
    clickup_list_id: str
    clickup_task_id: str
    last_synced: TaskSnapshot


class StateStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS board_map (
                    board_slug TEXT PRIMARY KEY,
                    clickup_list_id TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS task_map (
                    board_slug TEXT NOT NULL,
                    hermes_task_id TEXT NOT NULL,
                    clickup_list_id TEXT NOT NULL,
                    clickup_task_id TEXT NOT NULL UNIQUE,
                    last_synced_json TEXT NOT NULL,
                    PRIMARY KEY (board_slug, hermes_task_id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS activity_map (
                    board_slug TEXT NOT NULL,
                    hermes_task_id TEXT NOT NULL,
                    source_kind TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    target_id TEXT,
                    PRIMARY KEY (board_slug, hermes_task_id, source_kind, source_id)
                )
                """
            )

    def upsert_task_mapping(
        self,
        board_slug: str,
        hermes_task_id: str,
        clickup_list_id: str,
        clickup_task_id: str,
        snapshot: TaskSnapshot,
    ) -> None:
        payload = json.dumps(snapshot.__dict__, sort_keys=True)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO task_map(board_slug, hermes_task_id, clickup_list_id, clickup_task_id, last_synced_json)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(board_slug, hermes_task_id) DO UPDATE SET
                    clickup_list_id=excluded.clickup_list_id,
                    clickup_task_id=excluded.clickup_task_id,
                    last_synced_json=excluded.last_synced_json
                """,
                (board_slug, hermes_task_id, clickup_list_id, clickup_task_id, payload),
            )

    def get_task_mapping(self, board_slug: str, hermes_task_id: str) -> TaskMapping | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM task_map WHERE board_slug = ? AND hermes_task_id = ?",
                (board_slug, hermes_task_id),
            ).fetchone()
        if row is None:
            return None
        return self._mapping_from_row(row)

    def list_task_mappings(self, board_slug: str) -> list[TaskMapping]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM task_map WHERE board_slug = ? ORDER BY hermes_task_id",
                (board_slug,),
            ).fetchall()
        return [self._mapping_from_row(row) for row in rows]

    @staticmethod
    def _mapping_from_row(row: sqlite3.Row) -> TaskMapping:
        return TaskMapping(
            board_slug=row["board_slug"],
            hermes_task_id=row["hermes_task_id"],
            clickup_list_id=row["clickup_list_id"],
            clickup_task_id=row["clickup_task_id"],
            last_synced=TaskSnapshot(**json.loads(row["last_synced_json"])),
        )

    def delete_task_mapping(self, board_slug: str, hermes_task_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM task_map WHERE board_slug = ? AND hermes_task_id = ?",
                (board_slug, hermes_task_id),
            )
            conn.execute(
                "DELETE FROM activity_map WHERE board_slug = ? AND hermes_task_id = ?",
                (board_slug, hermes_task_id),
            )

    def mark_activity(
        self,
        board_slug: str,
        hermes_task_id: str,
        source_kind: str,
        source_id: str,
        target_id: str | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO activity_map(board_slug, hermes_task_id, source_kind, source_id, target_id)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(board_slug, hermes_task_id, source_kind, source_id)
                DO UPDATE SET target_id=excluded.target_id
                """,
                (
                    board_slug,
                    hermes_task_id,
                    source_kind,
                    str(source_id),
                    None if target_id is None else str(target_id),
                ),
            )

    def activity_seen(
        self,
        board_slug: str,
        hermes_task_id: str,
        source_kind: str,
        source_id: str,
    ) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT 1 FROM activity_map
                WHERE board_slug = ? AND hermes_task_id = ? AND source_kind = ? AND source_id = ?
                """,
                (board_slug, hermes_task_id, source_kind, str(source_id)),
            ).fetchone()
        return row is not None

    def activity_target(
        self,
        board_slug: str,
        hermes_task_id: str,
        source_kind: str,
        source_id: str,
    ) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT target_id FROM activity_map
                WHERE board_slug = ? AND hermes_task_id = ? AND source_kind = ? AND source_id = ?
                """,
                (board_slug, hermes_task_id, source_kind, str(source_id)),
            ).fetchone()
        return row["target_id"] if row else None

    def upsert_board_mapping(self, board_slug: str, clickup_list_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO board_map(board_slug, clickup_list_id) VALUES (?, ?) "
                "ON CONFLICT(board_slug) DO UPDATE SET clickup_list_id=excluded.clickup_list_id",
                (board_slug, clickup_list_id),
            )

    def get_board_list_id(self, board_slug: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT clickup_list_id FROM board_map WHERE board_slug = ?",
                (board_slug,),
            ).fetchone()
        return row["clickup_list_id"] if row else None
