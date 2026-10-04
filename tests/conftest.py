"""Shared fixtures: isolated app home, temp workspaces, clean Qt state."""

from __future__ import annotations

import os
import sys

import pytest


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """Redirect every persisted artefact into a temp dir for all tests."""
    home = tmp_path / "agentdesk-home"
    home.mkdir()
    monkeypatch.setenv("AGENTDESK_HOME", str(home))
    yield home


@pytest.fixture()
def workspace_dir(tmp_path):
    """A sample workspace tree used by tool tests."""
    root = tmp_path / "project"
    (root / "src").mkdir(parents=True)
    (root / "src" / "utils.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    (root / "README.md").write_text("# Demo\n", encoding="utf-8")
    return root


@pytest.fixture(scope="session")
def qapp():
    """Session-wide offscreen QApplication for UI smoke tests."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        from PySide6.QtWidgets import QApplication
    except Exception as exc:  # pragma: no cover — CI without Qt libs
        pytest.skip(f"PySide6 unavailable: {exc}")
    app = QApplication.instance() or QApplication(sys.argv)
    yield app
