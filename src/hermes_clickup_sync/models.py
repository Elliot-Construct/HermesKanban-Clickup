from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TaskSnapshot:
    title: str
    body: str
    status: str
    priority: int = 0
