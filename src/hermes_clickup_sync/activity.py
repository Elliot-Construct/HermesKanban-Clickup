from __future__ import annotations

import logging
import re
from typing import Any

_MARKER_RE = re.compile(r"\[HERMES_ACTIVITY\s+(comment|run):([^\]]+)\]")
_CLICKUP_COMMENT_RE = re.compile(
    r"\[CLICKUP_COMMENT\s+id:([^\s\]]+)(?:\s+user:([^\]\s]+))?\]"
)
_LEGACY_CLICKUP_AUTHOR_RE = re.compile(r"^clickup:([^:]+)(?::.*)?$")


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


def _clean_display_name(value: Any) -> str:
    return " ".join(str(value or "").replace("\n", " ").replace("\r", " ").split()).strip()


def clickup_comment_origin_author(comment: dict[str, Any]) -> str:
    """Return a human-readable Hermes author without exposing ClickUp email addresses."""
    user = comment.get("user") or {}
    display = _clean_display_name(user.get("username") or user.get("name"))
    if not display:
        user_id = _clean_display_name(user.get("id"))
        display = f"ClickUp User {user_id}" if user_id else "ClickUp User"
    return f"{display} (ClickUp)"


def format_clickup_import_body(comment: dict[str, Any]) -> str:
    """Append a recoverable origin marker to a human ClickUp comment."""
    text = clickup_comment_text(comment)
    comment_id = _clean_display_name(comment.get("id")) or "unknown"
    user = comment.get("user") or {}
    user_id = _clean_display_name(user.get("id"))
    marker = f"[CLICKUP_COMMENT id:{comment_id}"
    if user_id:
        marker += f" user:{user_id}"
    marker += "]"
    return f"{text}\n\n{marker}" if text else marker


def clickup_comment_origin_id(text: str | None) -> str | None:
    """Extract ClickUp comment identity from new body markers or legacy author values."""
    value = text or ""
    marker = _CLICKUP_COMMENT_RE.search(value)
    if marker:
        return marker.group(1)
    legacy = _LEGACY_CLICKUP_AUTHOR_RE.match(value)
    return legacy.group(1) if legacy else None


def _hermes_comment_clickup_origin_id(comment: dict[str, Any]) -> str | None:
    return clickup_comment_origin_id(str(comment.get("body") or "")) or clickup_comment_origin_id(
        str(comment.get("author") or "")
    )


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
        if (origin_id := _hermes_comment_clickup_origin_id(comment))
    }

    for comment in hermes_comments:
        source_id = str(comment.get("id") or "").strip()
        body = str(comment.get("body") or "").strip()
        if not source_id or not body or _hermes_comment_clickup_origin_id(comment):
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
        body = format_clickup_import_body(comment)
        if dry_run:
            logging.getLogger(__name__).info(
                "Would import ClickUp comment %s into Hermes %s/%s as %s",
                source_id,
                board_slug,
                task_id,
                author,
            )
            continue
        hermes.add_comment(board_slug, task_id, author=author, body=body)
        state.mark_activity(board_slug, task_id, "clickup_comment", source_id)
