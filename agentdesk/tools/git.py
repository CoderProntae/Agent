"""Git integration built on the system ``git`` binary.

Wraps the subset of git the agent needs: init / status / add / commit /
branch / checkout / diff / log. All calls run inside the bound workspace
directory and return structured results; nothing here ever pushes
credentials or touches remotes beyond what the user configures.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from dataclasses import dataclass

logger = logging.getLogger(__name__)

GIT_TIMEOUT = 120


@dataclass
class GitResult:
    ok: bool
    output: str
    exit_code: int = 0


class GitError(Exception):
    """Raised when git itself is unavailable."""


class GitManager:
    """High-level git operations scoped to a workspace directory."""

    def __init__(self, workspace_root: str):
        self.root = str(workspace_root)
        if shutil.which("git") is None:
            raise GitError("Sistemde 'git' yürütülebilir dosyası bulunamadı.")

    # -- low-level --------------------------------------------------------
    def _run(self, *args: str, timeout: int = GIT_TIMEOUT) -> GitResult:
        cmd = ["git", "-C", self.root, *args]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return GitResult(ok=False, output=f"[ZAMAN AŞIMI] {' '.join(cmd)}", exit_code=-1)
        output = (proc.stdout or "") + (proc.stderr or "")
        return GitResult(ok=proc.returncode == 0, output=output.strip(), exit_code=proc.returncode)

    # -- queries -----------------------------------------------------------
    def is_repo(self) -> bool:
        return self._run("rev-parse", "--is-inside-work-tree").ok

    def ensure_repo(self) -> GitResult:
        """``git init`` if the workspace is not a repository yet."""
        if self.is_repo():
            return GitResult(ok=True, output="Depo zaten mevcut.")
        result = self._run("init", "-b", "main")
        if not result.ok:  # older git without -b support
            result = self._run("init")
        logger.info("git init -> ok=%s", result.ok)
        return result

    def status(self) -> list[dict[str, str]]:
        """Parse ``git status --porcelain`` into structured entries.

        ``-uall`` expands untracked directories into individual files so the
        agent sees every pending path explicitly.
        """
        result = self._run("status", "--porcelain", "-uall")
        entries: list[dict[str, str]] = []
        if not result.ok:
            return entries
        for line in result.output.splitlines():
            if len(line) < 4:
                continue
            code, path = line[:2], line[3:].strip()
            if " -> " in path:
                path = path.split(" -> ", 1)[1]
            entries.append({"code": code.strip() or "?", "path": path.strip('"')})
        return entries

    def diff(self, staged: bool = False, path: str | None = None) -> str:
        args = ["diff", "--no-color"]
        if staged:
            args.append("--cached")
        if path:
            args += ["--", path]
        return self._run(*args).output

    def current_branch(self) -> str:
        """Name of the checked-out branch.

        ``branch --show-current`` is used because, unlike
        ``rev-parse --abbrev-ref HEAD``, it also reports unborn branches
        (repositories that have no commits yet).
        """
        result = self._run("branch", "--show-current")
        if result.ok and result.output.strip():
            return result.output.strip()
        # Detached HEAD → rev-parse gives the short SHA / "HEAD".
        fallback = self._run("rev-parse", "--abbrev-ref", "HEAD")
        return fallback.output.strip() if fallback.ok else ""

    def branches(self) -> list[str]:
        result = self._run("branch", "--format=%(refname:short)")
        names = [b.strip() for b in result.output.splitlines() if b.strip()] if result.ok else []
        if not names:
            # Unborn branches (no commits yet) have no ref; parse plain output.
            plain = self._run("branch")
            if plain.ok:
                for line in plain.output.splitlines():
                    stripped = line[2:].strip() if line.startswith("* ") else line.strip()
                    if stripped:
                        names.append(stripped)
        if not names:
            # Last resort: the checked-out unborn branch (git >= 2.23 reports
            # it only via --show-current).
            current = self.current_branch()
            if current and current != "HEAD":
                names.append(current)
        return names

    def log(self, limit: int = 20) -> list[dict[str, str]]:
        fmt = "%h%x1f%an%x1f%ad%x1f%s"
        result = self._run("log", f"--max-count={int(limit)}", f"--pretty=format:{fmt}", "--date=short")
        commits: list[dict[str, str]] = []
        if not result.ok:
            return commits
        for line in result.output.splitlines():
            parts = line.split("\x1f")
            if len(parts) == 4:
                commits.append(
                    {"hash": parts[0], "author": parts[1], "date": parts[2], "subject": parts[3]}
                )
        return commits

    # -- mutations ---------------------------------------------------------
    def add(self, paths: list[str] | None = None) -> GitResult:
        if paths:
            return self._run("add", "--", *paths)
        return self._run("add", "-A", ".")

    def commit(self, message: str) -> GitResult:
        if not message.strip():
            return GitResult(ok=False, output="Commit mesajı boş olamaz.", exit_code=1)
        self._run("config", "user.name", "AgentDesk")
        self._run("config", "user.email", "agentdesk@localhost")
        result = self._run("commit", "-m", message.strip())
        logger.info("git commit -> ok=%s", result.ok)
        return result

    def create_branch(self, name: str, checkout: bool = False) -> GitResult:
        """Create a branch; transparently handles repositories with no commits.

        ``git branch <name>`` fails on an unborn HEAD ("not a valid object
        name"), so when that happens we fall back to ``git checkout -b``,
        which is allowed to create the initial unborn branch.
        """
        if checkout:
            return self._run("checkout", "-b", name)
        result = self._run("branch", name)
        if not result.ok and "not a valid object name" in result.output:
            fallback = self._run("checkout", "-b", name)
            # Return to the original (unborn) branch if there was one.
            return fallback
        return result

    def checkout(self, name: str) -> GitResult:
        return self._run("checkout", name)
