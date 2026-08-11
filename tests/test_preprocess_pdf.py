"""Unit and integration tests for preprocess_pdf.py."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

import preprocess_pdf


class TestSanitize:
    def test_strips_zero_width_and_bidi_controls(self):
        text = (
            "visible\u200b\u200c\u200d\u2060\u00ad\u034f\u180e"
            "\u200e\u200f\u202e\u2066hidden\u2069"
        )
        cleaned, removed = preprocess_pdf.sanitize(text)
        assert cleaned == "visiblehidden"
        assert removed == 12

    def test_leaves_normal_text_and_punctuation(self):
        text = "Hello, world! Café — 123."
        cleaned, removed = preprocess_pdf.sanitize(text)
        assert cleaned == text
        assert removed == 0


class TestNumeralHelpers:
    @pytest.mark.parametrize(
        "value,expected",
        [
            ("I", 1),
            ("III", 3),
            ("IV", 4),
            ("IX", 9),
            ("XLII", 42),
            ("CLXXXVII", 187),      # function caps valid Roman numerals at <= 200
            ("MCMLXXXVII", None),   # too large to be a book/chapter numeral here
            ("NOT_ROMAN", None),
        ],
    )
    def test_roman_to_int(self, value, expected):
        assert preprocess_pdf._roman_to_int(value) == expected

    @pytest.mark.parametrize(
        "value,expected",
        [
            ("1", 1),
            ("42", 42),
            ("IV", 4),
            ("Four", 4),
            ("FIRST", 1),
            ("eleven", 11),
            ("foo", None),
        ],
    )
    def test_numeral_value(self, value, expected):
        assert preprocess_pdf._numeral_value(value) == expected


class TestCleanAndMarkPages:
    def test_inserts_page_markers(self):
        pages = [
            "Top line one\nBody line one",
            "Top line two\nBody line two",
            "Top line three\nBody line three",
        ]
        raw = "\f".join(pages)
        out = preprocess_pdf.clean_and_mark_pages(raw)
        assert "--- PAGE 1 ---" in out
        assert "--- PAGE 2 ---" in out
        assert "--- PAGE 3 ---" in out
        assert "Body line one" in out

    def test_tags_ocr_pages(self):
        pages = [
            "Top line one\nBody line one",
            "",  # empty page 2 (will be OCR'd and therefore marked blank too)
            "Top line three\nBody line three",
        ]
        raw = "\f".join(pages)
        out = preprocess_pdf.clean_and_mark_pages(raw, ocr_pages={2, 3})
        assert "--- PAGE 1 ---" in out
        assert "--- PAGE 2 [OCR] [BLANK] ---" in out
        assert "--- PAGE 3 [OCR] ---" in out

    def test_strips_repeated_running_headers(self):
        pages = []
        for i in range(1, 7):
            pages.append(f"Running Header\nContent line {i}\nFooter")
        raw = "\f".join(pages)
        out = preprocess_pdf.clean_and_mark_pages(raw)
        # The header repeated on every page should be gone from body text.
        marker_count = out.count("Running Header")
        # It appears once as a page marker label, not six times.
        assert marker_count <= 1

    def test_strips_bare_page_numbers(self):
        # Use a single page so stripping happens via _PDF_PAGE_NUM, not boiler.
        raw = "Body text\n42"
        out = preprocess_pdf.clean_and_mark_pages(raw)
        assert "42" not in out
        assert "Body text" in out

    def test_strips_bare_page_numbers_as_boiler(self):
        # With enough pages, identical last-line page numbers become boiler.
        pages = [f"Real content {i}\n42" for i in range(6)]
        raw = "\f".join(pages)
        out = preprocess_pdf.clean_and_mark_pages(raw)
        assert out.count("42") == 0
        # Distinct body lines should survive because they are not repeated headers.
        assert "Real content 0" in out

    def test_rejoins_hyphen_wrapped_words(self):
        raw = "well-\nknown fact"
        out = preprocess_pdf.clean_and_mark_pages(raw)
        assert "wellknown" in out


class TestFindHeadings:
    def test_detects_book_and_chapter_headings(self):
        text = (
            "--- PAGE 1 ---\nBOOK ONE\n--- PAGE 2 ---\n"
            "CHAPTER 1\nThe start\n--- PAGE 10 ---\n"
            "CHAPTER 2\nThe continuation"
        )
        hits = preprocess_pdf.find_headings(text)
        levels = [level for _, level, _ in hits]
        assert "book" in levels
        assert "chapter" in levels

    def test_demotes_endnotes_dividers(self):
        # After a Notes title in the last third, "Chapter 1" is probably a divider.
        lines = ["--- PAGE 1 ---"] + ["Body text."] * 30
        lines += ["--- PAGE 31 ---", "NOTES"]
        lines += ["--- PAGE 32 ---", "Chapter 1", "note one"]
        hits = preprocess_pdf.find_headings("\n".join(lines))
        assert any(level == "chapter?" for _, level, _ in hits)

    def test_rejects_wrapped_cross_references(self):
        text = "--- PAGE 1 ---\nChapter 5, the 1991 Gulf War, was..."
        hits = preprocess_pdf.find_headings(text)
        assert not any("Chapter 5" in h for _, _, h in hits)


class TestQualityReport:
    def test_flags_missing_pages(self):
        text = "--- PAGE 1 ---\nfoo\n--- PAGE 3 ---\nbar"
        report = preprocess_pdf.compute_quality_report(text, [], expected_pages=3)
        assert report["pages_found"] == 2
        assert report["page_count_ok"] is False
        assert report["sequence_ok"] is False

    def test_ok_when_complete(self):
        text = "--- PAGE 1 ---\nfoo\n--- PAGE 2 ---\nbar\n--- PAGE 3 ---\nbaz"
        report = preprocess_pdf.compute_quality_report(text, [], expected_pages=3)
        assert report["page_count_ok"] is True
        assert report["sequence_ok"] is True
        assert report["words"] == 3


class TestMetadataHelpers:
    def test_title_rejected_as_junk(self, junk_metadata_pdf: Path):
        meta = preprocess_pdf.extract_pdf_metadata(str(junk_metadata_pdf))
        assert meta["title"] == ""
        assert "imageItem" in meta["title_rejected"]

    def test_build_filename_falls_back_gracefully(self):
        meta = {"title": "", "author": "", "year": "", "title_rejected": ""}
        stem, why = preprocess_pdf.build_metadata_filename(meta, "original")
        assert stem == "original"
        assert "no title" in why.lower()


class TestAuthorNameNormalization:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("Clausewitz, Carl", "Carl Clausewitz"),
            ("Clausewitz, Carl von", "Carl von Clausewitz"),
            # Surname + suffix + first name: the reported edge case.
            ("Meyer, Jr., David", "David Meyer, Jr."),
            ("Smith, Sr., John", "John Smith, Sr."),
            # Multi-author strings must not be reordered.
            ("Clausewitz, Carl and Jomini, Antoine", "Clausewitz, Carl and Jomini, Antoine"),
            # Ambiguous or already-first-name forms fall through unchanged.
            ("Carl Clausewitz", "Carl Clausewitz"),
            ("Smith, John, Jr.", "Smith, John, Jr."),
            # Too many commas to interpret safely.
            ("A, B, C, D", "A, B, C, D"),
        ],
    )
    def test_normalize_author_for_filename(self, raw, expected):
        assert preprocess_pdf._normalize_author_for_filename(raw) == expected

    def test_build_filename_with_surname_first(self):
        meta = {"title": "On War", "author": "Clausewitz, Carl", "year": "1832", "title_rejected": ""}
        stem, why = preprocess_pdf.build_metadata_filename(meta, "on-war")
        assert stem == "Carl Clausewitz - On War (1832)"
        assert why == ""

    def test_build_filename_with_suffix_edge_case(self):
        meta = {"title": "Strategy", "author": "Meyer, Jr., David", "year": "", "title_rejected": ""}
        stem, why = preprocess_pdf.build_metadata_filename(meta, "strategy")
        assert stem == "David Meyer, Jr. - Strategy"
        assert why == ""


class TestOcrLangValidation:
    def test_installed_tesseract_langs_parses_output(self):
        stdout = "List of available languages (3):\neng\nlat\ndeu\n"
        with patch.object(
            subprocess, "run", return_value=__import__("subprocess").CompletedProcess(
                args=["tesseract", "--list-langs"], returncode=0, stdout=stdout, stderr=""
            )
        ):
            assert preprocess_pdf._installed_tesseract_langs() == ["eng", "lat", "deu"]

    def test_installed_tesseract_langs_returns_empty_on_failure(self):
        with patch.object(
            subprocess, "run", return_value=__import__("subprocess").CompletedProcess(
                args=["tesseract", "--list-langs"], returncode=1, stdout="", stderr="error"
            )
        ):
            assert preprocess_pdf._installed_tesseract_langs() == []

    def test_validate_ocr_lang_accepts_installed_single(self):
        with patch.object(
            preprocess_pdf, "_installed_tesseract_langs", return_value=["eng", "lat"]
        ):
            ok, missing = preprocess_pdf._validate_ocr_lang("eng")
            assert ok is True
            assert missing == []

    def test_validate_ocr_lang_accepts_installed_combined(self):
        with patch.object(
            preprocess_pdf, "_installed_tesseract_langs", return_value=["eng", "lat"]
        ):
            ok, missing = preprocess_pdf._validate_ocr_lang("eng+lat")
            assert ok is True
            assert missing == []

    def test_validate_ocr_lang_reports_missing_pack(self):
        with patch.object(
            preprocess_pdf, "_installed_tesseract_langs", return_value=["eng"]
        ):
            ok, missing = preprocess_pdf._validate_ocr_lang("deu")
            assert ok is False
            assert missing == ["deu"]

    def test_validate_ocr_lang_reports_partial_missing_in_combo(self):
        with patch.object(
            preprocess_pdf, "_installed_tesseract_langs", return_value=["eng"]
        ):
            ok, missing = preprocess_pdf._validate_ocr_lang("eng+lat")
            assert ok is False
            assert missing == ["lat"]

    def test_validate_ocr_lang_treats_empty_as_valid(self):
        with patch.object(
            preprocess_pdf, "_installed_tesseract_langs", return_value=["eng"]
        ):
            ok, missing = preprocess_pdf._validate_ocr_lang("")
            assert ok is True
            assert missing == []


class TestEndToEndExtraction:
    def test_simple_pdf_extraction(
        self, simple_pdf: Path, tmp_path: Path, has_pdftotext: bool
    ):
        if not has_pdftotext:
            pytest.skip("pdftotext not available")

        out_path = tmp_path / "simple.txt"
        args = self._dummy_args()
        result = preprocess_pdf.process_one_pdf(simple_pdf, out_path, args)

        assert result["pages"] == 5
        assert result["page_count_ok"] is True
        assert result["sequence_ok"] is True
        assert out_path.exists()
        text = out_path.read_text(encoding="utf-8")
        assert "--- PAGE 1 ---" in text
        assert "--- PAGE 5 ---" in text

    def test_header_footer_stripping(
        self, header_footer_pdf: Path, tmp_path: Path, has_pdftotext: bool
    ):
        if not has_pdftotext:
            pytest.skip("pdftotext not available")

        out_path = tmp_path / "headers.txt"
        args = self._dummy_args()
        result = preprocess_pdf.process_one_pdf(header_footer_pdf, out_path, args)

        assert result["pages"] == 6
        text = out_path.read_text(encoding="utf-8")
        # Repeated running header should be removed; bare page numbers too.
        assert text.count("Sample Treatise") <= 1
        body_numbers = sum(line.strip().isdigit() for line in text.splitlines())
        assert body_numbers == 0

    def test_embedded_outline_index(
        self, outline_pdf: Path, tmp_path: Path, has_pdftotext: bool
    ):
        if not has_pdftotext:
            pytest.skip("pdftotext not available")

        out_path = tmp_path / "outline.txt"
        args = self._dummy_args()
        preprocess_pdf.process_one_pdf(outline_pdf, out_path, args)

        index_path = out_path.with_suffix(out_path.suffix + ".index")
        assert index_path.exists()
        index_text = index_path.read_text(encoding="utf-8")
        assert "embedded outline" in index_text.lower()
        assert "BOOK ONE" in index_text
        assert "Chapter 1: The Beginning" in index_text

    @pytest.mark.skipif(
        shutil.which("tesseract") is None,
        reason="tesseract not available",
    )
    def test_image_only_pdf_gets_ocr_tag(
        self, image_only_pdf: Path, tmp_path: Path, has_pdftotext: bool
    ):
        if not has_pdftotext:
            pytest.skip("pdftotext not available")

        out_path = tmp_path / "ocr.txt"
        args = self._dummy_args()
        result = preprocess_pdf.process_one_pdf(image_only_pdf, out_path, args)

        assert result["pages"] == 1
        assert result["ocr_pages"] == 1
        assert result["ocr_pct"] == 100.0

        text = out_path.read_text(encoding="utf-8")
        assert "--- PAGE 1 [OCR] ---" in text
        # Tesseract may read "This page is an image" with minor differences,
        # so check for distinctive words rather than an exact string.
        assert "page" in text.lower()
        assert "image" in text.lower() or "mage" in text.lower()

    @staticmethod
    def _dummy_args():
        """Return a minimal argparse Namespace for process_one_pdf."""
        import argparse

        return argparse.Namespace(
            ocr_lang="eng",
            ocr_dpi=300,
            ocr_threshold=8,
            force_ocr=False,
            no_deskew=False,
            no_header=False,
        )


class TestCli:
    def test_version_flag(self):
        import subprocess
        result = subprocess.run(
            ["python", "preprocess_pdf.py", "--version"],
            capture_output=True, text=True, cwd=Path(__file__).parent.parent,
        )
        assert result.returncode == 0, result.stderr
        assert "1.1.0" in result.stdout


class TestAtomicWrites:
    def test_atomic_write_text_creates_file(self, tmp_path: Path):
        target = tmp_path / "out.txt"
        preprocess_pdf._atomic_write_text(target, "complete output")
        assert target.read_text(encoding="utf-8") == "complete output"
        assert not (tmp_path / "out.txt.tmp").exists()

    def test_atomic_write_cleans_temp_on_failure(self, tmp_path: Path):
        target = tmp_path / "missing_dir" / "out.txt"
        with pytest.raises(Exception):
            preprocess_pdf._atomic_write_text(target, "data")
        assert not target.exists()
        assert not (tmp_path / "out.txt.tmp").exists()


class TestDryRun:
    def test_dry_run_writes_no_files(self, simple_pdf: Path, tmp_path: Path):
        out_dir = tmp_path / "extracted"
        # Use subprocess to exercise the CLI argument parsing.
        import subprocess
        result = subprocess.run(
            ["python", "preprocess_pdf.py", str(simple_pdf),
             "--out-dir", str(out_dir), "--dry-run"],
            capture_output=True, text=True, cwd=Path(__file__).parent.parent,
        )
        assert result.returncode == 0, result.stderr
        assert "DRY RUN" in result.stderr
        # No .txt or .index files should be created.
        assert not any(out_dir.glob("*"))
