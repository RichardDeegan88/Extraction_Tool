"""HTML-to-text extraction using BeautifulSoup as a middle-tier fallback.

This sits between trafilatura (primary) and the dependency-free built-in
stripper (last resort) in the article extraction chain. Output still passes
through normalization.sanitize() for invisible-character removal.
"""

from __future__ import annotations

from extraction_tool.extraction.normalization import sanitize

_BLOCK_TAGS = ("script", "style", "noscript", "svg", "form", "nav",
               "header", "footer", "aside")


def extract_with_bs4(html: str) -> str:
    """Extract readable text from HTML using BeautifulSoup.

    Raises:
        ImportError: if beautifulsoup4 is not installed, with an actionable
            message so the caller can fall back or report the missing dep.
    """
    try:
        from bs4 import BeautifulSoup  # type: ignore[import-not-found]
    except ImportError as e:
        raise ImportError(
            "beautifulsoup4 is required for BS4 extraction. "
            "Install it with: pip install beautifulsoup4"
        ) from e

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(_BLOCK_TAGS):
        tag.decompose()
    text = soup.get_text(separator="\n")
    text, _ = sanitize(text)
    lines = [ln.strip() for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln).strip()
