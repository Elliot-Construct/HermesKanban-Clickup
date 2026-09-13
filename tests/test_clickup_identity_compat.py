from hermes_clickup_sync.activity import (
    clickup_comment_origin_author,
    clickup_comment_origin_id,
    format_clickup_import_body,
)


def test_clickup_identity_is_readable_and_marker_backed():
    comment = {
        "id": "991",
        "user": {"id": 42, "username": "Operator", "email": "private@example.com"},
        "comment": [{"text": "Please keep this."}],
    }

    assert clickup_comment_origin_author(comment) == "Operator (ClickUp)"
    body = format_clickup_import_body(comment)
    assert body == "Please keep this.\n\n[CLICKUP_COMMENT id:991 user:42]"
    assert clickup_comment_origin_id(body) == "991"
    assert "private@example.com" not in body


def test_clickup_identity_fallback_never_uses_email():
    comment = {
        "id": "992",
        "user": {"id": 73, "email": "someone@example.com"},
        "comment": [{"text": "Please review."}],
    }

    assert clickup_comment_origin_author(comment) == "ClickUp User 73 (ClickUp)"
    assert "someone@example.com" not in format_clickup_import_body(comment)


def test_legacy_clickup_author_marker_still_recovers_origin():
    assert clickup_comment_origin_id("clickup:77:Operator") == "77"
