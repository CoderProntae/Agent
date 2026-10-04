"""Sandboxed workspace filesystem operations.

Every agent file action is funnelled through :class:`Workspace`, which
binds a root directory and hard-rejects any path that would escape it
(``..`` traversal, absolute paths outside the root, symlink escapes).

All mutating operations that change file content produce a unified diff in
their result payload so the UI can render a live diff view.
"""

from __future__ import annotations

import difflib
import logging
import os
import re
import shutil
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: Directories never traversed by search/list operations.
IGNORED_DIRS = {
    ".git", ".hg", ".svn", "__pycache__", "node_modules", ".venv", "venv",
    "dist", "build", ".mypy_cache", ".pytest_cache", ".next", ".cache",
}
MAX_FILE_BYTES = 2_000_000  # refuse to read/write files larger than this
MAX_SEARCH_RESULTS = 200


class WorkspaceError(Exception):
    """Operational error inside the workspace."""


class WorkspaceSecurityError(WorkspaceError):
    """A path attempted to escape the workspace sandbox."""


def unified_diff(old: str, new: str, path: str) -> str:
    """Render a unified diff between two text versions of a file."""
    return "".join(
        difflib.unified_diff(
            old.splitlines(keepends=True),
            new.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
            n=3,
        )
    )


class Workspace:
    """A directory the agent is allowed to operate on."""

    def __init__(self, root: str | Path):
        root_path = Path(root).expanduser()
        if not root_path.exists():
            raise WorkspaceError(f"Çalışma alanı bulunamadı: {root_path}")
        if not root_path.is_dir():
            raise WorkspaceError(f"Çalışma alanı bir dizin değil: {root_path}")
        self.root = root_path.resolve()

    # -- sandbox ----------------------------------------------------------
    def resolve(self, rel_path: str) -> Path:
        """Resolve ``rel_path`` inside the sandbox or raise a security error."""
        rel = (rel_path or "").strip().lstrip("/")
        candidate = (self.root / rel).resolve() if rel else self.root
        if candidate != self.root and self.root not in candidate.parents:
            raise WorkspaceSecurityError(
                f"Güvenlik ihlali: '{rel_path}' çalışma alanının dışına çıkıyor."
            )
        return candidate

    def rel(self, path: Path) -> str:
        """Workspace-relative POSIX path for display purposes."""
        try:
            return Path(path).resolve().relative_to(self.root).as_posix()
        except ValueError:
            return str(path)

    # -- listing ---------------------------------------------------------
    def list_dir(self, rel_path: str = "") -> list[dict[str, Any]]:
        target = self.resolve(rel_path)
        if not target.is_dir():
            raise WorkspaceError(f"Dizin bulunamadı: {rel_path or '.'}")
        entries: list[dict[str, Any]] = []
        for item in sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name.lower())):
            if item.name in IGNORED_DIRS:
                continue
            entries.append(
                {
                    "name": item.name,
                    "path": self.rel(item),
                    "is_dir": item.is_dir(),
                    "size": 0 if item.is_dir() else item.stat().st_size,
                }
            )
        return entries

    def tree(self, max_depth: int = 4, max_entries: int = 500) -> list[dict[str, Any]]:
        """Flattened directory tree (used by the agent's context building)."""
        results: list[dict[str, Any]] = []

        def walk(directory: Path, depth: int) -> None:
            if depth > max_depth or len(results) >= max_entries:
                return
            try:
                children = sorted(directory.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
            except OSError:
                return
            for item in children:
                if len(results) >= max_entries:
                    return
                if item.name in IGNORED_DIRS:
                    continue
                results.append({"path": self.rel(item), "is_dir": item.is_dir()})
                if item.is_dir():
                    walk(item, depth + 1)

        walk(self.root, 1)
        return results

    # -- reading ----------------------------------------------------------
    def read_text(self, rel_path: str, start_line: int = 0, end_line: int = 0) -> dict[str, Any]:
        path = self.resolve(rel_path)
        if not path.is_file():
            raise WorkspaceError(f"Dosya bulunamadı: {rel_path}")
        if path.stat().st_size > MAX_FILE_BYTES:
            raise WorkspaceError(f"Dosya çok büyük (> {MAX_FILE_BYTES} bayt): {rel_path}")
        content = path.read_text(encoding="utf-8", errors="replace")
        lines = content.splitlines()
        if start_line > 0 or end_line > 0:
            s = max(0, start_line - 1)
            e = len(lines) if end_line <= 0 else min(len(lines), end_line)
            lines = lines[s:e]
        return {
            "path": self.rel(path),
            "content": "\n".join(lines),
            "total_lines": len(content.splitlines()),
        }

    def exists(self, rel_path: str) -> bool:
        return self.resolve(rel_path).exists()

    # -- writing -----------------------------------------------------------
    def write_text(self, rel_path: str, content: str) -> dict[str, Any]:
        """Create or overwrite a file; returns the unified diff applied."""
        path = self.resolve(rel_path)
        if len(content.encode("utf-8", errors="replace")) > MAX_FILE_BYTES:
            raise WorkspaceError("İçerik çok büyük; yazma reddedildi.")
        old = ""
        existed = path.is_file()
        if existed:
            old = path.read_text(encoding="utf-8", errors="replace")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        rel = self.rel(path)
        logger.info("Wrote %s (%d bytes, existed=%s)", rel, len(content), existed)
        return {
            "path": rel,
            "created": not existed,
            "diff": unified_diff(old, content, rel),
            "bytes_written": len(content.encode("utf-8")),
        }

    def edit_text(self, rel_path: str, old_text: str, new_text: str, replace_all: bool = False) -> dict[str, Any]:
        """Replace ``old_text`` with ``new_text`` (whitespace-tolerant match)."""
        path = self.resolve(rel_path)
        if not path.is_file():
            raise WorkspaceError(f"Dosya bulunamadı: {rel_path}")
        original = path.read_text(encoding="utf-8", errors="replace")

        def _norm(s: str) -> str:
            return re.sub(r"[ \t]+", " ", s).strip()

        target = old_text
        if target in original:
            replacements = original.count(target) if replace_all else 1
            updated = original.replace(target, new_text, 0 if replace_all else 1)
        else:
            # Fuzzy fallback: match on normalised whitespace line-by-line.
            norm_target_lines = _norm(target)
            found = False
            updated = original
            lines = original.split("\n")
            for i in range(len(lines)):
                for j in range(i + 1, len(lines) + 1):
                    chunk = "\n".join(lines[i:j])
                    if _norm(chunk) == norm_target_lines:
                        updated = "\n".join(lines[:i] + [new_text] + lines[j:])
                        found = True
                        break
                if found:
                    break
            if not found:
                raise WorkspaceError(
                    f"Düzenleme hedefi '{rel_path}' içinde bulunamadı "
                    "(old_text dosyayla eşleşmiyor)."
                )
            replacements = 1

        path.write_text(updated, encoding="utf-8")
        rel = self.rel(path)
        logger.info("Edited %s (%d replacement(s))", rel, replacements)
        return {
            "path": rel,
            "created": False,
            "replacements": replacements,
            "diff": unified_diff(original, updated, rel),
        }

    def rename(self, rel_path: str, new_rel_path: str) -> dict[str, Any]:
        src = self.resolve(rel_path)
        dst = self.resolve(new_rel_path)
        if not src.exists():
            raise WorkspaceError(f"Kaynak bulunamadı: {rel_path}")
        if dst.exists():
            raise WorkspaceError(f"Hedef zaten mevcut: {new_rel_path}")
        dst.parent.mkdir(parents=True, exist_ok=True)
        src.rename(dst)
        logger.info("Renamed %s -> %s", rel_path, new_rel_path)
        return {"from": rel_path, "to": self.rel(dst)}

    def delete(self, rel_path: str) -> dict[str, Any]:
        path = self.resolve(rel_path)
        if not path.exists():
            raise WorkspaceError(f"Silme hedefi bulunamadı: {rel_path}")
        if path == self.root:
            raise WorkspaceSecurityError("Çalışma alanı kökü silinemez.")
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
        logger.info("Deleted %s", rel_path)
        return {"deleted": rel_path}

    # -- searching ---------------------------------------------------------
    def search_text(self, pattern: str, rel_path: str = "", case_sensitive: bool = False) -> list[dict[str, Any]]:
        """Regex/substring search across text files (bounded results)."""
        base = self.resolve(rel_path) if rel_path else self.root
        try:
            regex = re.compile(pattern, 0 if case_sensitive else re.IGNORECASE)
        except re.error:
            regex = re.compile(re.escape(pattern), 0 if case_sensitive else re.IGNORECASE)

        matches: list[dict[str, Any]] = []

        def scan_file(file_path: Path) -> None:
            try:
                if file_path.stat().st_size > MAX_FILE_BYTES or file_path.is_dir():
                    return
                text = file_path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                return
            if "\x00" in text[:8192]:
                return  # binary
            for lineno, line in enumerate(text.splitlines(), start=1):
                if regex.search(line):
                    matches.append(
                        {
                            "path": self.rel(file_path),
                            "line": lineno,
                            "text": line.strip()[:300],
                        }
                    )
                    if len(matches) >= MAX_SEARCH_RESULTS:
                        raise StopIteration

        def walk(directory: Path) -> None:
            if not directory.is_dir():
                scan_file(directory)
                return
            for item in sorted(directory.rglob("*")):
                if any(part in IGNORED_DIRS for part in item.parts):
                    continue
                if item.is_file():
                    scan_file(item)
                if len(matches) >= MAX_SEARCH_RESULTS:
                    return

        try:
            walk(base)
        except StopIteration:
            pass
        return matches
