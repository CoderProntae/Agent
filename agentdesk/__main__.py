"""Allow ``python -m agentdesk`` to launch the desktop application."""

from agentdesk.app import main

if __name__ == "__main__":
    raise SystemExit(main())
