"""Headless UI smoke tests (QT_QPA_PLATFORM=offscreen).

Verifies the main window and usage-limit editor instantiate, wire their
panels, and handle a simulated quota banner without crashing.
"""

import pytest

pytestmark = pytest.mark.usefixtures("qapp")


def _make_config(workspace_root: str):
    from agentdesk.core.config import AppConfig

    return AppConfig(workspace_root=workspace_root, max_retries=0, connect_timeout=1)


def test_main_window_opens(qapp, workspace_dir):
    from agentdesk.ui.main_window import MainWindow

    window = MainWindow(config=_make_config(str(workspace_dir)))
    try:
        assert window.workspace is not None
        assert window.registry is not None
        assert window.chat is not None
        assert window.editor is not None
        assert window.terminal is not None
        assert window.session_list.count() >= 0
        window.chat.show_banner("test banner")
        assert window.chat.banner.isVisibleTo(window.chat)
        window.chat.hide_banner()
        assert not window.chat.banner.isVisibleTo(window.chat)
    finally:
        window.close()


def test_chat_rendering(qapp):
    from agentdesk.ui.chat_panel import ChatPanel, MessageBubble

    panel = ChatPanel()
    panel.add_user_message("Merhaba")
    bubble = panel.begin_assistant_message()
    bubble.append_delta("**kalın** cevap")
    card = panel.add_tool_card({"tool": "run_command", "args": {"command": "pytest"}})
    panel.update_tool_card(card, {"ok": True})
    panel.restore_history(
        [
            {"role": "user", "content": "geçmiş"},
            {"role": "assistant", "content": "# Başlık\nkod ```py```"},
        ]
    )


def test_diff_rendering(qapp):
    from agentdesk.ui.editor_panel import diff_to_html

    html = diff_to_html("--- a/x\n+++ b/x\n@@ -1 +1 @@\n-old\n+new\n")
    assert "diff-add" in html and "diff-del" in html
    assert diff_to_html("")  # empty diff handled


def test_usage_limit_editor_window(qapp):
    from agentdesk.usage_editor.main import UsageLimitEditorWindow

    window = UsageLimitEditorWindow()
    try:
        assert window.req_spin.value() > 0
        window.req_spin.setValue(123)
        # Saving with the default (unlocked) policy must succeed (no dialog).
        assert window.save_limits() is None
        assert window.store.load().max_requests_per_day == 123
    finally:
        window.close()
