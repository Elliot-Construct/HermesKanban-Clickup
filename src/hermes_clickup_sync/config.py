from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_STATUS_MAP = {
    "triage": "TRIAGE",
    "todo": "TODO",
    "scheduled": "SCHEDULED",
    "ready": "READY",
    "running": "RUNNING",
    "blocked": "BLOCKED",
    "review": "REVIEW",
    "done": "DONE",
    "archived": "ARCHIVED",
}


@dataclass(frozen=True)
class Settings:
    clickup_token: str
    clickup_space_id: str
    hermes_base_url: str = "http://127.0.0.1:9119"
    hermes_session_token: str | None = None
    folder_name: str = "Hermes"
    poll_seconds: float = 30.0
    state_db: Path = Path("./data/sync.db")
    status_map: dict[str, str] | None = None

    @classmethod
    def from_env(cls) -> "Settings":
        token = os.getenv("CLICKUP_TOKEN", "").strip()
        space_id = os.getenv("CLICKUP_SPACE_ID", "").strip()
        if not token:
            raise ValueError("CLICKUP_TOKEN is required")
        if not space_id:
            raise ValueError("CLICKUP_SPACE_ID is required")

        raw_map = os.getenv("STATUS_MAP_JSON", "").strip()
        status_map = dict(DEFAULT_STATUS_MAP)
        if raw_map:
            parsed = json.loads(raw_map)
            if not isinstance(parsed, dict) or not parsed:
                raise ValueError("STATUS_MAP_JSON must be a non-empty JSON object")
            status_map.update({str(k): str(v) for k, v in parsed.items()})

        return cls(
            clickup_token=token,
            clickup_space_id=space_id,
            hermes_base_url=os.getenv("HERMES_BASE_URL", "http://127.0.0.1:9119").rstrip("/"),
            hermes_session_token=os.getenv("HERMES_SESSION_TOKEN") or None,
            folder_name=os.getenv("CLICKUP_FOLDER_NAME", "Hermes"),
            poll_seconds=float(os.getenv("POLL_INTERVAL_SECONDS", "30")),
            state_db=Path(os.getenv("SYNC_STATE_DB", "./data/sync.db")),
            status_map=status_map,
        )
