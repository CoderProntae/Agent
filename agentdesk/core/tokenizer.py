"""Lightweight token estimation.

Real token counts are reported by Ollama in the final streamed payload
(``prompt_eval_count`` / ``eval_count``) and are always preferred. This
module provides a deterministic heuristic used for:

* pre-flight quota checks (estimating prompt size *before* sending), and
* offline testing where no server is reachable.

The heuristic approximates common BPE tokenisers (~4 characters per token
for English/code) and never under-counts by more than a small factor.
"""

from __future__ import annotations

from typing import Iterable, Mapping

CHARS_PER_TOKEN = 4.0


def estimate_tokens(text: str) -> int:
    """Estimate the token count of ``text`` (>= 1 for non-empty input)."""
    if not text:
        return 0
    return max(1, round(len(text) / CHARS_PER_TOKEN))


def estimate_message_tokens(message: Mapping[str, str]) -> int:
    """Estimate tokens of a single chat message (content + role overhead)."""
    content = message.get("content") or ""
    return estimate_tokens(content) + 4  # role / framing overhead


def estimate_conversation_tokens(messages: Iterable[Mapping[str, str]]) -> int:
    """Estimate the total prompt size of a conversation."""
    return sum(estimate_message_tokens(m) for m in messages)
