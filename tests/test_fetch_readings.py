"""Unit tests for fetch_readings.py."""

from __future__ import annotations

import io
import socket
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

import fetch_readings
import pytest


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

    def test_login_form_flagged_when_it_domininates(self):
        html = (
            '<html><body>'
            '<form action="/login?return=article"><input name="password"></form>'
            '</body></html>'
        )
        text = fetch_readings.html_to_text_builtin(html)
        assert "login form" in fetch_readings.page_looks_gated(html, text, 500)

    def test_non_login_form_not_flagged(self):
        html = '<html><body><form action="/search"><input name="q"></form></body></html>'
        text = fetch_readings.html_to_text_builtin(html)
        assert fetch_readings.page_looks_gated(html, text, 500) == ""

    def test_long_article_with_unrelated_login_widget_not_flagged(self):
        """A login widget in the header of a real article should not gate it."""
        long_text = "This is a long article with many words. " * 50
        html = (
            '<html><body>'
            '<header><form action="/login"><input name="password"></form></header>'
            '<article>' + long_text + '</article>'
            '</body></html>'
        )
        assert fetch_readings.page_looks_gated(html, long_text, 600) == ""

    def test_short_text_with_login_form_flagged(self):
        html = (
            '<html><body>'
            '<header><form action="/login"><input name="password"></form></header>'
            '<article>Short article.</article>'
            '</body></html>'
        )
        text = "Short article."
        assert "login form" in fetch_readings.page_looks_gated(html, text, 2)

    def test_min_words_threshold(self):
        text = "Short article."
        assert "only 5 words" in fetch_readings.looks_gated(text, 5)
        assert fetch_readings.looks_gated(text, 5, min_words=3) == ""
        assert "only 2 words" in fetch_readings.looks_gated(text, 2, min_words=5)


class TestPrivateNetworkBlocking:
    def _mock_addr(self, ip: str):
        if ":" in ip:
            return (socket.AF_INET6, None, None, None, (ip, 0, 0, 0))
        return (socket.AF_INET, None, None, None, (ip, 0))

    def test_loopback_ipv4_blocked(self):
        with patch("socket.getaddrinfo", return_value=[self._mock_addr("127.0.0.1")]):
            ok, reason = fetch_readings._is_public_host("localhost")
            assert ok is False
            assert "loopback" in reason.lower()

    def test_private_ipv4_blocked(self):
        with patch("socket.getaddrinfo", return_value=[self._mock_addr("192.168.1.1")]):
            ok, reason = fetch_readings._is_public_host("router.local")
            assert ok is False
            assert "private" in reason.lower()

    def test_cloud_metadata_blocked(self):
        with patch("socket.getaddrinfo", return_value=[self._mock_addr("169.254.169.254")]):
            ok, reason = fetch_readings._is_public_host("169.254.169.254")
            assert ok is False
            assert "link-local" in reason.lower()

    def test_public_host_allowed(self):
        with patch("socket.getaddrinfo", return_value=[self._mock_addr("93.184.216.34")]):
            ok, reason = fetch_readings._is_public_host("example.com")
            assert ok is True
            assert reason == ""

    def test_fetch_url_rejects_private_host(self):
        with patch("socket.getaddrinfo", return_value=[self._mock_addr("127.0.0.1")]):
            body, ctype, err, _ = fetch_readings.fetch_url("http://127.0.0.1/secret", 5)
            assert body is None
            assert "refused" in err.lower()

    def test_redirect_to_private_host_rejected(self):
        handler = fetch_readings._SafeRedirectHandler()
        req = MagicMock()
        fp = MagicMock()
        headers = {}
        with patch("socket.getaddrinfo", return_value=[self._mock_addr("10.0.0.1")]):
            with pytest.raises(urllib.error.HTTPError) as exc_info:
                handler.redirect_request(req, fp, 302, "Found", headers,
                                         "http://10.0.0.1/internal")
            assert "private" in str(exc_info.value).lower()


class TestBoundedDownloads:
    def _mock_response(self, body: bytes, content_length: int | None = None):
        resp = MagicMock()
        resp.headers = {}
        if content_length is not None:
            resp.headers["Content-Length"] = str(content_length)
        resp.read = MagicMock(side_effect=[body[i:i+16] for i in range(0, len(body), 16)] + [b""])
        return resp

    def test_content_length_over_limit_aborts(self):
        resp = self._mock_response(b"x", content_length=50)
        with patch.object(fetch_readings._OPENER, "open", return_value=resp):
            resp.__enter__ = MagicMock(return_value=resp)
            resp.__exit__ = MagicMock(return_value=False)
            body, ctype, err, reason = fetch_readings.fetch_url(
                "http://example.com/huge", 5, max_size=32)
            assert body is None
            assert reason == "size_limit"
            assert "32" in err

    def test_streaming_body_over_limit_aborts(self):
        resp = self._mock_response(b"x" * 100, content_length=None)
        resp.__enter__ = MagicMock(return_value=resp)
        resp.__exit__ = MagicMock(return_value=False)
        with patch.object(fetch_readings._OPENER, "open", return_value=resp):
            body, ctype, err, reason = fetch_readings.fetch_url(
                "http://example.com/huge", 5, max_size=32)
            assert body is None
            assert reason == "size_limit"

    def test_small_body_fits(self):
        resp = self._mock_response(b"hello world", content_length=11)
        resp.__enter__ = MagicMock(return_value=resp)
        resp.__exit__ = MagicMock(return_value=False)
        with patch.object(fetch_readings._OPENER, "open", return_value=resp):
            body, ctype, err, reason = fetch_readings.fetch_url(
                "http://example.com/small", 5, max_size=100)
            assert body == b"hello world"
            assert err == ""
            assert reason is None


class TestBalancedParenthesisUrls:
    def test_balanced_parentheses_preserved(self):
        raw = "https://en.wikipedia.org/wiki/Clausewitz_(surname)"
        assert fetch_readings._trim_url(raw) == raw

    def test_unbalanced_trailing_paren_removed(self):
        # URL is the last thing in a parenthetical sentence.
        assert fetch_readings._trim_url("https://example.com/page)") == "https://example.com/page"

    def test_trailing_comma_removed(self):
        assert fetch_readings._trim_url("https://example.com/page,") == "https://example.com/page"


class TestAtomicWrites:
    def test_atomic_write_text_creates_target(self, tmp_path: Path):
        target = tmp_path / "out.txt"
        fetch_readings._atomic_write_text(target, "hello")
        assert target.read_text(encoding="utf-8") == "hello"
        assert not (tmp_path / "out.txt.tmp").exists()

    def test_atomic_write_text_no_partial_on_failure(self, tmp_path: Path):
        target = tmp_path / "sub" / "out.txt"
        # Directory does not exist -> write fails, temp should be cleaned.
        with pytest.raises(Exception):
            fetch_readings._atomic_write_text(target, "hello")
        assert not target.exists()


class TestCharsetDecoding:
    def test_honours_content_type_charset(self):
        body = "Café naïve".encode("iso-8859-1")
        text = fetch_readings._decode_body(body, "text/html; charset=iso-8859-1")
        assert "Café" in text
        assert "naïve" in text

    def test_falls_back_to_utf8(self):
        body = "hello world".encode("utf-8")
        text = fetch_readings._decode_body(body, "text/html")
        assert text == "hello world"


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
