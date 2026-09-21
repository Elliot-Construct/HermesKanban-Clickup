from __future__ import annotations

from .models import TaskSnapshot


def decide_direction(base: TaskSnapshot, hermes: TaskSnapshot, clickup: TaskSnapshot) -> str:
    hermes_changed = hermes != base
    clickup_changed = clickup != base
    if hermes_changed and clickup_changed:
        if hermes == clickup:
            return "noop"
        return "conflict"
    if hermes_changed:
        return "hermes_to_clickup"
    if clickup_changed:
        return "clickup_to_hermes"
    return "noop"
