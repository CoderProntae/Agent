"""Allow ``python -m agentdesk.usage_editor`` to launch the quota editor."""

from agentdesk.usage_editor.main import main

if __name__ == "__main__":
    raise SystemExit(main())
