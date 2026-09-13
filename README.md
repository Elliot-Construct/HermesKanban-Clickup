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
Hermes task comments      <->  ClickUp task comments
Hermes run summaries       ->  ClickUp task comments
```

The service polls both APIs in one reconciliation cycle. It does not require ClickUp webhooks, custom fields, a paid ClickUp plan, or modifications to Hermes.

## What syncs

- Hermes boards create matching ClickUp Lists automatically.
- Existing Hermes tasks create matching ClickUp tasks.
- New unlinked ClickUp tasks create Hermes tasks in the corresponding board.
- Title, description, status, and compatible priority values synchronize in both directions.
- Hermes task comments are appended to the corresponding ClickUp task as comments.
- Completed Hermes run summaries are appended to ClickUp as chronological activity comments.
- Human ClickUp task comments are imported into the Hermes task comment thread so workers can see them in task context.
- Comment/run activity is de-duplicated locally and carries recoverable source markers so a lost local state database does not cause a comment echo loop.
- Deleting a previously linked task in Hermes deletes its ClickUp counterpart.
- Deleting a previously linked task in ClickUp deletes its Hermes counterpart.
- Deletion is only propagated after a direct existence check, so a task merely omitted by a board/list query is not treated as deleted.
- Hermes identity metadata is stored in a managed footer inside the ClickUp task description.
- Human-written description text is preserved outside that managed block.
- A local SQLite state database records mappings, last reconciled task snapshots, and activity IDs.
- If the local mapping database is lost, linked tasks can be rediscovered from the managed description footer and activity markers.

Deliberately not synchronized in the first release: attachments, full run logs, edits/deletions of historical comments, and ClickUp-specific planning metadata.

## Activity comments

The task description remains the durable task contract. Comments are the chronological activity and conversation trail.

A Hermes comment appears in ClickUp in a form similar to:

```text
🤖 Hermes · worker

Implemented the retry path and verified reconnect behavior.

[HERMES_ACTIVITY comment:12]
```

A Hermes run handoff appears as:

```text
🤖 Hermes · worker
Run #17 · completed

Implemented the requested change. Tests pass.

[HERMES_ACTIVITY run:17]
```

The small activity marker is intentional. It lets the synchronizer recover de-duplication after local state loss without relying on paid ClickUp custom fields.

When a human writes a normal ClickUp task comment, it is imported into Hermes with a readable author such as `Operator (ClickUp)` and a recoverable marker in the comment body:

```text
Author: Operator (ClickUp)

Preserve the existing browser session.

[CLICKUP_COMMENT id:77 user:42]
```

The visible author is derived from the ClickUp display name. Email addresses are not used as a fallback display identity; if no display name is available the synchronizer uses a generic label such as `ClickUp User 42 (ClickUp)`. The body marker carries the source comment/user identifiers used for de-duplication and recovery after local state loss.

For upgrade compatibility, the synchronizer also recognizes the older `clickup:<comment-id>:<name>` Hermes author format and will not echo those historical comments back into ClickUp.

Activity sync is append-only in v1. Editing or deleting an already-synchronized historical comment does not mutate its counterpart.

The ClickUp API request uses `notify_all=false` for generated comments. ClickUp may still notify task watchers or assignees according to ClickUp's own notification behavior.

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

## Deletion safety

Deletion propagation is intentionally stricter than ordinary field synchronization:

1. the task must already be linked by the local mapping database or Hermes metadata anchor;
2. the task must be absent from the normal reconciliation result; and
3. the synchronizer performs a direct API existence check before deleting the counterpart.

Brand-new unlinked ClickUp cards are therefore adopted into Hermes, not deleted. Archived Hermes tasks are requested explicitly from the Hermes API so they are not confused with deleted tasks.

## Security

- Never commit `CLICKUP_TOKEN`, Hermes session tokens, real workspace IDs, or generated SQLite state.
- `.env*` files and local database files are ignored by Git except for `.env.example`.
- Prefer connecting to Hermes over loopback rather than exposing its plugin API publicly.
- Managed description and activity markers contain task/run/comment identifiers, not credentials.
- ClickUp email addresses are not copied into Hermes comment author labels.

## Development

```bash
pytest -q
python -m compileall -q src
```

The integration is intentionally small: HTTP adapters, deterministic reconciliation logic, append-only activity synchronization, description metadata handling, and SQLite mapping state.

## License

Apache-2.0
