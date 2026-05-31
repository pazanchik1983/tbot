"""Изоляция тестов: временные APPDATA и БД, чистая шина событий."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_appdata(monkeypatch, tmp_path: Path):
    # Подменяем APPDATA / XDG, чтобы config/models/logs шли в tmp
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    # Перенаправляем БД явно
    from tbot.core import storage
    storage.set_db_path(tmp_path / "test.db")
    yield
    storage.set_db_path(None)


@pytest.fixture(autouse=True)
def clean_bus():
    from tbot.core.event_bus import bus
    bus.unsubscribe_all()
    yield
    bus.unsubscribe_all()
