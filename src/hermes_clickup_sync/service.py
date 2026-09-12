from __future__ import annotations

import logging
from typing import Any

from .metadata import extract_anchor, strip_managed_section, upsert_managed_section
from .models import TaskSnapshot
from .reconcile import decide_direction
from .state import StateStore

log = logging.getLogger(__name__)


class SyncService:
    def __init__(
        self,
        *,
        hermes,
        clickup,
        state: StateStore,
        clickup_space_id: str,
        folder_name: str,
        status_map: dict[str, str],
        dry_run: bool = False,
    ):
        self.hermes = hermes
        self.clickup = clickup
        self.state = state
        self.clickup_space_id = clickup_space_id
        self.folder_name = folder_name
        self.status_map = status_map
        self.reverse_status_map = {v.casefold(): k for k, v in status_map.items()}
        self.dry_run = dry_run

    def _ensure_folder(self) -> dict[str, Any]:
        folders = self.clickup.list_folders(self.clickup_space_id)
        for folder in folders:
            if folder.get("name") == self.folder_name:
                return folder
        if self.dry_run:
            raise RuntimeError(f"ClickUp folder {self.folder_name!r} does not exist in dry-run mode")
        return self.clickup.create_folder(self.clickup_space_id, self.folder_name)

    def _ensure_list(self, folder_id: str, board: dict[str, Any], lists: list[dict[str, Any]]) -> dict[str, Any]:
        mapped = self.state.get_board_list_id(board["slug"])
        if mapped:
            for item in lists:
                if str(item.get("id")) == str(mapped):
                    return item
        wanted = board.get("name") or board["slug"]
        for item in lists:
            if item.get("name") == wanted:
                self.state.upsert_board_mapping(board["slug"], str(item["id"]))
                return item
        if self.dry_run:
            raise RuntimeError(f"ClickUp list {wanted!r} does not exist in dry-run mode")
        item = self.clickup.create_list(folder_id, wanted)
        self.state.upsert_board_mapping(board["slug"], str(item["id"]))
        return item

    @staticmethod
    def _hermes_tasks(board_payload: dict[str, Any]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for column in board_payload.get("columns", []):
            out.extend(column.get("tasks", []))
        return out

    @staticmethod
    def _priority_from_clickup(task: dict[str, Any]) -> int:
        priority = task.get("priority")
        if isinstance(priority, dict):
            priority = priority.get("id")
        try:
            return int(priority or 0)
        except (TypeError, ValueError):
            return 0

    def _status_from_clickup(self, task: dict[str, Any]) -> str:
        status = task.get("status")
        if isinstance(status, dict):
            status = status.get("status")
        raw = str(status or "").casefold()
        if raw not in self.reverse_status_map:
            raise ValueError(f"Unmapped ClickUp status: {status!r}")
        return self.reverse_status_map[raw]

    @staticmethod
    def _hermes_snapshot(task: dict[str, Any]) -> TaskSnapshot:
        return TaskSnapshot(
            title=task.get("title") or "",
            body=task.get("body") or "",
            status=task.get("status") or "todo",
            priority=int(task.get("priority") or 0),
        )

    def _clickup_snapshot(self, task: dict[str, Any]) -> TaskSnapshot:
        return TaskSnapshot(
            title=task.get("name") or "",
            body=strip_managed_section(task.get("description") or task.get("text_content") or ""),
            status=self._status_from_clickup(task),
            priority=self._priority_from_clickup(task),
        )

    def _clickup_status(self, hermes_status: str) -> str:
        try:
            return self.status_map[hermes_status]
        except KeyError as exc:
            raise ValueError(f"Unmapped Hermes status: {hermes_status!r}") from exc

    def _create_clickup_from_hermes(self, list_id: str, board_slug: str, task: dict[str, Any]) -> dict[str, Any]:
        snapshot = self._hermes_snapshot(task)
        if self.dry_run:
            log.info("Would create ClickUp task for Hermes %s/%s", board_slug, task["id"])
            return {}
        created = self.clickup.create_task(
            list_id,
            name=snapshot.title,
            body=snapshot.body,
            status=self._clickup_status(snapshot.status),
            priority=snapshot.priority,
            board=board_slug,
            hermes_task_id=task["id"],
            agent=task.get("assignee"),
            run_id=None,
        )
        self.state.upsert_task_mapping(board_slug, task["id"], list_id, str(created["id"]), snapshot)
        return created

    def _create_hermes_from_clickup(self, board_slug: str, list_id: str, task: dict[str, Any]) -> dict[str, Any]:
        snapshot = self._clickup_snapshot(task)
        if self.dry_run:
            log.info("Would create Hermes task from ClickUp %s", task["id"])
            return {}
        created = self.hermes.create_task(
            board_slug,
            {"title": snapshot.title, "body": snapshot.body, "priority": snapshot.priority},
        )
        if snapshot.status != created.get("status"):
            created = self.hermes.update_task(board_slug, created["id"], {"status": snapshot.status})
        self.state.upsert_task_mapping(board_slug, created["id"], list_id, str(task["id"]), self._hermes_snapshot(created))
        managed = upsert_managed_section(
            snapshot.body,
            board=board_slug,
            task_id=created["id"],
            agent=created.get("assignee"),
            run_id=None,
        )
        self.clickup.update_task(str(task["id"]), {"markdown_description": managed})
        return created

    def _sync_pair(self, board_slug: str, list_id: str, htask: dict[str, Any], ctask: dict[str, Any]) -> None:
        mapping = self.state.get_task_mapping(board_slug, htask["id"])
        if mapping is None:
            base = self._hermes_snapshot(htask)
            self.state.upsert_task_mapping(board_slug, htask["id"], list_id, str(ctask["id"]), base)
            return
        hs = self._hermes_snapshot(htask)
        cs = self._clickup_snapshot(ctask)
        direction = decide_direction(mapping.last_synced, hs, cs)
        if direction == "noop":
            if hs == cs and mapping.last_synced != hs:
                self.state.upsert_task_mapping(board_slug, htask["id"], list_id, str(ctask["id"]), hs)
            return
        if direction == "clickup_to_hermes":
            if not self.dry_run:
                updated = self.hermes.update_task(
                    board_slug,
                    htask["id"],
                    {"title": cs.title, "body": cs.body, "status": cs.status, "priority": cs.priority},
                )
                hs = self._hermes_snapshot(updated)
            else:
                hs = cs
        elif direction == "hermes_to_clickup":
            if not self.dry_run:
                payload: dict[str, Any] = {
                    "name": hs.title,
                    "markdown_description": upsert_managed_section(
                        hs.body,
                        board=board_slug,
                        task_id=htask["id"],
                        agent=htask.get("assignee"),
                        run_id=None,
                    ),
                    "status": self._clickup_status(hs.status),
                }
                if 1 <= hs.priority <= 4:
                    payload["priority"] = hs.priority
                self.clickup.update_task(str(ctask["id"]), payload)
        else:
            # Execution state belongs to Hermes; planning fields use ClickUp only when
            # Hermes did not change them. For v1, whole-task conflicts prefer Hermes.
            log.warning("Conflict on %s/%s; preferring Hermes state", board_slug, htask["id"])
            if not self.dry_run:
                self.clickup.update_task(
                    str(ctask["id"]),
                    {
                        "name": hs.title,
                        "markdown_description": upsert_managed_section(
                            hs.body,
                            board=board_slug,
                            task_id=htask["id"],
                            agent=htask.get("assignee"),
                            run_id=None,
                        ),
                        "status": self._clickup_status(hs.status),
                    },
                )
        self.state.upsert_task_mapping(board_slug, htask["id"], list_id, str(ctask["id"]), hs)

    def run_once(self) -> None:
        folder = self._ensure_folder()
        lists = self.clickup.list_lists(str(folder["id"]))
        for board in self.hermes.list_boards():
            board_slug = board["slug"]
            clickup_list = self._ensure_list(str(folder["id"]), board, lists)
            list_id = str(clickup_list["id"])
            if clickup_list not in lists:
                lists.append(clickup_list)
            hermes_tasks = self._hermes_tasks(self.hermes.get_board(board_slug))
            clickup_tasks = self.clickup.list_tasks(list_id)
            h_by_id = {str(t["id"]): t for t in hermes_tasks}
            c_by_id = {str(t["id"]): t for t in clickup_tasks}
            c_by_anchor: dict[str, dict[str, Any]] = {}
            for task in clickup_tasks:
                anchor = extract_anchor(task.get("description") or "")
                if anchor and anchor.get("board") == board_slug:
                    c_by_anchor[str(anchor["task"])] = task

            linked_clickup_ids: set[str] = set()
            for h_id, htask in h_by_id.items():
                mapping = self.state.get_task_mapping(board_slug, h_id)
                ctask = c_by_id.get(mapping.clickup_task_id) if mapping else None
                if ctask is None:
                    ctask = c_by_anchor.get(h_id)
                if ctask is None:
                    created = self._create_clickup_from_hermes(list_id, board_slug, htask)
                    if created:
                        linked_clickup_ids.add(str(created["id"]))
                    continue
                linked_clickup_ids.add(str(ctask["id"]))
                if mapping is None:
                    self.state.upsert_task_mapping(board_slug, h_id, list_id, str(ctask["id"]), self._hermes_snapshot(htask))
                self._sync_pair(board_slug, list_id, htask, ctask)

            for ctask in clickup_tasks:
                c_id = str(ctask["id"])
                if c_id in linked_clickup_ids:
                    continue
                anchor = extract_anchor(ctask.get("description") or "")
                if anchor:
                    # Anchored task whose Hermes counterpart is absent: do not recreate deleted work.
                    log.warning("ClickUp task %s points to missing Hermes task %s; leaving untouched", c_id, anchor.get("task"))
                    continue
                self._create_hermes_from_clickup(board_slug, list_id, ctask)
