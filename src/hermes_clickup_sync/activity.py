from __future__ import annotations

import logging
import re
from typing import Any

_MARKER_RE = re.compile(r"\[HERMES_ACTIVITY\s+(comment|run):([^\]]+)\]")
_CLICKUP_AUTHOR_RE = re.compile(r"^clickup:([^:]+)(?::.*)?$")


def format_hermes_comment(comment: dict[str, Any]) -> str:
    comment_id = str(comment.get("id", "")).strip()
    author = str(comment.get("author") or "Hermes").strip()
    body = str(comment.get("body") or "").strip()
    return f"🤖 Hermes · {author}\n\n{body}\n\n[HERMES_ACTIVITY comment:{comment_id}]"


def format_run_summary(run: dict[str, Any], *, agent: str | None = None) -> str:
    run_id = str(run.get("id", "")).strip()
    summary = str(run.get("summary") or "").strip()
    outcome = str(run.get("outcome") or run.get("status") or "completed").strip()
    actor = str(agent or run.get("assignee") or "agent").strip()
    return f"🤖 Hermes · {actor}\nRun #{run_id} · {outcome}\n\n{summary}\n\n[HERMES_ACTIVITY run:{run_id}]"


def parse_hermes_activity_marker(text: str | None) -> tuple[str, str] | None:
    match = _MARKER_RE.search(text or "")
    return (match.group(1), match.group(2)) if match else None


def clickup_comment_text(comment: dict[str, Any]) -> str:
    direct = comment.get("comment_text") or comment.get("text_content")
    if isinstance(direct, str):
        return direct.strip()
    parts = comment.get("comment")
    if isinstance(parts, list):
        return "".join(
            str(part.get("text") or "")
            for part in parts
            if isinstance(part, dict)
        ).strip()
    if isinstance(parts, str):
        return parts.strip()
    return ""


def clickup_comment_origin_author(comment: dict[str, Any]) -> str:
    comment_id = str(comment.get("id") or "unknown")
    user = comment.get("user") or {}
    username = str(user.get("username") or user.get("email") or "user").replace(":", "-").strip()
    return f"clickup:{comment_id}:{username}"


def clickup_comment_origin_id(author: str | None) -> str | None:
    match = _CLICKUP_AUTHOR_RE.match(author or "")
    return match.group(1) if match else None


def sync_task_activity(
    *,
    board_slug: str,
    hermes_task: dict[str, Any],
    clickup_task_id: str,
    hermes: Any,
    clickup: Any,
    state: Any,
    dry_run: bool = False,
) -> None:
    """Reconcile task comments and Hermes run summaries without echo loops."""
    if not callable(getattr(hermes, "get_task_detail", None)) or not callable(
        getattr(clickup, "list_comments", None)
    ):
        return

    task_id = str(hermes_task["id"])
    detail = hermes.get_task_detail(board_slug, task_id)
    if not detail:
        return

    hermes_comments = detail.get("comments") or []
    runs = detail.get("runs") or []
    clickup_comments = clickup.list_comments(clickup_task_id)

    clickup_markers: set[tuple[str, str]] = set()
    for comment in clickup_comments:
        marker = parse_hermes_activity_marker(clickup_comment_text(comment))
        if marker:
            clickup_markers.add(marker)

    imported_clickup_ids = {
        origin_id
        for comment in hermes_comments
        if (origin_id := clickup_comment_origin_id(str(comment.get("author") or "")))
    }

    for comment in hermes_comments:
        source_id = str(comment.get("id") or "").strip()
        body = str(comment.get("body") or "").strip()
        author = str(comment.get("author") or "")
        if not source_id or not body or clickup_comment_origin_id(author):
            continue

        key = ("comment", source_id)
        if state.activity_seen(board_slug, task_id, "hermes_comment", source_id) or key in clickup_markers:
            if key in clickup_markers and not dry_run:
                state.mark_activity(board_slug, task_id, "hermes_comment", source_id)
            continue

        text = format_hermes_comment(comment)
        if dry_run:
            logging.getLogger(__name__).info(
                "Would append Hermes comment %s/%s#%s to ClickUp %s",
                board_slug,
                task_id,
                source_id,
                clickup_task_id,
            )
            continue
        target_id = clickup.add_comment(clickup_task_id, text)
        state.mark_activity(board_slug, task_id, "hermes_comment", source_id, target_id)

    for run in runs:
        source_id = str(run.get("id") or "").strip()
        summary = str(run.get("summary") or "").strip()
        if not source_id or not summary:
            continue

        key = ("run", source_id)
        if state.activity_seen(board_slug, task_id, "hermes_run", source_id) or key in clickup_markers:
            if key in clickup_markers and not dry_run:
                state.mark_activity(board_slug, task_id, "hermes_run", source_id)
            continue

        text = format_run_summary(run, agent=hermes_task.get("assignee"))
        if dry_run:
            logging.getLogger(__name__).info(
                "Would append Hermes run summary %s/%s#%s to ClickUp %s",
                board_slug,
                task_id,
                source_id,
                clickup_task_id,
            )
            continue
        target_id = clickup.add_comment(clickup_task_id, text)
        state.mark_activity(board_slug, task_id, "hermes_run", source_id, target_id)

    for comment in reversed(clickup_comments):
        source_id = str(comment.get("id") or "").strip()
        text = clickup_comment_text(comment)
        if not source_id or not text or parse_hermes_activity_marker(text):
            continue
        if source_id in imported_clickup_ids or state.activity_seen(
            board_slug, task_id, "clickup_comment", source_id
        ):
            continue

        author = clickup_comment_origin_author(comment)
        if dry_run:
            logging.getLogger(__name__).info(
                "Would import ClickUp comment %s into Hermes %s/%s",
                source_id,
                board_slug,
                task_id,
            )
            continue
        hermes.add_comment(board_slug, task_id, author=author, body=text)
        state.mark_activity(board_slug, task_id, "clickup_comment", source_id)
