from __future__ import annotations

from hermes_clickup_sync.metadata import upsert_managed_section
from hermes_clickup_sync.models import TaskSnapshot
from hermes_clickup_sync.service import SyncService
from hermes_clickup_sync.state import StateStore


class Hermes:
    def __init__(self, tasks):
        self.tasks = tasks
        self.updated = []

    def list_boards(self):
        return [{"slug": "board-a", "name": "Board A"}]

    def get_board(self, board):
        return {"columns": [{"name": "todo", "tasks": list(self.tasks)}]}

    def get_task(self, board, task_id):
        return next((task for task in self.tasks if task["id"] == task_id), None)

    def task_exists(self, board, task_id):
        return self.get_task(board, task_id) is not None

    def create_task(self, board, payload):
        task = {"id": "h-created", "title": payload["title"], "body": payload.get("body", ""), "status": "todo", "priority": payload.get("priority", 0)}
        self.tasks.append(task)
        return task

    def update_task(self, board, task_id, payload):
        task = self.get_task(board, task_id)
        task.update(payload)
        self.updated.append((board, task_id, payload))
        return task

    def delete_task(self, board, task_id):
        self.tasks[:] = [task for task in self.tasks if task["id"] != task_id]


class ClickUp:
    def __init__(self, tasks=None):
        self.tasks = tasks or []
        self.created = []
        self.updated = []

    def list_folders(self, space_id):
        return [{"id": "folder-1", "name": "Hermes"}]

    def create_folder(self, space_id, name):
        raise AssertionError

    def list_lists(self, folder_id):
        return [{"id": "list-1", "name": "Board A"}]

    def create_list(self, folder_id, name):
        raise AssertionError

    def list_tasks(self, list_id):
        return list(self.tasks)

    def get_task(self, task_id):
        return next((task for task in self.tasks if task["id"] == task_id), None)

    def task_exists(self, task_id):
        return self.get_task(task_id) is not None

    def create_task(self, list_id, **kwargs):
        self.created.append((list_id, kwargs))
        task = {
            "id": "c-created",
            "name": kwargs["name"],
            "description": upsert_managed_section(kwargs["body"], board=kwargs["board"], task_id=kwargs["hermes_task_id"], agent=kwargs["agent"], run_id=kwargs["run_id"]),
            "status": {"status": kwargs["status"]},
            "priority": None,
        }
        self.tasks.append(task)
        return task

    def update_task(self, task_id, payload):
        task = self.get_task(task_id)
        self.updated.append((task_id, payload))
        if "name" in payload:
            task["name"] = payload["name"]
        if "markdown_description" in payload:
            task["description"] = payload["markdown_description"]
        if "status" in payload:
            task["status"] = {"status": payload["status"]}
        if "priority" in payload:
            task["priority"] = payload["priority"]
        return task

    def delete_task(self, task_id):
        self.tasks[:] = [task for task in self.tasks if task["id"] != task_id]


def service(tmp_path, hermes, clickup):
    return SyncService(
        hermes=hermes,
        clickup=clickup,
        state=StateStore(tmp_path / "sync.db"),
        clickup_space_id="space-1",
        folder_name="Hermes",
        status_map={"todo": "TODO", "ready": "READY", "running": "RUNNING", "done": "DONE", "archived": "ARCHIVED"},
    )


def test_existing_hermes_task_creates_clickup_card(tmp_path):
    hermes = Hermes([{"id": "h1", "title": "Build thing", "body": "details", "status": "todo", "priority": 0, "assignee": "worker"}])
    clickup = ClickUp()

    service(tmp_path, hermes, clickup).run_once()

    assert len(clickup.created) == 1
    assert clickup.created[0][1]["name"] == "Build thing"
    assert clickup.created[0][1]["status"] == "TODO"


def test_clickup_status_change_updates_hermes(tmp_path):
    description = upsert_managed_section("details", board="board-a", task_id="h1", agent=None, run_id=None)
    htask = {"id": "h1", "title": "Build thing", "body": "details", "status": "todo", "priority": 0}
    ctask = {"id": "c1", "name": "Build thing", "description": description, "status": {"status": "READY"}, "priority": None}
    hermes = Hermes([htask])
    clickup = ClickUp([ctask])
    svc = service(tmp_path, hermes, clickup)
    svc.state.upsert_task_mapping("board-a", "h1", "list-1", "c1", TaskSnapshot("Build thing", "details", "todo", 0))

    svc.run_once()

    assert hermes.updated[-1][2]["status"] == "ready"
