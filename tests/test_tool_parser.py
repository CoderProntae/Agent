"""Tool-call extraction robustness."""

from agentdesk.core.tool_parser import extract_tool_calls


def test_fenced_tool_block():
    text = 'Sure.\n```tool\n{"tool": "write_file", "args": {"path": "a.py", "content": "x"}}\n```\nDone.'
    calls = extract_tool_calls(text)
    assert len(calls) == 1
    assert calls[0]["tool"] == "write_file"
    assert calls[0]["args"]["path"] == "a.py"


def test_json_fence_alias():
    text = '```json\n{"tool": "run_command", "args": {"command": "pytest"}}\n```'
    calls = extract_tool_calls(text)
    assert calls and calls[0]["tool"] == "run_command"


def test_bare_json_without_fence():
    text = 'I will read the file. {"tool": "read_file", "args": {"path": "x.txt"}}'
    calls = extract_tool_calls(text)
    assert calls and calls[0]["tool"] == "read_file"


def test_key_aliases():
    text = '{"name": "git_status", "parameters": {}}'
    calls = extract_tool_calls(text)
    assert calls and calls[0]["tool"] == "git_status"
    assert calls[0]["args"] == {}


def test_trailing_comma_repair():
    text = '{"tool": "delete_file", "args": {"path": "tmp.txt",}}'
    calls = extract_tool_calls(text)
    assert calls and calls[0]["args"]["path"] == "tmp.txt"


def test_multiple_calls_in_order():
    text = (
        '```tool\n{"tool": "read_file", "args": {"path": "a"}}\n```\n'
        'then\n```tool\n{"tool": "write_file", "args": {"path": "b", "content": ""}}\n```'
    )
    calls = extract_tool_calls(text)
    assert [c["tool"] for c in calls] == ["read_file", "write_file"]


def test_no_calls():
    assert extract_tool_calls("Just a plain final answer.") == []
    assert extract_tool_calls("") == []
    assert extract_tool_calls('{"not_a_tool": true}') == []


def test_malformed_json_skipped_not_raised():
    text = '```tool\n{"tool": "broken", "args": {"x": }\n```\nplain'
    assert extract_tool_calls(text) == []
