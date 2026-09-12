# HermesKanban-Clickup

A small bidirectional reconciliation service between [Hermes Agent](https://github.com/NousResearch/hermes-agent) Kanban boards and ClickUp.

It keeps Hermes as the agent execution system while using ClickUp as a human-friendly Kanban surface.

## Mapping

```text
ClickUp Folder: Hermes
├── ClickUp List: Board A  <->  Hermes board: board-a
├── ClickUp List: Board B  <->  Hermes board: board-b
└── ...

ClickUp task              <->  Hermes task
ClickUp task status       <->  Hermes task status
```

The service polls both APIs in one reconciliation cycle. It does not require ClickUp webhooks, custom fields, a paid ClickUp plan, or modifications to Hermes.

## What syncs

- Hermes boards create matching ClickUp Lists automatically.
- Existing Hermes tasks create matching ClickUp tasks.
- New unlinked ClickUp tasks create Hermes tasks in the corresponding board.
- Title, description, status, and compatible priority values synchronize in both directions.
- Hermes identity metadata is stored in a managed footer inside the ClickUp task description.
- Human-written description text is preserved outside that managed block.
- A local SQLite state database records mappings and the last reconciled task snapshot.
- If the local mapping database is lost, linked tasks can be rediscovered from the managed description footer.

Deliberately not synchronized in the first release: destructive deletion, attachments, comments, run history, and ClickUp-specific planning metadata.

## Conflict policy

The synchronizer stores the last common snapshot for each linked task.

- only Hermes changed: Hermes updates ClickUp
- only ClickUp changed: ClickUp updates Hermes
- both changed to the same value: no conflict
- both changed differently: Hermes wins the whole-task conflict in v1 and a warning is logged

This policy is intentionally conservative because execution state is owned by Hermes. A later release can resolve fields independently.

## Requirements

- Python 3.11+
- a running Hermes dashboard/API
- a ClickUp API token
- the ClickUp Space ID in which the `Hermes` Folder should live

Hermes currently serves its local dashboard on `http://127.0.0.1:9119` by default. Keeping the Hermes API bound to loopback is strongly recommended.

## Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

For development:

```bash
pip install -e '.[dev]'
pytest
```

## Configure

Copy `.env.example` somewhere private and supply real values through your shell, container runtime, or service manager. Do not commit credentials.

Required:

```bash
export CLICKUP_TOKEN='...'
export CLICKUP_SPACE_ID='...'
```

Optional:

```bash
export CLICKUP_FOLDER_NAME='Hermes'
export HERMES_BASE_URL='http://127.0.0.1:9119'
export HERMES_SESSION_TOKEN=''
export POLL_INTERVAL_SECONDS='30'
export SYNC_STATE_DB='./data/sync.db'
```

### Status mapping

ClickUp only accepts statuses configured for the destination List/Folder. By default the synchronizer expects ClickUp statuses named after Hermes states:

```text
TRIAGE
TODO
SCHEDULED
READY
RUNNING
BLOCKED
REVIEW
DONE
ARCHIVED
```

If your ClickUp Folder uses different names, override them with `STATUS_MAP_JSON`:

```bash
export STATUS_MAP_JSON='{"todo":"TO DO","running":"IN PROGRESS","done":"COMPLETE"}'
```

Unspecified Hermes states retain their default mapping.

## Run

One reconciliation cycle:

```bash
hermes-clickup-sync --once
```

Continuous polling:

```bash
hermes-clickup-sync
```

Verbose logs:

```bash
hermes-clickup-sync --verbose
```

A read-only diagnostic pass is available with `--dry-run`. In dry-run mode the required Folder and Lists must already exist.

## Description metadata

No ClickUp custom fields are required. Linked tasks contain a managed footer resembling:

```text
[HERMES_MANAGED_BEGIN]
### Hermes
Board: `example-board`
Task: `example-task-id`
Agent: `example-profile`

[HERMES_SYNC] {"board":"example-board","task":"example-task-id","v":1}
[HERMES_MANAGED_END]
```

Text outside the markers belongs to the task description and is synchronized normally. The service only replaces the managed block.

## Security

- Never commit `CLICKUP_TOKEN`, Hermes session tokens, real workspace IDs, or generated SQLite state.
- `.env*` files and local database files are ignored by Git except for `.env.example`.
- Prefer connecting to Hermes over loopback rather than exposing its plugin API publicly.
- The managed ClickUp description block contains board/task identifiers, not credentials.

## Development

```bash
pytest -q
python -m compileall -q src
```

The integration is intentionally small: HTTP adapters, deterministic reconciliation logic, description metadata handling, and SQLite mapping state.

## License

MIT
