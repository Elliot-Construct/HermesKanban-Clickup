from __future__ import annotations

import pytest

from hermes_clickup_sync.config import Settings


def test_settings_require_clickup_credentials(monkeypatch):
    monkeypatch.delenv("CLICKUP_TOKEN", raising=False)
    monkeypatch.delenv("CLICKUP_SPACE_ID", raising=False)
    with pytest.raises(ValueError, match="CLICKUP_TOKEN"):
        Settings.from_env()


def test_status_map_override_merges_with_defaults(monkeypatch):
    monkeypatch.setenv("CLICKUP_TOKEN", "token")
    monkeypatch.setenv("CLICKUP_SPACE_ID", "space")
    monkeypatch.setenv("STATUS_MAP_JSON", '{"todo":"TO DO","running":"IN PROGRESS"}')

    settings = Settings.from_env()

    assert settings.status_map["todo"] == "TO DO"
    assert settings.status_map["running"] == "IN PROGRESS"
    assert settings.status_map["done"] == "DONE"
