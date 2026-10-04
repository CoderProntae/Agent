"""Git wrapper over a temporary repository."""

import shutil
import subprocess

import pytest

from agentdesk.tools.git import GitManager


def _git_available() -> bool:
    return shutil.which("git") is not None


@pytest.fixture()
def git(workspace_dir):
    if not _git_available():
        pytest.skip("git not installed")
    # Keep CI hermetic: identity only inside this temp repo.
    manager = GitManager(str(workspace_dir))
    manager.ensure_repo()
    return manager


def test_ensure_repo_idempotent(git):
    assert git.is_repo()
    assert git.ensure_repo().ok


def test_status_add_commit_cycle(git, workspace_dir):
    entries = git.status()
    assert {e["path"] for e in entries} >= {"README.md", "src/utils.py"}

    assert git.add().ok
    commit = git.commit("feat: initial demo content")
    assert commit.ok, commit.output

    assert git.status() == []
    log = git.log()
    assert log and log[0]["subject"] == "feat: initial demo content"


def test_diff_reflects_edits(git, workspace_dir):
    git.add()
    git.commit("chore: baseline")
    (workspace_dir / "README.md").write_text("# Demo\nUpdated\n", encoding="utf-8")
    diff = git.diff()
    assert "+Updated" in diff


def test_branch_management_on_empty_repo(git):
    """Branch creation must work even before the first commit exists."""
    assert git.create_branch("feature/x").ok
    assert git.current_branch() == "feature/x"
    assert "feature/x" in git.branches()


def test_branch_management_with_commits(git, workspace_dir):
    git.add()
    git.commit("chore: baseline for branch test")
    assert git.create_branch("feature/y").ok
    assert "feature/y" in git.branches()
    assert git.checkout("main").ok
    assert git.current_branch() == "main"


def test_status_entries_are_individual_files(git, workspace_dir):
    """Untracked directories must expand to individual file entries."""
    (workspace_dir / "src" / "extra.py").write_text("x = 1\n", encoding="utf-8")
    paths = {e["path"] for e in git.status()}
    assert "src/extra.py" in paths
    assert "src/utils.py" in paths
    assert "src/" not in paths


def test_empty_commit_message_rejected(git):
    assert not git.commit("   ").ok
