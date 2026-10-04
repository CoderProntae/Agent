"""Tool registry: exposes workspace/terminal/git capabilities to the model.

Each tool is a ``(handler, description, parameter docs)`` triple. The agent
loop builds its system prompt from :meth:`ToolRegistry.describe` and routes
parsed tool calls through :meth:`ToolRegistry.execute`, which always returns
a JSON-serialisable dict — errors included — so the model can observe and
self-correct from failures.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from agentdesk.core.usage_tracker import QuotaExceededError, UsageTracker
from agentdesk.tools.git import GitError, GitManager
from agentdesk.tools.terminal import TerminalRunner
from agentdesk.tools.workspace import Workspace, WorkspaceError, WorkspaceSecurityError

logger = logging.getLogger(__name__)


class ToolRegistry:
    """Central dispatch for every capability the agent may invoke."""

    def __init__(
        self,
        workspace: Workspace,
        terminal: TerminalRunner,
        git: GitManager | None,
        usage: UsageTracker,
    ) -> None:
        self.workspace = workspace
        self.terminal = terminal
        self.git = git
        self.usage = usage
        self._tools: dict[str, Callable[..., dict[str, Any]]] = {
            "list_files": self._list_files,
            "read_file": self._read_file,
            "write_file": self._write_file,
            "edit_file": self._edit_file,
            "rename_file": self._rename_file,
            "delete_file": self._delete_file,
            "search_text": self._search_text,
            "run_command": self._run_command,
            "git_init": self._git_init,
            "git_status": self._git_status,
            "git_diff": self._git_diff,
            "git_add": self._git_add,
            "git_commit": self._git_commit,
            "git_branch": self._git_branch,
            "git_log": self._git_log,
        }

    # -- prompt building -------------------------------------------------
    def describe(self) -> str:
        """Human/model-readable catalogue of available tools."""
        return "\n".join(
            [
                "- list_files(path=''): list directory entries",
                "- read_file(path, start_line=0, end_line=0): read file text",
                "- write_file(path, content): create/overwrite file (returns diff)",
                "- edit_file(path, old_text, new_text, replace_all=false): replace exact snippet",
                "- rename_file(path, new_path): rename/move inside workspace",
                "- delete_file(path): delete file or folder",
                "- search_text(pattern, path=''): regex search across files",
                "- run_command(command, timeout_seconds=300): run shell command in workspace",
                "- git_init(): initialise repository if missing",
                "- git_status(): porcelain status entries",
                "- git_diff(staged=false): unified diff of working tree",
                "- git_add(paths=[]): stage files (default: all)",
                "- git_commit(message): commit staged changes",
                "- git_branch(name='', checkout=false): list/create branches",
                "- git_log(limit=20): recent commits",
            ]
        )

    # -- dispatch -----------------------------------------------------------
    def execute(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        """Run one tool call; never raises — failures are returned as data."""
        handler = self._tools.get(name)
        if handler is None:
            return {"error": f"Bilinmeyen araç: '{name}'. Kullanılabilir araçlar: {', '.join(sorted(self._tools))}"}
        try:
            result = handler(**args)
            if not isinstance(result, dict):
                result = {"result": result}
            result.setdefault("tool", name)
            return result
        except QuotaExceededError as exc:
            logger.warning("Tool %s blocked by quota: %s", name, exc)
            return {"tool": name, "error": f"KOTA AŞILDI: {exc}", "quota": exc.quota}
        except WorkspaceSecurityError as exc:
            logger.warning("Security violation in tool %s: %s", name, exc)
            return {"tool": name, "error": f"GÜVENLİK İHLALİ: {exc}"}
        except WorkspaceError as exc:
            return {"tool": name, "error": str(exc)}
        except GitError as exc:
            return {"tool": name, "error": str(exc)}
        except TypeError as exc:
            return {"tool": name, "error": f"Hatalı argümanlar: {exc}"}
        except Exception as exc:  # noqa: BLE001 — tool errors feed back to the model
            logger.exception("Tool %s crashed", name)
            return {"tool": name, "error": f"Beklenmeyen hata: {exc!r}"}

    # -- filesystem tools ---------------------------------------------------
    def _list_files(self, path: str = "") -> dict[str, Any]:
        return {"files": self.workspace.list_dir(path)}

    def _read_file(self, path: str, start_line: int = 0, end_line: int = 0) -> dict[str, Any]:
        return self.workspace.read_text(path, int(start_line or 0), int(end_line or 0))

    def _write_file(self, path: str, content: str) -> dict[str, Any]:
        return self.workspace.write_text(path, content)

    def _edit_file(
        self, path: str, old_text: str, new_text: str, replace_all: bool = False
    ) -> dict[str, Any]:
        return self.workspace.edit_text(path, old_text, new_text, bool(replace_all))

    def _rename_file(self, path: str, new_path: str) -> dict[str, Any]:
        return self.workspace.rename(path, new_path)

    def _delete_file(self, path: str) -> dict[str, Any]:
        return self.workspace.delete(path)

    def _search_text(self, pattern: str, path: str = "", case_sensitive: bool = False) -> dict[str, Any]:
        return {"matches": self.workspace.search_text(pattern, path, bool(case_sensitive))}

    # -- terminal --------------------------------------------------------
    def _run_command(self, command: str, timeout_seconds: int = 300) -> dict[str, Any]:
        self.usage.check_execution()
        result = self.terminal.run(command, timeout=int(timeout_seconds or 300))
        if not result.blocked:
            self.usage.record_execution()
        return {
            "command": result.command,
            "exit_code": result.exit_code,
            "timed_out": result.timed_out,
            "blocked": result.blocked,
            "block_reason": result.block_reason,
            "output_tail": result.tail[-60:],
        }

    # -- git -----------------------------------------------------------------
    def _require_git(self) -> GitManager:
        if self.git is None:
            raise WorkspaceError("Bu çalışma alanında git kullanılabilir değil.")
        return self.git

    def _git_init(self) -> dict[str, Any]:
        r = self._require_git().ensure_repo()
        return {"ok": r.ok, "output": r.output}

    def _git_status(self) -> dict[str, Any]:
        git = self._require_git()
        return {"entries": git.status(), "branch": git.current_branch()}

    def _git_diff(self, staged: bool = False, path: str | None = None) -> dict[str, Any]:
        return {"diff": self._require_git().diff(staged=bool(staged), path=path)}

    def _git_add(self, paths: list[str] | None = None) -> dict[str, Any]:
        r = self._require_git().add(paths)
        return {"ok": r.ok, "output": r.output}

    def _git_commit(self, message: str) -> dict[str, Any]:
        git = self._require_git()
        if not git.status():
            pass  # allow empty-commit attempt to surface git's own message
        r = git.commit(message)
        return {"ok": r.ok, "output": r.output}

    def _git_branch(self, name: str = "", checkout: bool = False) -> dict[str, Any]:
        git = self._require_git()
        if name:
            r = git.create_branch(name, checkout=bool(checkout))
            return {"ok": r.ok, "output": r.output, "branch": git.current_branch()}
        return {"branches": git.branches(), "current": git.current_branch()}

    def _git_log(self, limit: int = 20) -> dict[str, Any]:
        return {"commits": self._require_git().log(int(limit or 20))}
