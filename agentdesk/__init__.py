"""AgentDesk — Yerel Yapay Zeka Kodlama Ajanı ve Çalışma Alanı Masaüstü Uygulaması.

AgentDesk is an enterprise-grade, dark-themed desktop application that behaves
like an autonomous AI developer inside a user-selected local workspace:

* Streams chat completions from a **local Ollama server** (default port
  ``11435`` — deliberately *not* the stock ``11434``).
* Executes sandboxed file operations, headless terminal commands and git
  workflows on behalf of the model.
* Enforces corporate usage quotas (requests / tokens / executions / active
  time) through an encrypted local limit store that is managed by the
  companion ``UsageLimitEditor`` executable.

Package layout
--------------
``agentdesk.core``    : configuration, Ollama client, agent loop, quota engine.
``agentdesk.tools``   : workspace / terminal / git tool implementations.
``agentdesk.ui``      : PySide6 (Qt) dark-themed multi-pane GUI.
``agentdesk.usage_editor`` : standalone quota administration tool.
"""

from __future__ import annotations

__version__ = "1.0.0"
__app_name__ = "AgentDesk"
