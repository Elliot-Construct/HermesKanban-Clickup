from hermes_clickup_sync.activity import (
    clickup_comment_origin_author,
    clickup_comment_origin_id,
    clickup_comment_text,
    format_clickup_import_body,
    format_hermes_comment,
    format_run_summary,
    parse_hermes_activity_marker,
    sync_task_activity,
)
from hermes_clickup_sync.models import TaskSnapshot
from hermes_clickup_sync.service import SyncService
from hermes_clickup_sync.state import StateStore


class FakeHermesActivity:
    def __init__(self, comments=None, runs=None):
        self.comments = list(comments or [])
        self.runs = list(runs or [])
        self.added = []

    def get_task_detail(self, board, task_id):
        return {
            "task": {"id": task_id},
            "comments": list(self.comments),
            "runs": list(self.runs),
        }

    def add_comment(self, board, task_id, *, author, body):
        self.added.append((board, task_id, author, body))
        self.comments.append(
            {"id": 1000 + len(self.added), "author": author, "body": body}
        )


class FakeClickUpActivity:
    def __init__(self, comments=None):
        self.comments = list(comments or [])
        self.added = []

    def list_comments(self, task_id):
        return list(self.comments)

    def add_comment(self, task_id, text):
        ident = str(900 + len(self.added))
        self.added.append((task_id, text))
        self.comments.insert(
            0,
            {
                "id": ident,
                "date": "999",
                "user": {"username": "sync"},
                "comment": [{"text": text}],
            },
        )
        return ident


def test_formats_hermes_comment_with_recoverable_marker():
    text = format_hermes_comment(
        {"id": 12, "author": "worker", "body": "Implemented the retry path."}
    )
    assert "Hermes · worker" in text
    assert "Implemented the retry path." in text
    assert parse_hermes_activity_marker(text) == ("comment", "12")


def test_formats_run_summary_with_outcome_and_marker():
    text = format_run_summary(
        {"id": 17, "summary": "Tests pass.", "outcome": "completed"},
        agent="worker",
    )
    assert "Run #17" in text
    assert "completed" in text
    assert "Tests pass." in text
    assert parse_hermes_activity_marker(text) == ("run", "17")


def test_clickup_comment_helpers_flatten_and_track_origin():
    comment = {
        "id": "991",
        "user": {"id": 42, "username": "Operator", "email": "private@example.com"},
        "comment": [{"text": "Please "}, {"text": "keep this."}],
    }
    assert clickup_comment_text(comment) == "Please keep this."
    assert clickup_comment_origin_author(comment) == "Operator (ClickUp)"
    body = format_clickup_import_body(comment)
    assert body.startswith("Please keep this.")
    assert "private@example.com" not in body
    assert "[CLICKUP_COMMENT id:991 user:42]" in body
    assert clickup_comment_origin_id(body) == "991"


def test_clickup_comment_author_fallback_does_not_expose_email():
    comment = {
        "id": "992",
        "user": {"id": 73, "email": "someone@example.com"},
        "comment": [{"text": "Please review."}],
    }
    assert clickup_comment_origin_author(comment) == "ClickUp User 73 (ClickUp)"
    assert "someone@example.com" not in format_clickup_import_body(comment)


def test_activity_mapping_is_idempotent_and_cleaned_with_task(tmp_path):
    state = StateStore(tmp_path / "sync.db")
    assert not state.activity_seen("board", "task", "hermes_comment", "12")
    state.mark_activity("board", "task", "hermes_comment", "12", "991")
    assert state.activity_seen("board", "task", "hermes_comment", "12")
    assert state.activity_target("board", "task", "hermes_comment", "12") == "991"
    state.delete_task_mapping("board", "task")
    assert not state.activity_seen("board", "task", "hermes_comment", "12")


def test_run_summary_is_appended_once_to_clickup(tmp_path):
    state = StateStore(tmp_path / "sync.db")
    hermes = FakeHermesActivity(
        runs=[
            {
                "id": 17,
                "summary": "Implemented and verified.",
                "outcome": "completed",
            }
        ]
    )
    clickup = FakeClickUpActivity()

    for _ in range(2):
        sync_task_activity(
            board_slug="board",
            hermes_task={"id": "h1", "assignee": "worker"},
            clickup_task_id="c1",
            hermes=hermes,
            clickup=clickup,
            state=state,
        )

    assert len(clickup.added) == 1
    assert "Run #17" in clickup.added[0][1]
    assert "Implemented and verified." in clickup.added[0][1]


def test_human_clickup_comment_is_imported_once_into_hermes(tmp_path):
    state = StateStore(tmp_path / "sync.db")
    hermes = FakeHermesActivity()
    clickup = FakeClickUpActivity(
        [
            {
                "id": "77",
                "date": "1",
                "user": {"id": 42, "username": "Operator"},
                "comment": [{"text": "Preserve the existing session."}],
            }
        ]
    )

    for _ in range(2):
        sync_task_activity(
            board_slug="board",
            hermes_task={"id": "h1", "assignee": "worker"},
            clickup_task_id="c1",
            hermes=hermes,
            clickup=clickup,
            state=state,
        )

    assert hermes.added == [
        (
            "board",
            "h1",
            "Operator (ClickUp)",
            "Preserve the existing session.\n\n[CLICKUP_COMMENT id:77 user:42]",
        )
    ]


