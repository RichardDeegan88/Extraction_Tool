"""CLI adapter for the Extraction Toolkit.

Preserves the existing CLI behavior from preprocess_pdf.py and fetch_readings.py.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from extraction_tool.contracts.extraction import ExtractionRequest, ExtractionResult
from extraction_tool.contracts.readings import (
    ReadingOccurrence,
    ReadingPlan,
    ReadingRequest,
    ReadingResult,
)
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


def _resolve_out_path(args: argparse.Namespace, pdf_path: Path,
                      used_stems: dict[str, int]) -> Path:
    """Where the .txt for this PDF goes: explicit -o, else --out-dir/<stem>.txt,
    else <stem>.txt beside the source PDF.

    When --out-dir flattens a recursive tree, two PDFs in different subfolders
    can share a stem; disambiguate with a counter so neither is silently
    skipped as "already exists".
    """
    if args.out:
        return Path(args.out)
    stem = pdf_path.stem
    if args.out_dir:
        seen = used_stems.get(stem.lower(), 0)
        used_stems[stem.lower()] = seen + 1
        if seen:
            stem = f"{stem} ({seen + 1})"
        return Path(args.out_dir) / (stem + ".txt")
    return pdf_path.with_name(stem + ".txt")


def _report_extraction(out_path: Path, result: ExtractionResult) -> None:
    """Print a one-line quality summary for a written file."""
    flags = []
    if not result.page_count_ok:
        flags.append(f"PAGE COUNT {result.pages_found}/{result.pages_expected}")
    if not result.sequence_ok:
        flags.append("PAGE ORDER BROKEN")
    if result.ocr_pct > 50:
        flags.append(f"{result.ocr_pct:.0f}% OCR")
    if result.words_per_page < 50 and result.pages_found > 5:
        flags.append("LOW TEXT DENSITY")
    suffix = ("  [!] " + "; ".join(flags)) if flags else ""
    print(f"  wrote {out_path}  ({result.words:,} words, "
          f"{result.pages_found} pages, {result.ocr_pct:.1f}% OCR){suffix}",
          file=sys.stderr)


def _extract_one(service: ExtractionService, args: argparse.Namespace,
                 pdf_path: Path, out_path: Path) -> bool:
    """Extract a single PDF to out_path. Returns False on any failure (write
    error, extraction error, or empty output); a clean skip of an already-
    extracted file counts as success. One bad PDF never aborts the batch.
    """
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
    try:
        result = service.extract_pdf(request, out_path=out_path,
                                     no_header=args.no_header)
    except Exception as e:  # noqa: BLE001 - one bad PDF must not kill the batch
        print(f"  [error] failed on {pdf_path.name}: "
              f"{type(e).__name__}: {e}", file=sys.stderr)
        return False

    if not result.success:
        print(f"Error processing {pdf_path}: {result.errors[0]}", file=sys.stderr)
        return False

    _report_extraction(out_path, result)

    # A PDF that "succeeded" with zero words is corrupt/image-only — signal
    # failure via exit code so launchers/CI never treat it as a good extraction.
    if result.words == 0:
        print(f"  [warning] {out_path.name} has no extractable text — the "
              f"source PDF may be corrupt or unreadable", file=sys.stderr)
        return False

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

    repo = FilesystemRepository()
    service = ExtractionService(repo)
    pdf_files = repo.resolve_pdf_inputs(args.inputs)

    if args.out and len(pdf_files) > 1:
        ap.error("-o/--out writes a single file; use --out-dir for multiple PDFs")

    if args.dry_run:
        print("=== DRY RUN - no files written ===", file=sys.stderr)
        for pdf in pdf_files:
            print(f"  would process: {pdf}", file=sys.stderr)
        return

    # Process every PDF; one failure sets a non-zero exit without aborting rest.
    used_stems: dict[str, int] = {}
    ok = True
    for pdf_path in pdf_files:
        out_path = _resolve_out_path(args, pdf_path, used_stems)
        if not _extract_one(service, args, pdf_path, out_path):
            ok = False
    if not ok:
        sys.exit(1)


def _build_fetch_readings_parser() -> argparse.ArgumentParser:
    """Return the ArgumentParser for fetch_readings."""
    ap = argparse.ArgumentParser(
        description=(
            "Extract reading URLs from a syllabus PDF and fetch them as text. "
            "Exit codes: 0 = all non-video readings acquired or already present; "
            "2 = partial (manual captures or recoverable failures); "
            "1 = fatal, no URLs discovered, or all attempted retrievals failed."
        )
    )
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
    ap.add_argument("--gated-host", action="append", default=[],
                    help="additional host substring treated as gated "
                         "(can be given multiple times)")
    ap.add_argument("--version", action="version",
                    version=f"%(prog)s {_version()}")
    return ap


def _reading_request_from_args(args: argparse.Namespace) -> ReadingRequest:
    """Build a ReadingRequest from parsed CLI arguments."""
    return ReadingRequest(
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
        gated_hosts=list(args.gated_host),
    )


def _print_list_only(plan: ReadingPlan) -> int:
    """Print the categorised URL list and return an exit code."""
    if plan.total_occurrences == 0:
        print("No reading URLs were discovered.", file=sys.stderr)
        return 1

    print("\nCATEGORISED READING URLs")
    print("=" * 72)
    for category in ("article", "pdf", "gated", "video"):
        entries = [e for e in plan.entries if e.category == category]
        if not entries:
            continue
        print(f"\n{category.upper()} ({len(entries)} unique)")
        for entry in entries:
            pages = _pages_str(entry.occurrences)
            print(f"  {entry.url}")
            print(f"      pages: {pages}")
    print("\n" + "=" * 72)
    print(f"Total: {plan.total_unique} unique URLs across "
          f"{plan.total_occurrences} occurrences")
    print(f"  articles: {plan.category_counts['article']}, "
          f"PDFs: {plan.category_counts['pdf']}, "
          f"gated: {plan.category_counts['gated']}, "
          f"videos: {plan.category_counts['video']}")
    return 0


def _print_dry_run(plan: ReadingPlan, out_dir: str) -> None:
    """Print what a normal run would do without making network calls."""
    print("\nDRY RUN - no network requests or files written", file=sys.stderr)
    print(f"\nDiscovered: {plan.total_unique} unique URLs across "
          f"{plan.total_occurrences} occurrences", file=sys.stderr)
    print(f"PDFs:      {plan.category_counts['pdf']}", file=sys.stderr)
    print(f"Articles:  {plan.category_counts['article']}", file=sys.stderr)
    print(f"Gated:     {plan.category_counts['gated']}", file=sys.stderr)
    print(f"Videos:    {plan.category_counts['video']}", file=sys.stderr)
    print(f"\nOutput directory would be: {out_dir}", file=sys.stderr)

    for category in ("pdf", "gated", "article", "video"):
        for entry in plan.entries:
            if entry.category != category:
                continue
            pages = _pages_str(entry.occurrences)
            label = {
                "pdf": "PDF",
                "gated": "GATED",
                "article": "ARTICLE",
                "video": "VIDEO",
            }[category]
            print(f"\n{label} — syllabus page {pages}", file=sys.stderr)
            print(f"{entry.url}", file=sys.stderr)


def _pages_str(occurrences: list[ReadingOccurrence]) -> str:
    """Return a comma-separated page string, or 'unknown'."""
    pages = sorted(
        {o.source_page for o in occurrences if o.source_page is not None}
    )
    return ", ".join(str(p) for p in pages) if pages else "unknown"


def _print_summary(result: ReadingResult, out_dir: str) -> None:
    """Print a concise acquisition summary to stderr."""
    print("\nACQUISITION SUMMARY", file=sys.stderr)
    print(f"  unique URLs discovered:  {result.discovered}", file=sys.stderr)
    print(f"  readings fetched:        {result.fetched_count}", file=sys.stderr)
    print(f"  PDFs downloaded:         {result.downloaded_pdfs_count}",
          file=sys.stderr)
    print(f"  existing files skipped:  {result.skipped_count}", file=sys.stderr)
    print(f"  manual captures:         {result.manual_count}", file=sys.stderr)
    print(f"  videos skipped:          {result.videos_count}", file=sys.stderr)
    print(f"  unexpected errors:       {result.unexpected_errors}",
          file=sys.stderr)
    if result.manual_count:
        print(f"\n  MANUAL_CAPTURE.txt:      {Path(out_dir) / 'MANUAL_CAPTURE.txt'}",
              file=sys.stderr)
    if result.fetched_count == 0 and result.downloaded_pdfs_count == 0:
        print("\n  [warning] No readings were acquired.", file=sys.stderr)


def _exit_code_for_result(result: ReadingResult) -> int:
    """Return the documented exit code for a finished acquisition run."""
    if not result.success:
        return 1
    if result.manual_count or result.unexpected_errors:
        return 2
    return 0


def fetch_readings_main() -> None:
    """CLI entry point for reading acquisition."""
    ap = _build_fetch_readings_parser()
    args = ap.parse_args()

    if not args.pdf and not args.urls:
        ap.error("give a syllabus PDF, or --urls FILE (or both)")

    repo = HttpReadingRepository()
    fs_repo = FilesystemRepository()
    service = ReadingService(repo, fs_repo)
    request = _reading_request_from_args(args)

    if args.list_only:
        plan = service.plan_readings(request)
        sys.exit(_print_list_only(plan))

    if args.dry_run:
        plan = service.plan_readings(request)
        if plan.total_occurrences == 0:
            print("No reading URLs were discovered.", file=sys.stderr)
            sys.exit(1)
        _print_dry_run(plan, args.out_dir)
        return

    result = service.acquire_readings(request)
    _print_summary(result, args.out_dir)
    sys.exit(_exit_code_for_result(result))
