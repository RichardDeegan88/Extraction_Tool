"""Tests for ReadingService extraction chain and browser routing."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

pytest.importorskip("bs4")
pytest.importorskip("trafilatura")

import trafilatura

from extraction_tool.contracts.readings import ReadingRequest
from extraction_tool.services.reading_service import ReadingService


def test_trafilatura_is_primary_when_enough_words() -> None:
    html = "<html><body>" + "<p>Word. </p>" * 80 + "</body></html>"
    _, _, extractor = ReadingService._extract_article(html.encode("utf-8"), "")
    assert extractor == "trafilatura"


def test_bs4_is_middle_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(trafilatura, "extract", lambda *a, **k: "too short")
    html = "<html><body><p>" + "word. " * 80 + "</p></body></html>"
    text, _, extractor = ReadingService._extract_article(html.encode("utf-8"), "")
    assert extractor == "beautifulsoup4"
    assert "word" in text


def test_builtin_is_last_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(trafilatura, "extract", lambda *a, **k: "too short")
    monkeypatch.setattr(
        "extraction_tool.extraction.html.extract_with_bs4",
        lambda html: "short",
    )
    html = "<html><body><p>tiny</p></body></html>"
    _, _, extractor = ReadingService._extract_article(html.encode("utf-8"), "")
    assert extractor == "built-in stripper"


def test_use_browser_routes_to_rendered_html(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    urls_file = tmp_path / "urls.txt"
    urls_file.write_text("https://example.com/article\n", encoding="utf-8")
    repo = MagicMock()
    repo.categorise.return_value = "article"
    repo.safe_filename.return_value = "example_com_article"
    paragraphs = " ".join(f"word{i}" for i in range(200))
    html = f"<html><body><article><p>{paragraphs}</p></article></body></html>"
    repo.fetch_rendered_html.return_value = (html, "")

    service = ReadingService(repo)
    request = ReadingRequest(
        source=None,
        urls_file=str(urls_file),
        out_dir=str(tmp_path / "out"),
        use_browser=True,
    )
    result = service.acquire_readings(request)

    assert result.success
    repo.fetch_rendered_html.assert_called_once()
    assert repo.fetch_url.call_count == 0
    out = tmp_path / "out" / "example_com_article.txt"
    assert out.exists()
    assert "word0" in out.read_text(encoding="utf-8")


def test_use_browser_false_uses_fetch_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    urls_file = tmp_path / "urls.txt"
    urls_file.write_text("https://example.com/article\n", encoding="utf-8")
    repo = MagicMock()
    repo.categorise.return_value = "article"
    repo.safe_filename.return_value = "example_com_article"
    paragraphs = " ".join(f"word{i}" for i in range(200))
    html = f"<html><body><article><p>{paragraphs}</p></article></body></html>"
    repo.fetch_url.return_value = (html.encode("utf-8"), "text/html", "", None)

    service = ReadingService(repo)
    request = ReadingRequest(
        source=None,
        urls_file=str(urls_file),
        out_dir=str(tmp_path / "out"),
        use_browser=False,
    )
    result = service.acquire_readings(request)

    assert result.success
    repo.fetch_url.assert_called_once()
    assert repo.fetch_rendered_html.call_count == 0
