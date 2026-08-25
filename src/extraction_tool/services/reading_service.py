"""Reading acquisition service layer.

Bridges DataAccess operations to URL fetching and reading acquisition.
"""

from __future__ import annotations

import re
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from extraction_tool.contracts.readings import (
    ManualCaptureEntry,
    PlannedReading,
    ReadingOccurrence,
    ReadingPlan,
    ReadingRequest,
    ReadingResult,
)
from extraction_tool.extraction.normalization import sanitize
from extraction_tool.repositories.filesystem import FilesystemRepository
from extraction_tool.repositories.http import HttpReadingRepository

_GATE_PHRASES = (
    "sign in to continue", "subscribe to continue", "create a free account",
    "log in to your account", "institutional login", "purchase this article",
    "access through your institution", "you have reached your article limit",
    "please enable javascript", "verify you are a human",
    "checking your browser", "access denied", "subscription required",
)
_LOGIN_FORM_RE = re.compile(
    r"<form[^>]*>(.*?)</form>",
    re.IGNORECASE | re.DOTALL,
)
_LOGIN_FORM_MARKERS = ("login", "log in", "signin", "sign in", "auth",
                       "password", "passwort", "contraseña")
_TECHNICAL_FAILURE_CLASSES = frozenset({
    "dns_failure", "network_failure", "http_failure", "size_limit",
    "browser_failure",
})


@dataclass
class _AcquireState:
    """Mutable, locally-scoped accumulator for an acquisition run."""

    fetched: list[str] = field(default_factory=list)
    downloaded_pdfs: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    manual: list[ManualCaptureEntry] = field(default_factory=list)
    fetched_count: int = 0
    downloaded_pdfs_count: int = 0
    skipped_count: int = 0
    manual_count: int = 0
    videos_count: int = 0
    unexpected_errors: int = 0


def trim_url(url: str) -> str:
    """Trim trailing punctuation that is not part of a balanced parenthesis."""
    url = url.rstrip(".,;")
    while url.endswith(")") and url.count("(") < url.count(")"):
        url = url[:-1]
    return url


def decode_body(raw: bytes, content_type: str = "") -> str:
    """Decode bytes using the Content-Type charset, falling back to UTF-8."""
    charset = None
    if content_type:
        parts = [p.strip() for p in content_type.split(";")]
        for part in parts[1:]:
            if part.lower().startswith("charset="):
                charset = part.split("=", 1)[1].strip('"\'')
                break
    if charset:
        try:
            return raw.decode(charset, errors="replace")
        except (LookupError, UnicodeError):
            pass
    try:
        return raw.decode("utf-8", errors="replace")
    except Exception:
        return str(raw)


def html_to_text_builtin(raw_html: str) -> str:
    """Crude but dependency-free HTML text extraction."""
    _STRIP_BLOCKS = re.compile(
        r"<(script|style|noscript|svg|form|nav|header|footer|aside)\b.*?</\1>",
        re.IGNORECASE | re.DOTALL)
    _BLOCK_END = re.compile(
        r"</(p|div|section|article|h[1-6]|li|tr|blockquote)\s*>",
        re.IGNORECASE)
    _BR = re.compile(r"<br\s*/?>", re.IGNORECASE)
    _TAG = re.compile(r"<[^>]+>")
    _MULTI_NL = re.compile(r"\n{3,}")

    text = _STRIP_BLOCKS.sub(" ", raw_html)
    text = _BR.sub("\n", text)
    text = _BLOCK_END.sub("\n\n", text)
    text = _TAG.sub(" ", text)
    import html as html_mod
    text = html_mod.unescape(text)
    text = "\n".join(re.sub(r"[ \t\xa0]+", " ", ln).strip()
                     for ln in text.splitlines())
    return _MULTI_NL.sub("\n\n", text).strip()


def has_login_form(html: str) -> bool:
    """Return True if the HTML contains a form that looks like a login form."""
    low_html = html.lower()
    for form in _LOGIN_FORM_RE.finditer(low_html):
        block = form.group(0)
        if any(marker in block for marker in _LOGIN_FORM_MARKERS):
            return True
    return False


