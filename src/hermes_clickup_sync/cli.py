from __future__ import annotations

import argparse
import logging
import time

from .clickup import ClickUpClient
from .config import Settings
from .hermes import HermesClient
from .service import SyncService
from .state import StateStore


def build_service(settings: Settings, *, dry_run: bool = False) -> SyncService:
    return SyncService(
        hermes=HermesClient(settings.hermes_base_url, session_token=settings.hermes_session_token),
        clickup=ClickUpClient(settings.clickup_token),
        state=StateStore(settings.state_db),
        clickup_space_id=settings.clickup_space_id,
        folder_name=settings.folder_name,
        status_map=settings.status_map or {},
        dry_run=dry_run,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Synchronize Hermes Kanban boards with ClickUp Lists")
    parser.add_argument("--once", action="store_true", help="Run one reconciliation cycle and exit")
    parser.add_argument("--dry-run", action="store_true", help="Read both systems without applying changes")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    settings = Settings.from_env()
    service = build_service(settings, dry_run=args.dry_run)

    if args.once:
        service.run_once()
        return 0

    while True:
        try:
            service.run_once()
        except Exception:
            logging.exception("sync cycle failed")
        time.sleep(settings.poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
