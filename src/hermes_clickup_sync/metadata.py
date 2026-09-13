from __future__ import annotations

import json
import re
from typing import Any

BEGIN = "[HERMES_MANAGED_BEGIN]"
END = "[HERMES_MANAGED_END]"
_BLOCK_RE = re.compile(rf"\n*{re.escape(BEGIN)}.*?{re.escape(END)}\n*", re.DOTALL)
_ANCHOR_RE = re.compile(r"\[HERMES_SYNC\]\s*(\{.*?\})", re.DOTALL)


def _managed_block(*, board: str, task_id: str, agent: str | None, run_id: str | None) -> str:
    anchor = json.dumps({"v": 1, "board": board, "task": task_id}, separators=(",", ":"), sort_keys=True)
    lines = [
        BEGIN,
        "### Hermes",
        f"Board: `{board}`",
        f"Task: `{task_id}`",
    ]
    if agent:
        lines.append(f"Agent: `{agent}`")
    if run_id:
        lines.append(f"Run: `{run_id}`")
    lines.extend(["", f"[HERMES_SYNC] {anchor}", END])
    return "\n".join(lines)


def upsert_managed_section(
    description: str | None,
    *,
    board: str,
    task_id: str,
    agent: str | None,
    run_id: str | None,
) -> str:
    human = _BLOCK_RE.sub("\n", description or "").rstrip()
    block = _managed_block(board=board, task_id=task_id, agent=agent, run_id=run_id)
    return f"{human}\n\n{block}\n" if human else f"{block}\n"


def extract_anchor(description: str | None) -> dict[str, Any] | None:
    match = _ANCHOR_RE.search(description or "")
    if not match:
        return None
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError:
        return None
    if payload.get("v") != 1 or not payload.get("board") or not payload.get("task"):
        return None
    return payload


def strip_managed_section(description: str | None) -> str:
    return _BLOCK_RE.sub("\n", description or "").strip()
