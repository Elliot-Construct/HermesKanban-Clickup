from __future__ import annotations

from hermes_clickup_sync.metadata import upsert_managed_section
from hermes_clickup_sync.models import TaskSnapshot
from hermes_clickup_sync.service import SyncService
from hermes_clickup_sync.state import StateStore


class FakeHermes:
    def __init__(self, tasks):
        self.tasks = tasks
        self.deleted = []
        self.created = []

    def list_boards(self):
        return [{"slug": "board-a", "name": "Board A"}]

    def get_board(self, board):
        return {"columns": [{"name": "todo", "tasks": list(self.tasks)}]}

    def create_task(self, board, payload):
        self.created.append((board, payload))
        task = {"id": "new-hermes", "title": payload["title"], "body": payload.get("body", ""), "status": "todo", "priority": payload.get("priority", 0)}
        self.tasks.append(task)
        return task

    def update_task(self, board, task_id, payload):
        for task in self.tasks:
            if task["id"] == task_id:
                task.update(payload)
                return task
        raise AssertionError("task not found")

    def task_exists(self, board, task_id):
        return any(task["id"] == task_id for task in self.tasks)

    def delete_task(self, board, task_id):
        self.deleted.append((board, task_id))
        self.tasks[:] = [task for task in self.tasks if task["id"] != task_id]


class FakeClickUp:
    def __init__(self, tasks):
        self.tasks = tasks
        self.deleted = []
        self.created = []

    def list_folders(self, space_id):
        return [{"id": "folder-1", "name": "Hermes"}]

    def create_folder(self, space_id, name):
        raise AssertionError("folder should already exist")

    def list_lists(self, folder_id):
        return [{"id": "list-1", "name": "Board A"}]

    def create_list(self, folder_id, name):
        raise AssertionError("list should already exist")

    def list_tasks(self, list_id):
        return list(self.tasks)

    def create_task(self, list_id, **kwargs):
        self.created.append((list_id, kwargs))
        task = {"id": "new-clickup", "name": kwargs["name"], "description": kwargs["body"], "status": {"status": kwargs["status"]}, "priority": None}
        self.tasks.append(task)
        return task

    def update_task(self, task_id, payload):
        for task in self.tasks:
            if task["id"] == task_id:
                task.update(payload)
                return task
        raise AssertionError("task not found")

    def task_exists(self, task_id):
        return any(task["id"] == task_id for task in self.tasks)

    def delete_task(self, task_id):
        self.deleted.append(task_id)
        self.tasks[:] = [task for task in self.tasks if task["id"] != task_id]


def make_service(tmp_path, hermes, clickup):
    state = StateStore(tmp_path / "sync.db")
    service = SyncService(
        hermes=hermes,
        clickup=clickup,
        state=state,
        clickup_space_id="space-1",
        folder_name="Hermes",
        status_map={"todo": "TODO", "done": "DONE", "archived": "ARCHIVED"},
    )
    return service, state


def test_deleting_linked_hermes_task_deletes_clickup_counterpart(tmp_path):
    description = upsert_managed_section("body", board="board-a", task_id="h1", agent=None, run_id=None)
    clickup = FakeClickUp([{"id": "c1", "name": "Task", "description": description, "status": {"status": "TODO"}, "priority": None}])
    hermes = FakeHermes([])
    service, state = make_service(tmp_path, hermes, clickup)
    state.upsert_board_mapping("board-a", "list-1")
    state.upsert_task_mapping("board-a", "h1", "list-1", "c1", TaskSnapshot("Task", "body", "todo", 0))

    service.run_once()

    assert clickup.deleted == ["c1"]
    assert state.get_task_mapping("board-a", "h1") is None


def test_deleting_linked_clickup_task_deletes_hermes_counterpart(tmp_path):
    hermes_task = {"id": "h1", "title": "Task", "body": "body", "status": "todo", "priority": 0}
    hermes = FakeHermes([hermes_task])
    clickup = FakeClickUp([])
    service, state = make_service(tmp_path, hermes, clickup)
    state.upsert_board_mapping("board-a", "list-1")
    state.upsert_task_mapping("board-a", "h1", "list-1", "c1", TaskSnapshot("Task", "body", "todo", 0))

    service.run_once()

    assert hermes.deleted == [("board-a", "h1")]
    assert clickup.created == []
    assert state.get_task_mapping("board-a", "h1") is None


def test_unlinked_clickup_task_is_still_adopted_not_deleted(tmp_path):
    clickup = FakeClickUp([{"id": "c-new", "name": "New Task", "description": "human text", "status": {"status": "TODO"}, "priority": None}])
    hermes = FakeHermes([])
    service, _ = make_service(tmp_path, hermes, clickup)

    service.run_once()

    assert len(hermes.created) == 1
    assert clickup.deleted == []
