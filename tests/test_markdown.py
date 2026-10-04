"""Markdown renderer safety and features."""

from agentdesk.core.markdown import md_to_html


def test_escapes_html_injection():
    html = md_to_html("<script>alert(1)</script>")
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_code_fence():
    html = md_to_html("```python\nprint('hi')\n```")
    assert "code-block" in html
    assert "python" in html
    assert "print(" in html


def test_bold_italic_inline_code():
    html = md_to_html("**bold** *it* `code`")
    assert "<b>bold</b>" in html
    assert "<i>it</i>" in html
    assert "inline-code" in html


def test_link_sanitisation():
    safe = md_to_html("[ok](https://example.com)")
    assert 'href="https://example.com"' in safe
    evil = md_to_html("[x](javascript:alert(1))")
    assert "javascript:" not in evil


def test_lists_and_headings():
    html = md_to_html("# Title\n- one\n- two\n1. first")
    assert "<h1>Title</h1>" in html
    assert "<ul>" in html and "<li>one</li>" in html
    assert "<ol>" in html and "<li>first</li>" in html
