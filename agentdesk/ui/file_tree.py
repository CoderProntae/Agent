"""Left sidebar: workspace file explorer.

Uses a ``QFileSystemModel`` rooted at the bound workspace with common
build/dependency noise filtered out. Double-click opens a file in the
editor panel; the model is refreshed automatically when the agent mutates
the filesystem (via a QFileSystemWatcher-free manual ``refresh``).
"""

from __future__ import annotations

from PySide6.QtCore import QDir, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from agentdesk.tools.workspace import Workspace

HIDDEN_FILTERS = [
    "*.pyc", "*.pyo", "*.class", "*.o", "*.obj", "*.exe", "*.dll", "*.so",
    "*.egg-info", ".DS_Store", "Thumbs.db",
]


class FileTreePanel(QWidget):
    """Tree view of the bound workspace."""

    file_open_requested = Signal(str)  # workspace-relative path

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.tree = QTreeView()
        self.tree.setHeaderHidden(True)
        self.tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tree.setAnimated(True)
        self.tree.setExpandsOnDoubleClick(False)
        self.tree.doubleClicked.connect(self._on_double_click)
        layout.addWidget(self.tree)
        self._model = None

    def bind_workspace(self, workspace: Workspace | None) -> None:
        """Point the tree at a new workspace root."""
        from PySide6.QtWidgets import QFileSystemModel

        if workspace is None:
            self.tree.setModel(None)
            self._model = None
            return
        self._model = QFileSystemModel(self)
        self._model.setRootPath(str(workspace.root))
        self._model.setNameFilters(HIDDEN_FILTERS)
        self._model.setFilter(QDir.AllEntries | QDir.NoDotAndDotDot)
        self.tree.setModel(self._model)
        self.tree.setRootIndex(self._model.index(str(workspace.root)))
        header: QHeaderView = self.tree.header()
        header.setStretchLastSection(True)
        for col in (1, 2, 3):
            self.tree.hideColumn(col)

    def refresh(self) -> None:
        """Force re-read of the directory contents after agent edits."""
        if self._model is not None:
            root = self._model.rootPath()
            self._model.setRootPath("")
            self._model.setRootPath(root)

    def _on_double_click(self, index) -> None:
        if self._model is None:
            return
        path = self._model.filePath(index)
        if self._model.isDir(index):
            self.tree.setExpanded(index, not self.tree.isExpanded(index))
            return
        workspace_root = self._model.rootPath()
        try:
            import os

            rel = os.path.relpath(path, workspace_root).replace("\\", "/")
            self.file_open_requested.emit(rel)
        except ValueError:
            pass
