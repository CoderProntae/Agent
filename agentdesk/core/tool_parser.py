"""Robust extraction of tool calls from model output.

The agent asks the model to emit tool invocations as JSON objects with a
``tool`` key and an ``args`` object, optionally wrapped in a fenced code
block. Local models are imperfect, so this parser is deliberately lenient:

* fenced ```tool / ```json blocks are tried first;
* any brace-delimited JSON object in the raw text is scanned as a fallback;
* common key aliases are accepted (``name``/``action``, ``args``/
  ``parameters``/``arguments``/``inputs``);
* trailing commas — the single most frequent local-model mistake — are
  repaired automatically.

Parsing never raises: invalid fragments are skipped and logged.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

_FENCED_RE = re.compile(r"```(?:tool|json|toolcall)?\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)
_TRAILING_COMMA_RE = re.compile(r",\s*([}\]])")
_TOOL_KEY_ALIASES = ("tool", "name", "action", "function")
_ARGS_KEY_ALIASES = ("args", "arguments", "parameters", "inputs", "params")


def _repair(fragment: str) -> str:
    """Best-effort cleanup of JSON emitted by small local models."""
    fragment = fragment.strip()
    fragment = _TRAILING_COMMA_RE.sub(r"\1", fragment)
    # Strip Markdown residue that occasionally leaks inside fences.
    fragment = fragment.strip("` \t")
    return fragment


def _coerce(obj: Any) -> dict[str, Any] | None:
    """Normalise a parsed JSON object into ``{"tool":…, "args":…}``."""
    if not isinstance(obj, dict):
        return None
    tool = next((obj[k] for k in _TOOL_KEY_ALIASES if isinstance(obj.get(k), str)), None)
    if not tool:
        return None
    args: Any = {}
    for key in _ARGS_KEY_ALIASES:
        if key in obj and isinstance(obj[key], dict):
            args = obj[key]
            break
    return {"tool": tool.strip(), "args": args}


def _iter_json_candidates(text: str):
    """Yield every brace-delimited substring that starts with ``{"``."""
    start = text.find("{")
    while start != -1:
        depth = 0
        in_string = False
        escaped = False
        for idx in range(start, len(text)):
            ch = text[idx]
            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    yield text[start : idx + 1]
                    break
        start = text.find("{", start + 1)


def extract_tool_calls(text: str) -> list[dict[str, Any]]:
    """Return the ordered list of tool calls embedded in ``text``."""
    if not text:
        return []
    calls: list[dict[str, Any]] = []
    seen_fragments: set[str] = set()

    candidates: list[str] = []
    for fenced in _FENCED_RE.findall(text):
        candidates.append(fenced)
    for fragment in _iter_json_candidates(text):
        if fragment not in seen_fragments:
            candidates.append(fragment)

    for raw in candidates:
        fragment = _repair(raw)
        if fragment in seen_fragments:
            continue
        seen_fragments.add(fragment)
        try:
            obj = json.loads(fragment)
        except json.JSONDecodeError:
            continue
        call = _coerce(obj)
        if call and call not in calls:
            calls.append(call)

    if calls:
        logger.debug("Extracted %d tool call(s): %s", len(calls), [c["tool"] for c in calls])
    return calls
