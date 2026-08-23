"""CLI adapter for the Extraction Toolkit.

Preserves the existing CLI behavior from preprocess_pdf.py and fetch_readings.py.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from extraction_tool.contracts.extraction import ExtractionRequest
from extraction_tool.contracts.readings import ReadingRequest
from extraction_tool.extraction.ocr import check_dependencies
from extraction_tool.repositories.filesystem import FilesystemRepository
from extraction_tool.repositories.http import HttpReadingRepository
from extraction_tool.services.extraction_service import ExtractionService
from extraction_tool.services.reading_service import ReadingService


def _version() -> str:
    version_file = Path(__file__).resolve().parents[3] / "VERSION"
    if version_file.is_file():
        return version_file.read_text(encoding="utf-8").strip()
    return "unknown"


def _build_preprocess_parser() -> argparse.ArgumentParser:
    """Return the ArgumentParser for preprocess_pdf."""
    ap = argparse.ArgumentParser(
        description="Extract complete searchable text from PDFs.")
    ap.add_argument(
        "inputs", nargs="*", help="PDF files, directories, or glob patterns"
    )
    ap.add_argument("-o", "--out", help="Explicit output path (single PDF only)")
    ap.add_argument("--out-dir", help="Write all outputs into this directory")
    ap.add_argument("--overwrite", action="store_true",
                    help="Reprocess even if matching .txt already exists")
    ap.add_argument("--force-ocr", action="store_true",
                    help="OCR every page regardless of extracted text")
    ap.add_argument("--ocr-lang", default="eng",
                    help="tesseract language code (default: eng)")
    ap.add_argument("--ocr-dpi", type=int, default=300,
                    help="Render resolution for OCR (default: 300)")
    ap.add_argument("--ocr-threshold", type=int, default=8,
                    help="Pages with fewer than N extracted words are OCR'd")
    ap.add_argument("--no-deskew", action="store_true",
                    help="Skip deskew before OCR")
    ap.add_argument("--check", action="store_true",
                    help="Report which tools are installed and exit")
    ap.add_argument("--dry-run", action="store_true",
                    help="Preview what would be done without writing files")
    ap.add_argument("--no-header", action="store_true",
                    help="Omit quality header from output")
    ap.add_argument("--version", action="version",
                    version=f"%(prog)s {_version()}")
    return ap


def _resolve_out_path(args: argparse.Namespace, pdf_path: Path) -> Path:
    """Where the .txt for this PDF goes: explicit -o, else --out-dir/<stem>.txt,
    else <stem>.txt beside the source PDF."""
    if args.out:
        return Path(args.out)
    if args.out_dir:
        return Path(args.out_dir) / (pdf_path.stem + ".txt")
    return pdf_path.with_name(pdf_path.stem + ".txt")


def _report_extraction(out_path: Path, result) -> None:
    """Print a one-line quality summary for a written file."""
    flags = []
    if not result.page_count_ok:
        flags.append(f"PAGE COUNT {result.pages_found}/{result.pages_expected}")
    if not result.sequence_ok:
        flags.append("PAGE ORDER BROKEN")
    suffix = ("  [!] " + "; ".join(flags)) if flags else ""
    print(f"  wrote {out_path}  ({result.words:,} words, "
          f"{result.pages_found} pages, {result.ocr_pct:.1f}% OCR){suffix}",
          file=sys.stderr)


def _extract_one(service: ExtractionService, args: argparse.Namespace,
                 pdf_path: Path) -> bool:
    """Extract a single PDF to its resolved output path. Returns False on error
    (a clean skip of an already-extracted file counts as success)."""
    out_path = _resolve_out_path(args, pdf_path)

    # The tool only ever reads source PDFs — never write over one.
    if out_path.resolve() == pdf_path.resolve():
        print(f"  [error] refusing to write output over the source PDF: "
              f"{pdf_path}", file=sys.stderr)
        return False

    # Idempotent re-runs: skip already-extracted files unless --overwrite.
    if out_path.exists() and not args.overwrite:
        print(f"  skipping — {out_path.name} already exists "
              f"(use --overwrite to redo)", file=sys.stderr)
        return True

    out_path.parent.mkdir(parents=True, exist_ok=True)
    request = ExtractionRequest(
        pdf_path=str(pdf_path),
        ocr_lang=args.ocr_lang,
        ocr_dpi=args.ocr_dpi,
        ocr_threshold=args.ocr_threshold,
        force_ocr=args.force_ocr,
        no_deskew=args.no_deskew,
    )
    result = service.extract_pdf(request, out_path=out_path,
                                 no_header=args.no_header)
    if not result.success:
        print(f"Error processing {pdf_path}: {result.errors[0]}", file=sys.stderr)
        return False

    _report_extraction(out_path, result)
    return True


def preprocess_pdf_main() -> None:
    """CLI entry point for PDF preprocessing."""
    ap = _build_preprocess_parser()
    args = ap.parse_args()

    if args.check:
        check_dependencies(args.ocr_lang)
        return

    if not args.inputs:
        ap.error("give at least one PDF, directory, or glob pattern")

    repo = FilesystemRepository(out_dir=args.out_dir)
    service = ExtractionService(repo)
    pdf_files = repo.resolve_pdf_inputs(args.inputs)

    if args.dry_run:
        print("=== DRY RUN - no files written ===", file=sys.stderr)
        for pdf in pdf_files:
            print(f"  would process: {pdf}", file=sys.stderr)
        return

    if args.out and len(pdf_files) > 1:
        ap.error("-o/--out writes a single file; use --out-dir for multiple PDFs")

    # Process every PDF (list comp forces full evaluation, no short-circuit).
    if not all([_extract_one(service, args, pdf) for pdf in pdf_files]):
        sys.exit(1)


def _build_fetch_readings_parser() -> argparse.ArgumentParser:
    """Return the ArgumentParser for fetch_readings."""
    ap = argparse.ArgumentParser(
        description="Extract reading URLs from a syllabus PDF and fetch them as text.")
    ap.add_argument("pdf", nargs="?", help="syllabus / reading-list PDF")
    ap.add_argument("--urls", help="text file of URLs, one per line")
    ap.add_argument("--out-dir", default="readings")
    ap.add_argument("--list-only", action="store_true",
                    help="print the categorised URL list and exit")
    ap.add_argument("--include-videos", action="store_true",
                    help="write placeholder notes for video links")
    ap.add_argument("--delay", type=float, default=1.5,
                    help="seconds between requests (default 1.5)")
    ap.add_argument("--timeout", type=int, default=30)
    ap.add_argument("--overwrite", action="store_true")
    ap.add_argument("--min-words", type=int, default=120)
    ap.add_argument("--use-browser", action="store_true",
                    help="render article pages in a headless browser (Selenium)")
    ap.add_argument("--browser-timeout", type=int, default=30,
                    help="headless browser render timeout in seconds")
    ap.add_argument("--dry-run", action="store_true",
                   help="categorise URLs and report what would be fetched")
    ap.add_argument("--version", action="version",
                    version=f"%(prog)s {_version()}")
    return ap


def fetch_readings_main() -> None:
    """CLI entry point for reading acquisition."""
    ap = _build_fetch_readings_parser()
    args = ap.parse_args()

    if not args.pdf and not args.urls:
        ap.error("give a syllabus PDF, or --urls FILE (or both)")

    repo = HttpReadingRepository()
    service = ReadingService(repo)

    if args.dry_run:
        print("\n=== DRY RUN - no network requests, no files written ===",
              file=sys.stderr)
        print(f"Output directory would be: {args.out_dir}", file=sys.stderr)
        return

    request = ReadingRequest(
        source=args.pdf,
        urls_file=args.urls,
        out_dir=args.out_dir,
        include_videos=args.include_videos,
        delay=args.delay,
        timeout=args.timeout,
        overwrite=args.overwrite,
        min_words=args.min_words,
        use_browser=args.use_browser,
        browser_timeout=args.browser_timeout,
    )
    result = service.acquire_readings(request)
    if not result.success:
        print(f"Error: {result.errors}", file=sys.stderr)
        sys.exit(1)
