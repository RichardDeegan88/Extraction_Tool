"""Regression tests for the reading-acquisition workflow."""

from __future__ import annotations

import socket
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

import fetch_readings
from extraction_tool.repositories.http import HttpReadingRepository


def _article_html(words: int = 150) -> bytes:
    """Return a simple HTML body with enough words to pass the gate check."""
    text = " ".join([f"word{i}" for i in range(words)])
    return (
        f"<html><head><title>Article Title</title></head>"
        f"<body><article>{text}</article></body></html>"
    ).encode()


def _urls_file(tmp_path: Path, urls: list[str]) -> Path:
    """Write a newline-separated URL list."""
    path = tmp_path / "urls.txt"
    path.write_text("\n".join(urls) + "\n", encoding="utf-8")
    return path


def _url_pdf(tmp_path: Path, pages: list[str]) -> Path:
    """Create a PDF whose pages contain the given visible text strings."""
    path = tmp_path / "syllabus.pdf"
    c = canvas.Canvas(str(path), pagesize=letter)
    for text in pages:
        c.drawString(72, 720, text)
        c.showPage()
    c.save()
    return path


class TestPlanning:
    def test_plan_readings_from_urls_file(self, tmp_path: Path):
        urls = [
            "https://example.com/article",
            "https://example.com/paper.pdf",
            "https://www.jstor.org/stable/123",
            "https://youtube.com/watch?v=1",
            "https://example.com/article",  # duplicate
        ]
        urls_path = _urls_file(tmp_path, urls)
        request = fetch_readings.ReadingRequest(
            urls_file=str(urls_path), out_dir=str(tmp_path / "readings"), delay=0
        )
        plan = fetch_readings.plan_readings(request)

        assert plan.total_unique == 4
        assert plan.total_occurrences == 5
        assert plan.category_counts == {
            "article": 1, "pdf": 1, "gated": 1, "video": 1,
        }
        article = next(e for e in plan.entries if e.category == "article")
        assert len(article.occurrences) == 2

    def test_plan_readings_from_pdf_preserves_pages(self, tmp_path: Path):
        pdf = _url_pdf(tmp_path, [
            "Read https://example.com/page1 for context.",
            "See https://example.com/page2 (required).",
            "Optional: https://example.com/page1",
        ])
        request = fetch_readings.ReadingRequest(
            source=str(pdf), out_dir=str(tmp_path / "readings"), delay=0
        )
        plan = fetch_readings.plan_readings(request)

        assert plan.total_unique == 2
        assert plan.total_occurrences == 3
        entry1 = next(e for e in plan.entries
                      if e.url == "https://example.com/page1")
        pages = [o.source_page for o in entry1.occurrences]
        assert sorted(pages) == [1, 3]

    def test_plan_readings_makes_no_network_calls(self, tmp_path: Path):
        urls_path = _urls_file(tmp_path, ["https://example.com/article"])
        request = fetch_readings.ReadingRequest(
            urls_file=str(urls_path), out_dir=str(tmp_path / "readings"), delay=0
        )
        with patch.object(HttpReadingRepository, "fetch_url") as mock_fetch:
            fetch_readings.plan_readings(request)
        mock_fetch.assert_not_called()
        assert not (tmp_path / "readings").exists()


