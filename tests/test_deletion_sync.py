from __future__ import annotations

from hermes_clickup_sync.metadata import upsert_managed_section
from hermes_clickup_sync.models import TaskSnapshot
from hermes_clickup_sync.service import SyncService
from hermes_clickup_sync.state import StateStore


class FakeHermes:
    def __init__(self, tasks, listed_ids=None):
        self.tasks = tasks
        self.listed_ids = listed_ids
        self.deleted = []
        self.created = []

    def list_boards(self):
        return [{"slug": "board-a", "name": "Board A"}]

    def get_board(self, board):
        tasks = self.tasks if self.listed_ids is None else [t for t in self.tasks if t["id"] in self.listed_ids]
        return {"columns": [{"name": "todo", "tasks": list(tasks)}]}

    def get_task(self, board, task_id):
        return next((task for task in self.tasks if task["id"] == task_id), None)

    def task_exists(self, board, task_id):
        return self.get_task(board, task_id) is not None

    def create_task(self, board, payload):
        self.created.append((board, payload))
        task = {"id": "new-hermes", "title": payload["title"], "body": payload.get("body", ""), "status": "todo", "priority": payload.get("priority", 0)}
        self.tasks.append(task)
        return task

    def update_task(self, board, task_id, payload):
        task = self.get_task(board, task_id)
        if task is None:
            raise AssertionError("task not found")
        task.update(payload)
        return task

    def delete_task(self, board, task_id):
        self.deleted.append((board, task_id))
        self.tasks[:] = [task for task in self.tasks if task["id"] != task_id]


class FakeClickUp:
    def __init__(self, tasks, listed_ids=None):
        self.tasks = tasks
        self.listed_ids = listed_ids
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
        tasks = self.tasks if self.listed_ids is None else [t for t in self.tasks if t["id"] in self.listed_ids]
        return list(tasks)

    def get_task(self, task_id):
        return next((task for task in self.tasks if task["id"] == task_id), None)

    def task_exists(self, task_id):
        return self.get_task(task_id) is not None

    def create_task(self, list_id, **kwargs):
        self.created.append((list_id, kwargs))
        task = {"id": "new-clickup", "name": kwargs["name"], "description": kwargs["body"], "status": {"status": kwargs["status"]}, "priority": None}
        self.tasks.append(task)
        return task

    def update_task(self, task_id, payload):
        task = self.get_task(task_id)
        if task is None:
            raise AssertionError("task not found")
        if "markdown_description" in payload:
            task["description"] = payload["markdown_description"]
        for key in ("name", "status", "priority"):
            if key in payload:
                task[key] = payload[key]
        return task

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


def linked_clickup(task_id="h1", clickup_id="c1"):
    description = upsert_managed_section("body", board="board-a", task_id=task_id, agent=None, run_id=None)
    return {"id": clickup_id, "name": "Task", "description": description, "status": {"status": "TODO"}, "priority": None}


def test_deleting_linked_hermes_task_deletes_clickup_counterpart(tmp_path):
    clickup = FakeClickUp([linked_clickup()])
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


def test_filtered_clickup_task_is_hydrated_not_deleted_or_duplicated(tmp_path):
    hermes_task = {"id": "h1", "title": "Task", "body": "body", "status": "todo", "priority": 0}
    clickup_task = linked_clickup()
    hermes = FakeHermes([hermes_task])
    clickup = FakeClickUp([clickup_task], listed_ids=set())
    service, state = make_service(tmp_path, hermes, clickup)
    state.upsert_task_mapping("board-a", "h1", "list-1", "c1", TaskSnapshot("Task", "body", "todo", 0))

    service.run_once()

    assert clickup.deleted == []
    assert clickup.created == []
    assert hermes.deleted == []


def test_filtered_hermes_task_is_hydrated_not_deleted(tmp_path):
    hermes_task = {"id": "h1", "title": "Task", "body": "body", "status": "archived", "priority": 0}
    clickup_task = linked_clickup()
    clickup_task["status"] = {"status": "ARCHIVED"}
    hermes = FakeHermes([hermes_task], listed_ids=set())
    clickup = FakeClickUp([clickup_task])
    service, state = make_service(tmp_path, hermes, clickup)
    state.upsert_task_mapping("board-a", "h1", "list-1", "c1", TaskSnapshot("Task", "body", "archived", 0))

    service.run_once()

    assert clickup.deleted == []
    assert hermes.deleted == []
