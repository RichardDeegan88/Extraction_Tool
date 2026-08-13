"""Tests for BeautifulSoup HTML-to-text extraction (middle-tier fallback)."""

from __future__ import annotations

import pytest

pytest.importorskip("bs4")

from extraction_tool.extraction.html import extract_with_bs4

_HTML = (
    "<html><head><title>T</title><style>.x{color:red}</style>"
    "<script>var a=1;</script></head>"
    "<body><nav>menu</nav><header>banner</header>"
    "<article><h1>Heading</h1><p>First paragraph of text.</p>"
    "<p>Second paragraph with more words.</p></article>"
    "<footer>copyright</footer></body></html>"
)


def test_strips_block_elements_and_keeps_text():
    text = extract_with_bs4(_HTML)
    assert "menu" not in text
    assert "banner" not in text
    assert "copyright" not in text
    assert "var a=1" not in text
    assert "First paragraph of text." in text
    assert "Second paragraph" in text


def test_removes_invisible_codepoints():
    dirty = "visible\u200b\u200fhidden\u115f"
    assert extract_with_bs4(f"<p>{dirty}</p>") == "visiblehidden"


def test_collapses_blank_lines():
    html = "<p>a</p><p></p><p>b</p>"
    text = extract_with_bs4(html)
    assert "\n\n\n" not in text


def test_raises_actionable_error_without_bs4(monkeypatch):
    import sys

    monkeypatch.setitem(sys.modules, "bs4", None)
    with pytest.raises(ImportError, match="beautifulsoup4"):
        extract_with_bs4("<p>hi</p>")
