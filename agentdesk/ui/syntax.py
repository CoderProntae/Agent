"""Lightweight regex-based syntax highlighter for the code editor panel.

Covers the languages the agent touches most (Python, JavaScript/TypeScript,
JSON, YAML, shell, TOML/INI, Markdown). Not a full grammar — but fast and
dependency-free, which matters when editing large files on modest hardware.
"""

from __future__ import annotations

import re

from PySide6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat

_KEYWORDS = {
    "python": r"\b(def|class|return|if|elif|else|for|while|try|except|finally|import|from|as|with|lambda|yield|async|await|pass|break|continue|raise|global|nonlocal|assert|del|in|is|not|and|or|True|False|None|self)\b",
    "js": r"\b(function|const|let|var|return|if|else|for|while|do|switch|case|break|continue|new|delete|typeof|instanceof|class|extends|super|this|import|export|from|default|try|catch|finally|throw|async|await|yield|of|in|null|undefined|true|false)\b",
    "shell": r"\b(if|then|else|elif|fi|for|in|do|done|while|case|esac|function|echo|export|local|return|exit|set|source|cd|ls|cat|grep|awk|sed|curl|git|pip|python|npm|node)\b",
}

_COMMENT_PATTERNS = {
    "python": r"#[^\n]*",
    "js": r"//[^\n]*",
    "shell": r"#[^\n]*",
    "yaml": r"#[^\n]*",
    "ini": r"[#;][^\n]*",
}

_STRING_RE = re.compile(r"\"\"\".*?\"\"\"|\'\'\'.*?\'\'\"|\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'", re.DOTALL)
_NUMBER_RE = re.compile(r"\b\d+(?:\.\d+)?\b")
_DECORATOR_RE = re.compile(r"^\s*@\w+", re.MULTILINE)
_FUNCTION_RE = re.compile(r"\b(?:def|function)\s+(\w+)|\b(\w+)(?=\s*\()")


def _fmt(color: str, bold: bool = False, italic: bool = False) -> QTextCharFormat:
    fmt = QTextCharFormat()
    fmt.setForeground(QColor(color))
    if bold:
        fmt.setFontWeight(QFont.Bold)
    if italic:
        fmt.setFontItalic(True)
    return fmt


class SyntaxHighlighter(QSyntaxHighlighter):
    """Apply language-aware colouring to a document."""

    def __init__(self, document, language: str = "") -> None:
        super().__init__(document)
        self.language = (language or "").lower()
        self._rules: list[tuple[re.Pattern, QTextCharFormat]] = []
        self._build_rules()

    def _build_rules(self) -> None:
        lang = self.language
        if lang in ("javascript", "typescript", "jsx", "tsx"):
            lang = "js"
        if lang in ("sh", "bash", "zsh", "batch", "powershell"):
            lang = "shell"
        if lang in ("toml", "cfg", "conf"):
            lang = "ini"

        kw = _KEYWORDS.get(lang) or _KEYWORDS["python"] if lang in ("python", "js", "shell") else None
        if kw:
            self._rules.append((re.compile(kw), _fmt("#ff7b72", bold=True)))
        comment = _COMMENT_PATTERNS.get(lang)
        if comment:
            self._rules.append((re.compile(comment), _fmt("#8b949e", italic=True)))
        self._rules.append((_STRING_RE, _fmt("#a5d6ff")))
        self._rules.append((_NUMBER_RE, _fmt("#79c0ff")))
        if lang == "python":
            self._rules.append((_DECORATOR_RE, _fmt("#d2a8ff")))
        self._rules.append((_FUNCTION_RE, _fmt("#d2a8ff")))

    def highlightBlock(self, text: str) -> None:  # noqa: N802 (Qt naming)
        for pattern, fmt in self._rules:
            for match in pattern.finditer(text):
                self.setFormat(match.start(), match.end() - match.start(), fmt)