def test_embedded_markers_prevent_duplicates_after_state_loss(tmp_path):
    hermes = FakeHermesActivity(
        comments=[
            {"id": 12, "author": "worker", "body": "Found the cause."},
            {
                "id": 13,
                "author": "Operator (ClickUp)",
                "body": "Human note\n\n[CLICKUP_COMMENT id:77 user:42]",
            },
        ],
        runs=[{"id": 17, "summary": "Fixed it.", "outcome": "completed"}],
    )
    clickup = FakeClickUpActivity(
        [
            {
                "id": "77",
                "date": "3",
                "user": {"id": 42, "username": "Operator"},
                "comment": [{"text": "Human note"}],
            },
            {
                "id": "c-run",
                "date": "2",
                "user": {"username": "sync"},
                "comment": [
                    {
                        "text": "🤖 Hermes · worker\nRun #17 · completed\n\nFixed it.\n\n[HERMES_ACTIVITY run:17]"
                    }
                ],
            },
            {
                "id": "c-comment",
                "date": "1",
                "user": {"username": "sync"},
                "comment": [
                    {
                        "text": "🤖 Hermes · worker\n\nFound the cause.\n\n[HERMES_ACTIVITY comment:12]"
                    }
                ],
            },
        ]
    )
    state = StateStore(tmp_path / "fresh.db")

    sync_task_activity(
        board_slug="board",
        hermes_task={"id": "h1", "assignee": "worker"},
        clickup_task_id="c1",
        hermes=hermes,
        clickup=clickup,
        state=state,
    )

    assert clickup.added == []
    assert hermes.added == []


def test_clickup_origin_hermes_comment_is_not_echoed_back(tmp_path):
    state = StateStore(tmp_path / "sync.db")
    hermes = FakeHermesActivity(
        comments=[
            {
                "id": 88,
                "author": "Operator (ClickUp)",
                "body": "Human note\n\n[CLICKUP_COMMENT id:77 user:42]",
            }
        ]
    )
    clickup = FakeClickUpActivity(
        [
            {
                "id": "77",
                "date": "1",
                "user": {"id": 42, "username": "Operator"},
                "comment": [{"text": "Human note"}],
            }
        ]
    )

    sync_task_activity(
        board_slug="board",
        hermes_task={"id": "h1", "assignee": "worker"},
        clickup_task_id="c1",
        hermes=hermes,
        clickup=clickup,
        state=state,
    )

    assert clickup.added == []
    assert hermes.added == []


class LinkedHermes:
    def list_boards(self):
        return [{"slug": "board", "name": "Board"}]

    def get_board(self, board):
        return {
            "columns": [
                {
                    "name": "done",
                    "tasks": [
                        {
                            "id": "h1",
                            "title": "Task",
                            "body": "",
                            "status": "done",
                            "priority": 0,
                            "assignee": "worker",
                        }
                    ],
                }
            ]
        }

    def get_task(self, board, task_id):
        return {
            "id": "h1",
            "title": "Task",
            "body": "",
            "status": "done",
            "priority": 0,
            "assignee": "worker",
        }

    def get_task_detail(self, board, task_id):
        return {
            "task": {"id": "h1"},
            "comments": [],
            "runs": [
                {"id": 3, "summary": "Finished cleanly.", "outcome": "completed"}
            ],
        }

    def task_exists(self, board, task_id):
        return True


class LinkedClickUp:
    def __init__(self):
        self.added_comments = []

    def list_folders(self, space):
        return [{"id": "f", "name": "Hermes"}]

    def list_lists(self, folder):
        return [{"id": "l", "name": "Board"}]

    def list_tasks(self, list_id):
        return [
            {
                "id": "c1",
                "name": "Task",
                "description": "",
                "status": {"status": "DONE"},
                "priority": None,
            }
        ]

    def get_task(self, task_id):
        return self.list_tasks("l")[0]

    def list_comments(self, task_id):
        return []

    def add_comment(self, task_id, text):
        self.added_comments.append((task_id, text))
        return "x1"


def test_run_once_syncs_activity_for_linked_task(tmp_path):
    clickup = LinkedClickUp()
    state = StateStore(tmp_path / "sync.db")
    service = SyncService(
        hermes=LinkedHermes(),
        clickup=clickup,
        state=state,
        clickup_space_id="s",
        folder_name="Hermes",
        status_map={"done": "DONE"},
    )
    state.upsert_board_mapping("board", "l")
    state.upsert_task_mapping(
        "board", "h1", "l", "c1", TaskSnapshot("Task", "", "done", 0)
    )

    service.run_once()

    assert len(clickup.added_comments) == 1
    assert "Finished cleanly." in clickup.added_comments[0][1]