class TestDryRunAndListOnly:
    def test_dry_run_discovers_and_categorises(self, tmp_path: Path):
        urls_path = _urls_file(tmp_path, [
            "https://example.com/article",
            "https://example.com/paper.pdf",
            "https://www.jstor.org/stable/123",
            "https://youtube.com/watch?v=1",
        ])
        out_dir = tmp_path / "readings"
        result = subprocess.run(
            [sys.executable, "fetch_readings.py", "--urls", str(urls_path),
             "--out-dir", str(out_dir), "--dry-run"],
            capture_output=True, text=True, cwd=Path(__file__).parent.parent,
        )
        assert result.returncode == 0, result.stderr
        assert "DRY RUN" in result.stderr
        assert "Discovered: 4 unique URLs" in result.stderr
        assert not any(out_dir.glob("*"))

    def test_list_only_prints_categorised_urls(self, tmp_path: Path):
        urls_path = _urls_file(tmp_path, [
            "https://example.com/article",
            "https://example.com/paper.pdf",
            "https://www.jstor.org/stable/123",
        ])
        result = subprocess.run(
            [sys.executable, "fetch_readings.py", "--urls", str(urls_path),
             "--list-only"],
            capture_output=True, text=True, cwd=Path(__file__).parent.parent,
        )
        assert result.returncode == 0, result.stderr
        assert "ARTICLE" in result.stdout
        assert "PDF" in result.stdout
        assert "GATED" in result.stdout
        assert "Total: 3 unique URLs" in result.stdout

    def test_list_only_zero_urls_fails(self, tmp_path: Path):
        urls_path = _urls_file(tmp_path, [])
        result = subprocess.run(
            [sys.executable, "fetch_readings.py", "--urls", str(urls_path),
             "--list-only"],
            capture_output=True, text=True, cwd=Path(__file__).parent.parent,
        )
        assert result.returncode != 0
        assert "No reading URLs were discovered" in result.stderr


class TestAcquisitionReporting:
    def _public_addr(self):
        return [(socket.AF_INET, None, None, None, ("93.184.216.34", 0))]

    def test_repeated_url_downloaded_once_retains_pages(self, tmp_path: Path):
        pdf = _url_pdf(tmp_path, [
            "Page 1 text.",
            "Read https://example.com/repeated today.",
            "Page 3 text.",
            "Again https://example.com/repeated for next week.",
        ])
        out_dir = tmp_path / "readings"
        request = fetch_readings.ReadingRequest(
            source=str(pdf), out_dir=str(out_dir), delay=0, timeout=5
        )
        body = _article_html(150)
        with (
            patch("socket.getaddrinfo", return_value=self._public_addr()),
            patch.object(HttpReadingRepository, "fetch_url",
                         return_value=(body, "text/html", "", None)),
            patch.object(HttpReadingRepository, "_is_public_host",
                         return_value=(True, "")),
        ):
            result = fetch_readings.acquire_readings(request)

        assert result.success is True
        assert result.discovered == 1
        assert result.fetched_count == 1
        assert result.skipped_count == 0
        article_files = [
            p for p in out_dir.glob("*.txt")
            if p.name != "MANUAL_CAPTURE.txt"
        ]
        assert len(article_files) == 1
        content = article_files[0].read_text(encoding="utf-8")
        assert "Listed on:  page 2" in content

    def test_zero_urls_returns_failure(self, tmp_path: Path):
        urls_path = _urls_file(tmp_path, [])
        request = fetch_readings.ReadingRequest(
            urls_file=str(urls_path), out_dir=str(tmp_path / "readings"), delay=0
        )
        result = fetch_readings.acquire_readings(request)
        assert result.success is False
        assert "No reading URLs were discovered" in result.errors[0]

    def test_partial_acquisition_returns_exit_code_0(self, tmp_path: Path):
        urls_path = _urls_file(tmp_path, [
            "https://example.com/article",
            "https://www.jstor.org/stable/123",
        ])
        out_dir = tmp_path / "readings"
        body = _article_html(150)
        argv = [
            "fetch_readings.py", "--urls", str(urls_path),
            "--out-dir", str(out_dir),
        ]
        with (
            patch("sys.argv", argv),
            patch("socket.getaddrinfo", return_value=self._public_addr()),
            patch.object(HttpReadingRepository, "fetch_url",
                         return_value=(body, "text/html", "", None)),
            pytest.raises(SystemExit) as exc_info,
        ):
            fetch_readings.fetch_readings_main()
        assert exc_info.value.code == 0

    def test_manual_capture_contains_pages_and_class(self, tmp_path: Path):
        pdf = _url_pdf(tmp_path, [
            "Intro.",
            "Read https://example.com/gated-article (required).",
            "More context.",
            "Again https://example.com/gated-article (optional).",
        ])
        request = fetch_readings.ReadingRequest(
            source=str(pdf), out_dir=str(tmp_path / "readings"), delay=0, timeout=5
        )
        with (
            patch("socket.getaddrinfo", return_value=self._public_addr()),
            patch.object(HttpReadingRepository, "fetch_url",
                         return_value=(None, "", "could not resolve host", None)),
        ):
            result = fetch_readings.acquire_readings(request)

        assert result.success is True
        assert result.manual_count == 1
        entry = result.manual_capture[0]
        assert entry.pages == [2, 4]
        assert entry.failure_class == "dns_failure"
        manual_path = Path(request.out_dir) / "MANUAL_CAPTURE.txt"
        content = manual_path.read_text(encoding="utf-8")
        assert "Pages:         2, 4" in content
        assert "Failure class: dns_failure" in content

    def test_videos_not_counted_as_failures(self, tmp_path: Path):
        urls_path = _urls_file(tmp_path, ["https://youtube.com/watch?v=1"])
        request = fetch_readings.ReadingRequest(
            urls_file=str(urls_path), out_dir=str(tmp_path / "readings"), delay=0
        )
        result = fetch_readings.acquire_readings(request)
        assert result.success is True
        assert result.videos_count == 1
        assert result.manual_count == 0
        assert result.unexpected_errors == 0

    def test_manual_capture_lists_skipped_videos(self, tmp_path: Path):
        urls_path = _urls_file(tmp_path, ["https://youtube.com/watch?v=1"])
        request = fetch_readings.ReadingRequest(
            urls_file=str(urls_path), out_dir=str(tmp_path / "readings"), delay=0
        )
        fetch_readings.acquire_readings(request)
        manual_path = Path(request.out_dir) / "MANUAL_CAPTURE.txt"
        content = manual_path.read_text(encoding="utf-8")
        assert "VIDEOS (watch directly; not text)" in content
        assert "https://youtube.com/watch?v=1" in content

    def test_existing_files_counted_as_skipped(self, tmp_path: Path):
        urls_path = _urls_file(tmp_path, ["https://example.com/article"])
        out_dir = tmp_path / "readings"
        out_dir.mkdir()
        stem = HttpReadingRepository().safe_filename("https://example.com/article")
        (out_dir / (stem + ".txt")).write_text("existing", encoding="utf-8")
        request = fetch_readings.ReadingRequest(
            urls_file=str(urls_path), out_dir=str(out_dir), delay=0
        )
        result = fetch_readings.acquire_readings(request)
        assert result.skipped_count == 1
        assert result.fetched_count == 0


