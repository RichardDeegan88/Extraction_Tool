"""Unit tests for fetch_readings.py."""

from __future__ import annotations

from pathlib import Path

import fetch_readings


class TestCategorise:
    def test_video_hosts(self):
        assert fetch_readings.categorise("https://youtube.com/watch?v=1") == "video"
        assert fetch_readings.categorise("https://youtu.be/abc") == "video"
        assert fetch_readings.categorise("https://vimeo.com/123") == "video"

    def test_gated_hosts(self):
        assert fetch_readings.categorise("https://www.jstor.org/stable/123") == "gated"
        assert fetch_readings.categorise("https://academic.oup.com/article") == "gated"

    def test_direct_pdf(self):
        assert fetch_readings.categorise("https://example.com/paper.pdf") == "pdf"

    def test_article(self):
        assert fetch_readings.categorise("https://example.com/article") == "article"


class TestSafeFilename:
    def test_includes_hash_and_is_safe(self):
        url = "https://example.com/path/to/article?foo=bar"
        name = fetch_readings.safe_filename(url)
        assert "/" not in name
        assert "?" not in name
        assert "_" in name
        assert len(name) > 8

    def test_distinct_urls_produce_distinct_names(self):
        a = fetch_readings.safe_filename("https://example.com/a")
        b = fetch_readings.safe_filename("https://example.com/b")
        assert a != b


class TestStripHidden:
    def test_removes_invisible_codepoints(self):
        text = "visible\u200b\u200fhidden\u115f"
        assert fetch_readings.strip_hidden(text) == "visiblehidden"


class TestLooksGated:
    def test_phrase_detection(self):
        text = "Please sign in to continue reading this article."
        assert "sign in to continue" in fetch_readings.looks_gated(text, 500)

    def test_low_word_count(self):
        text = "Login form."
        assert "only 2 words" in fetch_readings.looks_gated(text, 2)

    def test_returns_empty_for_clean_text(self):
        text = "This is a long article with many words about an important topic. " * 20
        assert fetch_readings.looks_gated(text, 500) == ""


class TestGateDetectionStrengthening:
    """Tests for the improved login-page structural detection."""

    def test_login_form_flagged(self):
        html = (
            '<html><body>'
            '<form action="/login?return=article"><input name="password"></form>'
            '</body></html>'
        )
        text = fetch_readings.html_to_text_builtin(html)
        assert fetch_readings.page_looks_gated(html, text, 500) == "page contains a login form"

    def test_non_login_form_not_flagged(self):
        html = '<html><body><form action="/search"><input name="q"></form></body></html>'
        text = fetch_readings.html_to_text_builtin(html)
        assert fetch_readings.page_looks_gated(html, text, 500) == ""

    def test_min_words_threshold(self):
        text = "Short article."
        assert "only 5 words" in fetch_readings.looks_gated(text, 5)
        assert fetch_readings.looks_gated(text, 5, min_words=3) == ""
        assert "only 2 words" in fetch_readings.looks_gated(text, 2, min_words=5)


class TestCli:
    def test_version_flag(self):
        import subprocess
        result = subprocess.run(
            ["python", "fetch_readings.py", "--version"],
            capture_output=True, text=True, cwd=Path(__file__).parent.parent,
        )
        assert result.returncode == 0, result.stderr
        assert "1.1.0" in result.stdout


class TestDryRun:
    def test_dry_run_writes_no_files(self, tmp_path: Path):
        urls_path = tmp_path / "urls.txt"
        urls_path.write_text(
            "https://example.com/article\n"
            "https://example.com/paper.pdf\n"
            "https://www.jstor.org/stable/123\n",
            encoding="utf-8",
        )
        out_dir = tmp_path / "readings"
        import subprocess
        result = subprocess.run(
            ["python", "fetch_readings.py", "--urls", str(urls_path),
             "--out-dir", str(out_dir), "--dry-run"],
            capture_output=True, text=True, cwd=Path(__file__).parent.parent,
        )
        assert result.returncode == 0, result.stderr
        assert "DRY RUN" in result.stderr
        assert not any(out_dir.glob("*"))
