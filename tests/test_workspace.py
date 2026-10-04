"""Sandboxed filesystem operations."""

import pytest

from agentdesk.tools.workspace import (
    Workspace,
    WorkspaceError,
    WorkspaceSecurityError,
)


@pytest.fixture()
def ws(workspace_dir):
    return Workspace(workspace_dir)


def test_sandbox_blocks_escape(ws):
    with pytest.raises(WorkspaceSecurityError):
        ws.resolve("../outside.txt")
    with pytest.raises(WorkspaceSecurityError):
        ws.resolve("a/../../b")
    with pytest.raises(WorkspaceSecurityError):
        ws.resolve("src/../../..")


def test_read_write_roundtrip(ws):
    result = ws.write_text("new.txt", "hello\nworld\n")
    assert result["created"] is True
    assert "+hello" in result["diff"]
    data = ws.read_text("new.txt")
    assert data["content"] == "hello\nworld"
    assert data["total_lines"] == 2


def test_write_over_produces_diff(ws):
    ws.write_text("src/utils.py", "def add(a, b):\n    return a + b\n")
    result = ws.write_text("src/utils.py", "def add(a, b):\n    return a + b + 0\n")
    assert result["created"] is False
    assert "-    return a + b" in result["diff"]
    assert "+    return a + b + 0" in result["diff"]


def test_edit_text_exact_and_fuzzy(ws):
    exact = ws.edit_text("src/utils.py", "return a + b", "return a + b + 1")
    assert exact["replacements"] == 1
    assert "+    return a + b + 1" in exact["diff"]
    # Fuzzy: tolerate whitespace differences in the needle.
    fuzzy = ws.edit_text("src/utils.py", "return   a   +   b   +   1", "return a + b + 2")
    assert fuzzy["replacements"] == 1


def test_edit_text_missing_target_raises(ws):
    with pytest.raises(WorkspaceError):
        ws.edit_text("src/utils.py", "not present anywhere", "x")


def test_list_dir_and_tree(ws):
    entries = ws.list_dir("")
    names = {e["name"] for e in entries}
    assert {"src", "README.md"} <= names
    tree_paths = {e["path"] for e in ws.tree()}
    assert "src/utils.py" in tree_paths


def test_rename_and_delete(ws):
    ws.write_text("temp.txt", "x")
    ws.rename("temp.txt", "moved.txt")
    assert not ws.exists("temp.txt")
    assert ws.exists("moved.txt")
    ws.delete("moved.txt")
    assert not ws.exists("moved.txt")


def test_delete_root_blocked(ws):
    with pytest.raises(WorkspaceSecurityError):
        ws.delete("")


def test_search_text(ws):
    matches = ws.search_text("def add")
    assert any(m["path"] == "src/utils.py" and m["line"] == 1 for m in matches)
    assert ws.search_text("zzz_no_match_zzz") == []


def test_read_with_line_range(ws):
    ws.write_text("lines.txt", "\n".join(f"l{i}" for i in range(1, 11)))
    data = ws.read_text("lines.txt", start_line=2, end_line=4)
    assert data["content"] == "l2\nl3\nl4"
    assert data["total_lines"] == 10


def test_missing_workspace_rejected(tmp_path):
    with pytest.raises(WorkspaceError):
        Workspace(tmp_path / "nope")