class TestGatedHostConfiguration:
    def test_extra_gated_host_via_request(self):
        repo = HttpReadingRepository()
        assert repo.categorise("https://myproxy.edu/item") == "article"
        assert repo.categorise(
            "https://myproxy.edu/item", extra_gated=["myproxy.edu"]
        ) == "gated"

    def test_primo_host_is_gated(self):
        assert fetch_readings.categorise(
            "https://aul.primo.exlibrisgroup.com/discovery/fulldisplay"
        ) == "gated"

    def test_cli_gated_host_flag(self, tmp_path: Path):
        urls_path = _urls_file(tmp_path, ["https://myproxy.edu/item"])
        result = subprocess.run(
            [sys.executable, "fetch_readings.py", "--urls", str(urls_path),
             "--list-only", "--gated-host", "myproxy.edu"],
            capture_output=True, text=True, cwd=Path(__file__).parent.parent,
        )
        assert result.returncode == 0, result.stderr
        assert "GATED" in result.stdout

    def test_empty_gated_host_is_rejected(self):
        with pytest.raises(ValueError, match="non-empty"):
            fetch_readings.ReadingRequest(
                urls_file="urls.txt", gated_hosts=[""]
            )

    def test_whitespace_gated_host_is_rejected(self):
        with pytest.raises(ValueError, match="non-empty"):
            fetch_readings.ReadingRequest(
                urls_file="urls.txt", gated_hosts=["   "]
            )
