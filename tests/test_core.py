from __future__ import annotations

from hermes_clickup_sync.metadata import extract_anchor, strip_managed_section, upsert_managed_section
from hermes_clickup_sync.models import TaskSnapshot
from hermes_clickup_sync.reconcile import decide_direction
from hermes_clickup_sync.state import StateStore


def snap(title="Task", body="body", status="todo", priority=0):
    return TaskSnapshot(title, body, status, priority)


def test_managed_footer_preserves_human_description():
    rendered = upsert_managed_section("Human notes", board="board-a", task_id="h1", agent="worker", run_id="7")
    assert rendered.startswith("Human notes\n\n[HERMES_MANAGED_BEGIN]")
    assert strip_managed_section(rendered) == "Human notes"
    assert extract_anchor(rendered) == {"v": 1, "board": "board-a", "task": "h1"}


def test_managed_footer_is_replaced_not_duplicated():
    first = upsert_managed_section("Human notes", board="board-a", task_id="h1", agent=None, run_id=None)
    second = upsert_managed_section(first, board="board-a", task_id="h1", agent="worker", run_id=None)
    assert second.count("[HERMES_MANAGED_BEGIN]") == 1
    assert "Agent: `worker`" in second


def test_invalid_anchor_returns_none():
    assert extract_anchor("[HERMES_SYNC] not-json") is None
    assert extract_anchor('[HERMES_SYNC] {"v":2,"board":"b","task":"t"}') is None


def test_reconcile_detects_each_direction():
    base = snap()
    assert decide_direction(base, base, base) == "noop"
    assert decide_direction(base, snap(title="Hermes"), base) == "hermes_to_clickup"
    assert decide_direction(base, base, snap(title="ClickUp")) == "clickup_to_hermes"
    assert decide_direction(base, snap(title="Same"), snap(title="Same")) == "noop"
    assert decide_direction(base, snap(title="Hermes"), snap(title="ClickUp")) == "conflict"


def test_state_store_round_trips_and_deletes_mapping(tmp_path):
    store = StateStore(tmp_path / "sync.db")
    store.upsert_board_mapping("board-a", "list-1")
    store.upsert_task_mapping("board-a", "h1", "list-1", "c1", snap())

    mapping = store.get_task_mapping("board-a", "h1")
    assert mapping is not None
    assert mapping.clickup_task_id == "c1"
    assert mapping.last_synced == snap()
    assert store.get_board_list_id("board-a") == "list-1"
    assert store.list_task_mappings("board-a") == [mapping]

    store.delete_task_mapping("board-a", "h1")
    assert store.get_task_mapping("board-a", "h1") is None