def login_form_dominates(html: str) -> bool:
    """Return True if a login form makes up most of the body."""
    low_html = html.lower()
    body_match = re.search(r"<body[^>]*>(.*?)</body>", low_html, re.DOTALL)
    body = body_match.group(1) if body_match else low_html
    if not body:
        return False
    form_len = 0
    for form in _LOGIN_FORM_RE.finditer(low_html):
        if any(marker in form.group(0) for marker in _LOGIN_FORM_MARKERS):
            form_len += len(form.group(0))
            break
    return form_len > 0 and form_len / len(body) > 0.4


def looks_gated(text: str, word_count: int, min_words: int = 120) -> str:
    """Return a reason string if this looks like a gate/error page."""
    low = text[:4000].lower()
    for phrase in _GATE_PHRASES:
        if phrase in low:
            return f"page contains '{phrase}'"
    if word_count < min_words:
        return f"only {word_count} words retrieved (likely a stub or gate)"
    return ""


def page_looks_gated(html: str, text: str, word_count: int,
                     min_words: int = 120) -> str:
    """Check both raw HTML structure and extracted text for gate signals."""
    if has_login_form(html):
        if word_count < min_words:
            return "page contains a login form and extracted text is short"
        if login_form_dominates(html):
            return "page contains a login form that dominates the page"
    return looks_gated(text, word_count, min_words=min_words)


def pages_from_occurrences(occurrences: list[ReadingOccurrence]) -> list[int]:
    """Return sorted source pages with None values omitted."""
    pages = [o.source_page for o in occurrences if o.source_page is not None]
    return sorted(set(pages))


def first_page(occurrences: list[ReadingOccurrence]) -> int | None:
    """Return the first source page, if any."""
    for occurrence in occurrences:
        if occurrence.source_page is not None:
            return occurrence.source_page
    return None


def first_label(occurrences: list[ReadingOccurrence]) -> str | None:
    """Return the first deterministic label, if any."""
    for occurrence in occurrences:
        if occurrence.label:
            return occurrence.label
    return None


def classify_gate_reason(reason: str) -> str:
    """Map a gate-detection reason to a failure class."""
    low = reason.lower()
    if "login form" in low or "institutional" in low:
        return "institutional_login"
    if "only" in low and "words" in low:
        return "insufficient_content"
    return "bot_protection"


def _unique_page_url_entries(
    entries: list[tuple[int | None, str]]
) -> list[tuple[int | None, str]]:
    """Remove duplicate (page, url) pairs from PDF sources while preserving order.

    The same URL may appear as both a link annotation and visible text on one
    PDF page; that should count as a single occurrence. Appearances on different
    pages are preserved. Plain URL files (page is None) are left as-is.
    """
    seen: set[tuple[int, str]] = set()
    unique: list[tuple[int | None, str]] = []
    for page, url in entries:
        if page is not None:
            key = (page, url.rstrip("/"))
            if key in seen:
                continue
            seen.add(key)
        unique.append((page, url))
    return unique


