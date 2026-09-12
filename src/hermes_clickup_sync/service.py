from __future__ import annotations

import logging
from typing import Any

from .metadata import extract_anchor, strip_managed_section, upsert_managed_section
from .models import TaskSnapshot
from .reconcile import decide_direction
from .state import StateStore

log = logging.getLogger(__name__)


class SyncService:
    def __init__(self, *, hermes, clickup, state: StateStore, clickup_space_id: str, folder_name: str, status_map: dict[str, str], dry_run: bool = False):
        self.hermes = hermes
        self.clickup = clickup
        self.state = state
        self.clickup_space_id = clickup_space_id
        self.folder_name = folder_name
        self.status_map = status_map
        self.reverse_status_map = {v.casefold(): k for k, v in status_map.items()}
        self.dry_run = dry_run

    def _remember_board(self, board_slug: str, list_id: str) -> None:
        if not self.dry_run:
            self.state.upsert_board_mapping(board_slug, list_id)

    def _remember_task(self, board_slug: str, hermes_task_id: str, list_id: str, clickup_task_id: str, snapshot: TaskSnapshot) -> None:
        if not self.dry_run:
            self.state.upsert_task_mapping(board_slug, hermes_task_id, list_id, clickup_task_id, snapshot)

    def _forget_task(self, board_slug: str, hermes_task_id: str) -> None:
        if not self.dry_run:
            self.state.delete_task_mapping(board_slug, hermes_task_id)

    def _ensure_folder(self) -> dict[str, Any]:
        for folder in self.clickup.list_folders(self.clickup_space_id):
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
                self._remember_board(board["slug"], str(item["id"]))
                return item
        if self.dry_run:
            raise RuntimeError(f"ClickUp list {wanted!r} does not exist in dry-run mode")
        item = self.clickup.create_list(folder_id, wanted)
        self._remember_board(board["slug"], str(item["id"]))
        return item

    @staticmethod
    def _hermes_tasks(board_payload: dict[str, Any]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for column in board_payload.get("columns", []):
            out.extend(column.get("tasks", []))
        return out

    @staticmethod
    def _clickup_description(task: dict[str, Any]) -> str:
        return task.get("markdown_description") or task.get("description") or task.get("text_content") or ""

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
        return TaskSnapshot(task.get("title") or "", task.get("body") or "", task.get("status") or "todo", int(task.get("priority") or 0))

    def _clickup_snapshot(self, task: dict[str, Any]) -> TaskSnapshot:
        return TaskSnapshot(
            task.get("name") or "",
            strip_managed_section(self._clickup_description(task)),
            self._status_from_clickup(task),
            self._priority_from_clickup(task),
        )

    def _clickup_status(self, hermes_status: str) -> str:
        if hermes_status not in self.status_map:
            raise ValueError(f"Unmapped Hermes status: {hermes_status!r}")
        return self.status_map[hermes_status]

    def _create_clickup_from_hermes(self, list_id: str, board_slug: str, task: dict[str, Any]) -> dict[str, Any]:
        snapshot = self._hermes_snapshot(task)
        if self.dry_run:
            log.info("Would create ClickUp task for Hermes %s/%s", board_slug, task["id"])
            return {}
        created = self.clickup.create_task(list_id, name=snapshot.title, body=snapshot.body, status=self._clickup_status(snapshot.status), priority=snapshot.priority, board=board_slug, hermes_task_id=task["id"], agent=task.get("assignee"), run_id=None)
        self._remember_task(board_slug, task["id"], list_id, str(created["id"]), snapshot)
        return created

    def _create_hermes_from_clickup(self, board_slug: str, list_id: str, task: dict[str, Any]) -> dict[str, Any]:
        snapshot = self._clickup_snapshot(task)
        if self.dry_run:
            log.info("Would create Hermes task from ClickUp %s", task["id"])
            return {}
        created = self.hermes.create_task(board_slug, {"title": snapshot.title, "body": snapshot.body, "priority": snapshot.priority})
        if snapshot.status != created.get("status"):
            created = self.hermes.update_task(board_slug, created["id"], {"status": snapshot.status})
        self._remember_task(board_slug, created["id"], list_id, str(task["id"]), self._hermes_snapshot(created))
        managed = upsert_managed_section(snapshot.body, board=board_slug, task_id=created["id"], agent=created.get("assignee"), run_id=None)
        self.clickup.update_task(str(task["id"]), {"markdown_description": managed})
        return created

    def _sync_pair(self, board_slug: str, list_id: str, htask: dict[str, Any], ctask: dict[str, Any]) -> None:
        mapping = self.state.get_task_mapping(board_slug, htask["id"])
        if mapping is None:
            self._remember_task(board_slug, htask["id"], list_id, str(ctask["id"]), self._hermes_snapshot(htask))
            return
        hs, cs = self._hermes_snapshot(htask), self._clickup_snapshot(ctask)
        direction = decide_direction(mapping.last_synced, hs, cs)
        if direction == "noop":
            if hs == cs and mapping.last_synced != hs:
                self._remember_task(board_slug, htask["id"], list_id, str(ctask["id"]), hs)
            return
        if direction == "clickup_to_hermes":
            if not self.dry_run:
                hs = self._hermes_snapshot(self.hermes.update_task(board_slug, htask["id"], {"title": cs.title, "body": cs.body, "status": cs.status, "priority": cs.priority}))
            else:
                log.info("Would update Hermes task %s/%s from ClickUp", board_slug, htask["id"])
                hs = cs
        else:
            if direction == "conflict":
                log.warning("Conflict on %s/%s; preferring Hermes state", board_slug, htask["id"])
            if not self.dry_run:
                payload: dict[str, Any] = {
                    "name": hs.title,
                    "markdown_description": upsert_managed_section(hs.body, board=board_slug, task_id=htask["id"], agent=htask.get("assignee"), run_id=None),
                    "status": self._clickup_status(hs.status),
                }
                if 1 <= hs.priority <= 4:
                    payload["priority"] = hs.priority
                self.clickup.update_task(str(ctask["id"]), payload)
            else:
                log.info("Would update ClickUp task %s from Hermes %s/%s", ctask["id"], board_slug, htask["id"])
        self._remember_task(board_slug, htask["id"], list_id, str(ctask["id"]), hs)

    def _apply_mapped_deletions(self, board_slug: str, h_by_id: dict[str, dict[str, Any]], c_by_id: dict[str, dict[str, Any]]) -> tuple[set[str], set[str]]:
        deleted_h: set[str] = set()
        deleted_c: set[str] = set()
        for mapping in self.state.list_task_mappings(board_slug):
            htask = h_by_id.get(mapping.hermes_task_id)
            ctask = c_by_id.get(mapping.clickup_task_id)

            if htask is None:
                htask = self.hermes.get_task(board_slug, mapping.hermes_task_id)
                if htask is not None:
                    h_by_id[mapping.hermes_task_id] = htask
            if ctask is None:
                ctask = self.clickup.get_task(mapping.clickup_task_id)
                if ctask is not None:
                    c_by_id[mapping.clickup_task_id] = ctask

            if htask is not None and ctask is not None:
                continue
            if htask is None and ctask is not None:
                if self.dry_run:
                    log.info("Would delete ClickUp task %s because Hermes %s/%s was deleted", mapping.clickup_task_id, board_slug, mapping.hermes_task_id)
                else:
                    self.clickup.delete_task(mapping.clickup_task_id)
                self._forget_task(board_slug, mapping.hermes_task_id)
                deleted_c.add(mapping.clickup_task_id)
                continue
            if htask is not None and ctask is None:
                if self.dry_run:
                    log.info("Would delete Hermes task %s/%s because ClickUp %s was deleted", board_slug, mapping.hermes_task_id, mapping.clickup_task_id)
                else:
                    self.hermes.delete_task(board_slug, mapping.hermes_task_id)
                self._forget_task(board_slug, mapping.hermes_task_id)
                deleted_h.add(mapping.hermes_task_id)
                continue
            self._forget_task(board_slug, mapping.hermes_task_id)
        return deleted_h, deleted_c

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

            deleted_h, deleted_c = self._apply_mapped_deletions(board_slug, h_by_id, c_by_id)
            for task_id in deleted_h:
                h_by_id.pop(task_id, None)
            for task_id in deleted_c:
                c_by_id.pop(task_id, None)
            clickup_tasks = [t for t in clickup_tasks if str(t["id"]) not in deleted_c]

            c_by_anchor: dict[str, dict[str, Any]] = {}
            for task in clickup_tasks:
                anchor = extract_anchor(self._clickup_description(task))
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
                    self._remember_task(board_slug, h_id, list_id, str(ctask["id"]), self._hermes_snapshot(htask))
                self._sync_pair(board_slug, list_id, htask, ctask)

            for ctask in clickup_tasks:
                c_id = str(ctask["id"])
                if c_id in linked_clickup_ids:
                    continue
                anchor = extract_anchor(self._clickup_description(ctask))
                if anchor:
                    hermes_id = str(anchor.get("task"))
                    if not self.hermes.task_exists(board_slug, hermes_id):
                        if self.dry_run:
                            log.info("Would delete anchored ClickUp task %s because Hermes %s/%s is missing", c_id, board_slug, hermes_id)
                        else:
                            self.clickup.delete_task(c_id)
                        self._forget_task(board_slug, hermes_id)
                    continue
                self._create_hermes_from_clickup(board_slug, list_id, ctask)
