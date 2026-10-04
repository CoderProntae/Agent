"""Headless command execution: capture, timeouts, danger filter."""

import sys

import pytest

from agentdesk.tools.terminal import TerminalRunner, check_dangerous


@pytest.fixture()
def runner(workspace_dir):
    return TerminalRunner(default_cwd=str(workspace_dir))


def test_echo_captures_stdout(runner):
    result = runner.run("echo hello-from-test")
    assert result.ok
    assert result.exit_code == 0
    assert "hello-from-test" in result.output


def test_nonzero_exit_code(runner):
    cmd = "cmd /c exit 3" if sys.platform == "win32" else "exit 3"
    result = runner.run(cmd)
    assert result.exit_code == 3
    assert not result.ok


def test_stderr_is_captured(runner):
    cmd = "python -c \"import sys; sys.stderr.write('boom-err')\""
    result = runner.run(cmd)
    assert "boom-err" in result.output


def test_streaming_callback(runner):
    seen: list[str] = []
    runner.run("echo line1 & echo line2" if sys.platform == "win32" else "echo line1; echo line2",
               on_line=seen.append)
    joined = "\n".join(seen)
    assert "line1" in joined and "line2" in joined


def test_timeout_kills_process(runner):
    cmd = "ping -n 8 127.0.0.1" if sys.platform == "win32" else "sleep 8"
    result = runner.run(cmd, timeout=1)
    assert result.timed_out
    assert not result.ok
    assert result.duration < 7


def test_runs_inside_workspace_cwd(runner, workspace_dir):
    cmd = "cd" if sys.platform == "win32" else "pwd"
    result = runner.run(cmd)
    assert "project" in result.output


@pytest.mark.parametrize(
    "command",
    [
        "rm -rf /",
        "rm -rf /*",
        "mkfs.ext4 /dev/sda1",
        "dd if=/dev/zero of=/dev/sda",
        "format c:",
        "shutdown now",
    ],
)
def test_dangerous_commands_blocked(command):
    assert check_dangerous(command) is not None


def test_benign_commands_allowed():
    assert check_dangerous("pip install requests") is None
    assert check_dangerous("pytest -q") is None
    assert check_dangerous("git status") is None


def test_blocked_execution_result(runner):
    result = runner.run("rm -rf /")
    assert result.blocked
    assert result.block_reason