class ReadingService:
    """Service for reading acquisition operations."""

    _TEXT_URL_RE = re.compile(r"https?://[^\s<>\"'\]}]+", re.IGNORECASE)

    # Static helpers live at module scope to keep the class small; these
    # aliases preserve the existing public attribute interface.
    _trim_url = staticmethod(trim_url)
    _decode_body = staticmethod(decode_body)
    _html_to_text_builtin = staticmethod(html_to_text_builtin)
    _page_looks_gated = staticmethod(page_looks_gated)
    _looks_gated = staticmethod(looks_gated)
    _pages_from_occurrences = staticmethod(pages_from_occurrences)
    _first_page = staticmethod(first_page)
    _first_label = staticmethod(first_label)
    _classify_gate_reason = staticmethod(classify_gate_reason)

    def __init__(
        self,
        repo: HttpReadingRepository,
        fs_repo: FilesystemRepository | None = None,
    ) -> None:
        """Initialize with an HTTP reading repository and optional filesystem repo."""
        self._repo = repo
        self._fs_repo = fs_repo or FilesystemRepository()

    def plan_readings(self, request: ReadingRequest) -> ReadingPlan:
        """Inspect the syllabus and return a non-network reading plan.

        The plan discovers URLs, deduplicates by normalised URL, and preserves
        every syllabus occurrence. No DNS, HTTP, Selenium, or filesystem-output
        calls are made.
        """
        entries = self._collect_entries(request)
        return self._build_plan(entries, request)

    def acquire_readings(self, request: ReadingRequest) -> ReadingResult:
        """Acquire readings from a syllabus PDF or URLs file."""
        if request.source and not Path(request.source).is_file():
            return ReadingResult(
                success=False,
                errors=[f"Source PDF not found: {request.source}"],
            )
        if request.urls_file and not Path(request.urls_file).is_file():
            return ReadingResult(
                success=False,
                errors=[f"URLs file not found: {request.urls_file}"],
            )

        plan = self.plan_readings(request)
        if plan.total_occurrences == 0:
            return ReadingResult(
                success=False,
                errors=[
                    "No reading URLs were discovered. "
                    "If the source is a PDF, check that it contains link "
                    "annotations or selectable text rather than a flat image."
                ],
                discovered=0,
            )

        out_dir = Path(request.out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        pdf_dir = out_dir / "downloaded_pdfs"

        state = _AcquireState()
        for planned in plan.entries:
            self._process_entry(request, planned, out_dir, pdf_dir, state)

        _write_manual_capture(self._fs_repo, request, out_dir, state.manual)

        return ReadingResult(
            success=True,
            fetched=state.fetched,
            manual_capture=state.manual,
            downloaded_pdfs=state.downloaded_pdfs,
            skipped=state.skipped,
            errors=[],
            discovered=plan.total_unique,
            fetched_count=state.fetched_count,
            downloaded_pdfs_count=state.downloaded_pdfs_count,
            skipped_count=state.skipped_count,
            manual_count=state.manual_count,
            videos_count=state.videos_count,
            unexpected_errors=state.unexpected_errors,
        )

    def _process_entry(
        self,
        request: ReadingRequest,
        planned: PlannedReading,
        out_dir: Path,
        pdf_dir: Path,
        state: _AcquireState,
    ) -> None:
        """Route one planned reading to its category handler."""
        try:
            if planned.category == "video":
                self._process_video_entry(request, planned, out_dir, state)
            elif planned.category == "gated":
                self._process_gated_entry(planned, state)
            elif planned.category == "pdf":
                self._process_pdf_entry(request, planned, pdf_dir, state)
            else:
                self._process_article_entry(request, planned, out_dir, pdf_dir, state)
        except Exception as e:  # noqa: BLE001 - one bad URL must not kill the run
            state.unexpected_errors += 1
            print(
                f"  [error] unexpected failure for {planned.url}: "
                f"{type(e).__name__}: {e}",
                file=sys.stderr,
            )

    def _process_video_entry(
        self,
        request: ReadingRequest,
        planned: PlannedReading,
        out_dir: Path,
        state: _AcquireState,
    ) -> None:
        """Record a video link."""
        state.videos_count += 1
        if not request.include_videos:
            return
        target = out_dir / (self._repo.safe_filename(planned.url) + ".txt")
        if target.exists() and not request.overwrite:
            state.skipped.append(str(target))
            state.skipped_count += 1
            return
        text = f"VIDEO: {planned.url}\n\n"
        text += "Videos are skipped by default; watch directly.\n"
        self._fs_repo.atomic_write_text(target, text)
        state.fetched.append(str(target))
        state.fetched_count += 1

    def _process_gated_entry(
        self, planned: PlannedReading, state: _AcquireState
    ) -> None:
        """Record a gated URL for manual capture."""
        state.manual.append(
            ManualCaptureEntry(
                url=planned.url,
                category="gated",
                failure_class="institutional_login",
                reason="subscription or institutional login required",
                pages=pages_from_occurrences(planned.occurrences),
                label=first_label(planned.occurrences),
            )
        )
        state.manual_count += 1

    def _process_pdf_entry(
        self,
        request: ReadingRequest,
        planned: PlannedReading,
        pdf_dir: Path,
        state: _AcquireState,
    ) -> None:
        """Download a direct PDF, recording failures as manual captures."""
        pdf_dir.mkdir(exist_ok=True)
        target = pdf_dir / (self._repo.safe_filename(planned.url) + ".pdf")
        if target.exists() and not request.overwrite:
            state.skipped.append(str(target))
            state.skipped_count += 1
            return

        body, _ctype, err, size_reason = self._repo.fetch_url(
            planned.url, request.timeout, max_size=100 * 1024 * 1024
        )
        time.sleep(request.delay)
        if body is None:
            state.manual.append(
                ManualCaptureEntry(
                    url=planned.url,
                    category="pdf",
                    failure_class=self._repo.classify_failure(err, size_reason),
                    reason=err or "fetch failed",
                    pages=pages_from_occurrences(planned.occurrences),
                    label=first_label(planned.occurrences),
                )
            )
            state.manual_count += 1
            return
        if not body.startswith(b"%PDF"):
            state.manual.append(
                ManualCaptureEntry(
                    url=planned.url,
                    category="pdf",
                    failure_class="incorrect_content_type",
                    reason="server did not return a PDF "
                           "(likely a login or landing page)",
                    pages=pages_from_occurrences(planned.occurrences),
                    label=first_label(planned.occurrences),
                )
            )
            state.manual_count += 1
            return
        self._fs_repo.atomic_write_bytes(target, body)
        state.fetched.append(str(target))
        state.downloaded_pdfs.append(str(target))
        state.downloaded_pdfs_count += 1

    def _process_article_entry(
        self,
        request: ReadingRequest,
        planned: PlannedReading,
        out_dir: Path,
        pdf_dir: Path,
        state: _AcquireState,
    ) -> None:
        """Fetch and extract an article."""
        stem = self._repo.safe_filename(planned.url)
        target = out_dir / (stem + ".txt")
        pdf_target = pdf_dir / (stem + ".pdf")
        if not request.overwrite and (target.exists() or pdf_target.exists()):
            state.skipped.append(str(target))
            state.skipped_count += 1
            return

        source = _fetch_article_source(
            self._repo, self._extract_article, self._fs_repo, request,
            planned.url, pdf_dir, state, planned.occurrences,
        )
        if source is None:
            return

        text, title, extractor, raw_html = source
        text, _ = sanitize(text)
        title, _ = sanitize(title)
        words = len(text.split())
        reason = page_looks_gated(raw_html, text, words, min_words=request.min_words)
        if reason:
            state.manual.append(
                ManualCaptureEntry(
                    url=planned.url,
                    category="article",
                    failure_class=classify_gate_reason(reason),
                    reason=reason,
                    pages=pages_from_occurrences(planned.occurrences),
                    label=title or first_label(planned.occurrences),
                )
            )
            state.manual_count += 1
            return

        header = format_reading_header(
            planned.url, title, extractor, words, first_page(planned.occurrences)
        )
        self._fs_repo.atomic_write_text(target, header + text)
        state.fetched.append(str(target))
        state.fetched_count += 1

    def _collect_entries(
        self, request: ReadingRequest
    ) -> list[tuple[int | None, str]]:
        """Gather (page, url) tuples from the syllabus PDF and URLs file."""
        entries: list[tuple[int | None, str]] = []
        if request.source:
            entries += self._urls_from_pdf(request.source)
        if request.urls_file:
            for line in Path(request.urls_file).read_text(
                encoding="utf-8-sig"
            ).splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if not line.lower().startswith(("http://", "https://")):
                    continue
                entries.append((None, line))
        return _unique_page_url_entries(entries)

    def _build_plan(
        self,
        entries: list[tuple[int | None, str]],
        request: ReadingRequest,
    ) -> ReadingPlan:
        """Deduplicate entries by normalised URL while preserving occurrences."""
        grouped: dict[str, list[tuple[int | None, str]]] = {}
        for page, url in entries:
            key = url.rstrip("/")
            grouped.setdefault(key, []).append((page, url))

        category_counts: dict[str, int] = {
            "article": 0, "pdf": 0, "video": 0, "gated": 0
        }
        plan_entries: list[PlannedReading] = []
        for key in grouped:
            occurrences_raw = grouped[key]
            canonical_url = occurrences_raw[0][1]
            category = self._repo.categorise(canonical_url, request.gated_hosts)
            category_counts[category] += 1
            occurrences = [
                ReadingOccurrence(source_page=page)
                for page, _ in occurrences_raw
            ]
            plan_entries.append(
                PlannedReading(url=canonical_url, category=category,
                               occurrences=occurrences)
            )

        return ReadingPlan(
            category_counts=category_counts,
            total_unique=len(plan_entries),
            total_occurrences=len(entries),
            entries=plan_entries,
        )

    def _urls_from_pdf(self, pdf_path: str) -> list[tuple[int, str]]:
        """Extract URLs from a PDF's link annotations and visible text."""
        try:
            import pypdf
        except ImportError:
            print("Error: pypdf is required to read PDFs.", file=sys.stderr)
            sys.exit(1)

        found: list[tuple[int, str]] = []
        try:
            reader = pypdf.PdfReader(pdf_path)
        except Exception as e:
            print(f"Error: could not open {pdf_path}: {type(e).__name__}: {e}",
                  file=sys.stderr)
            sys.exit(1)

        for page_num, page in enumerate(reader.pages, start=1):
            self._extract_annotation_urls(page, page_num, found)
            self._extract_text_urls(page, page_num, found)
        return found

    def _extract_annotation_urls(
        self, page: Any, page_num: int, found: list[tuple[int, str]]
    ) -> None:
        """Append annotation URLs from one PDF page."""
        try:
            for annot in page.get("/Annots") or []:
                try:
                    obj = annot.get_object()
                    action = obj.get("/A")
                    if action and "/URI" in action:
                        uri = str(action["/URI"]).strip()
                        if uri.lower().startswith(("http://", "https://")):
                            found.append((page_num, uri))
                except Exception as e:
                    print(f"  [debug] skipped malformed annotation on page "
                          f"{page_num}: {type(e).__name__}: {e}",
                          file=sys.stderr)
        except Exception as e:
            print(f"  [debug] could not read link annotations on page "
                  f"{page_num}: {type(e).__name__}: {e}", file=sys.stderr)

    def _extract_text_urls(
        self, page: Any, page_num: int, found: list[tuple[int, str]]
    ) -> None:
        """Append visible-text URLs from one PDF page."""
        try:
            text = page.extract_text() or ""
            for m in ReadingService._TEXT_URL_RE.finditer(text):
                found.append((page_num, trim_url(m.group(0))))
        except Exception as e:
            print(f"  [debug] could not extract text from page "
                  f"{page_num}: {type(e).__name__}: {e}", file=sys.stderr)

    @staticmethod
    def _extract_article(raw: bytes) -> tuple[str, str, str]:
        """Return (text, title, extractor_name)."""
        import html as html_mod
        raw_html = raw.decode("utf-8", errors="replace")
        title = ""
        m = re.search(r"<title[^>]*>(.*?)</title>", raw_html,
                      re.IGNORECASE | re.DOTALL)
        if m:
            title = html_mod.unescape(re.sub(r"\s+", " ", m.group(1))).strip()
        text, extractor = _extract_article_text(raw)
        return text, title, extractor


def _format_manual_entry(entry: ManualCaptureEntry) -> list[str]:
    """Render one manual-capture entry as lines."""
    pages = ", ".join(str(p) for p in entry.pages) if entry.pages else "unknown"
    lines = [
        f"  URL:           {entry.url}",
        f"  Category:      {entry.category}",
        f"  Failure class: {entry.failure_class}",
        f"  Reason:        {entry.reason}",
        f"  Pages:         {pages}",
    ]
    if entry.label:
        lines.append(f"  Label:         {entry.label}")
    return lines


def _write_manual_capture(
    fs_repo: FilesystemRepository,
    request: ReadingRequest,
    out_dir: Path,
    manual: list[ManualCaptureEntry],
) -> None:
    """Write the MANUAL_CAPTURE.txt report, separating retryable failures."""
    manual_path = out_dir / "MANUAL_CAPTURE.txt"
    capture = [e for e in manual
               if e.failure_class not in _TECHNICAL_FAILURE_CLASSES]
    technical = [e for e in manual
                 if e.failure_class in _TECHNICAL_FAILURE_CLASSES]

    lines = [
        "=" * 72,
        "READINGS THAT COULD NOT BE FETCHED AUTOMATICALLY",
        "=" * 72,
        "",
    ]
    if capture:
        lines += [
            "MANUAL CAPTURE REQUIRED",
            "",
            "These need to be saved by hand. Open each in a browser where you",
            "are signed in (institutional proxy, subscription, etc.), then use",
            "Ctrl+P -> 'Save as PDF' and put the file with your other PDFs so",
            "preprocess_pdf.py can process it.",
            "",
        ]
        for entry in capture:
            lines.extend(_format_manual_entry(entry))
            lines.append("")
    if technical:
        lines += [
            "TECHNICAL FAILURES — RETRY",
            "",
            "These URLs could not be reached because of a network, DNS, HTTP,",
            "size-limit, or browser-rendering problem. They are not paywalled;",
            "check connectivity and rerun before treating them as manual captures.",
            "",
        ]
        for entry in technical:
            lines.extend(_format_manual_entry(entry))
            lines.append("")
    if not manual:
        lines.append("  (none - everything fetched successfully)")
        lines.append("")
    fs_repo.atomic_write_text(manual_path, "\n".join(lines) + "\n")


def format_reading_header(url: str, title: str, extractor: str, words: int,
                          source_page: int | None) -> str:
    """Build the saved-reading banner written above fetched article text."""
    lines = [
        "=" * 72,
        f"FETCHED READING - {title or urlparse(url).netloc}",
        "=" * 72,
        "",
        "SOURCE",
        f"  URL:        {url}",
        f"  Retrieved:  {time.strftime('%Y-%m-%d %H:%M')}",
    ]
    if source_page:
        lines.append(f"  Listed on:  page {source_page} of the syllabus PDF")
    lines += [
        f"  Extractor:  {extractor}",
        f"  Words:      {words:,}",
        "",
    ]
    if extractor == "built-in stripper":
        lines += [
            "WARNING",
            "  Extracted with the built-in fallback stripper, which is crude",
            "  and may include navigation or sidebar text. Install trafilatura",
            "  (pip install trafilatura) and refetch for much cleaner output.",
            "",
        ]
    lines += [
        "NOTES",
        "  This is a saved copy of a web page, not an authoritative edition.",
        "  Web articles have no stable page numbers - cite the URL and the",
        "  retrieval date above, per your style guide.",
        "  Verify any direct quotation against the live page before citing.",
        "",
        "  This tool does not summarise, paraphrase, or generate text and",
        "  contains no AI model. Text below is the source page's own words.",
        "=" * 72,
        "",
    ]
    return "\n".join(lines)


def _extract_article_text(raw: bytes) -> tuple[str, str]:
    """Three-tier article extraction chain.

    Order: trafilatura (primary) -> beautifulsoup4 (middle) -> built-in
    stripper (last resort). Each tier is only accepted when it yields more
    than 50 words. Returns (text, extractor_name). The page <title> is handled
    separately by ReadingService._extract_article.
    """
    raw_html = raw.decode("utf-8", errors="replace")
    try:
        import trafilatura  # type: ignore[import-not-found]
        extracted = trafilatura.extract(
            raw_html, include_comments=False, include_tables=True,
            favor_precision=True)
        if extracted and len(extracted.split()) > 50:
            return extracted.strip(), "trafilatura"
    except ImportError:
        pass
    except Exception as e:
        print(f"  [debug] trafilatura extraction failed, trying "
              f"beautifulsoup4: {type(e).__name__}: {e}", file=sys.stderr)

    try:
        from extraction_tool.extraction.html import extract_with_bs4
        extracted = extract_with_bs4(raw_html)
        if extracted and len(extracted.split()) > 50:
            return extracted, "beautifulsoup4"
    except ImportError:
        pass
    except Exception as e:
        print(f"  [debug] beautifulsoup4 extraction failed, using "
              f"built-in stripper: {type(e).__name__}: {e}", file=sys.stderr)

    return html_to_text_builtin(raw_html), "built-in stripper"


def _record_manual_capture(
    state: _AcquireState,
    url: str,
    failure_class: str,
    reason: str,
    pages: list[int],
    label: str | None,
) -> None:
    """Record a manual-capture entry and increment the counter."""
    state.manual.append(
        ManualCaptureEntry(
            url=url,
            category="article",
            failure_class=failure_class,
            reason=reason,
            pages=pages,
            label=label,
        )
    )
    state.manual_count += 1


def _save_article_pdf_or_skip(
    body: bytes,
    repo: HttpReadingRepository,
    fs_repo: FilesystemRepository,
    request: ReadingRequest,
    url: str,
    pdf_dir: Path,
    state: _AcquireState,
) -> None:
    """Save an article URL that returned a PDF, or skip if it exists."""
    pdf_dir.mkdir(exist_ok=True)
    pdf_target = pdf_dir / (repo.safe_filename(url) + ".pdf")
    if not pdf_target.exists() or request.overwrite:
        fs_repo.atomic_write_bytes(pdf_target, body)
        state.fetched.append(str(pdf_target))
        state.downloaded_pdfs.append(str(pdf_target))
        state.downloaded_pdfs_count += 1
    else:
        state.skipped.append(str(pdf_target))
        state.skipped_count += 1


def _fetch_article_source(
    repo: HttpReadingRepository,
    extract_article: Callable[[bytes], tuple[str, str, str]],
    fs_repo: FilesystemRepository,
    request: ReadingRequest,
    url: str,
    pdf_dir: Path,
    state: _AcquireState,
    occurrences: list[ReadingOccurrence],
) -> tuple[str, str, str, str] | None:
    """Fetch article source and return (text, title, extractor, raw_html).

    Returns None if the URL was handled (saved as PDF or recorded as manual).
    """
    pages = pages_from_occurrences(occurrences)
    label = first_label(occurrences)
    if request.use_browser:
        return _fetch_article_via_browser(
            repo, extract_article, request, url, pages, label, state)
    return _fetch_article_via_http(
        repo, extract_article, fs_repo, request, url, pdf_dir, pages, label, state)


def _fetch_article_via_browser(
    repo: HttpReadingRepository,
    extract_article: Callable[[bytes], tuple[str, str, str]],
    request: ReadingRequest,
    url: str,
    pages: list[int],
    label: str | None,
    state: _AcquireState,
) -> tuple[str, str, str, str] | None:
    """Render an article in a headless browser and return extracted source."""
    html, err = repo.fetch_rendered_html(url, request.browser_timeout)
    time.sleep(request.delay)
    if not html:
        _record_manual_capture(
            state, url, repo.classify_failure(err or ""),
            err or "browser returned no content", pages, label,
        )
        return None
    text, title, extractor = extract_article(html.encode("utf-8"))
    return text, title, extractor, html


def _fetch_article_via_http(
    repo: HttpReadingRepository,
    extract_article: Callable[[bytes], tuple[str, str, str]],
    fs_repo: FilesystemRepository,
    request: ReadingRequest,
    url: str,
    pdf_dir: Path,
    pages: list[int],
    label: str | None,
    state: _AcquireState,
) -> tuple[str, str, str, str] | None:
    """Fetch an article over HTTP and return extracted source."""
    body, _ctype, err, size_reason = repo.fetch_url(
        url, request.timeout, max_size=10 * 1024 * 1024
    )
    time.sleep(request.delay)
    if body is None:
        _record_manual_capture(
            state, url, repo.classify_failure(err, size_reason),
            err or "fetch failed", pages, label,
        )
        return None
    if body.startswith(b"%PDF"):
        _save_article_pdf_or_skip(body, repo, fs_repo, request, url, pdf_dir, state)
        return None
    text, title, extractor = extract_article(body)
    return text, title, extractor, body.decode("utf-8", errors="replace")
