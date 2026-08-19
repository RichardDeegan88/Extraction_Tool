"""Reading acquisition service layer.

Bridges DataAccess operations to URL fetching and reading acquisition.
"""

from __future__ import annotations

import re
import sys
import time
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlparse

from extraction_tool.contracts.readings import (
    ReadingRequest,
    ReadingResult,
)
from extraction_tool.extraction.normalization import sanitize
from extraction_tool.repositories.http import HttpReadingRepository


class ReadingService:
    """Service for reading acquisition operations."""

    _TEXT_URL_RE = re.compile(r"https?://[^\s<>\"'\]}]+", re.IGNORECASE)

    def __init__(self, repo: HttpReadingRepository) -> None:
        """Initialize with an HTTP reading repository."""
        self._repo = repo

    def acquire_readings(self, request: ReadingRequest) -> ReadingResult:
        """Acquire readings from a syllabus PDF or URLs file.

        Args:
            request: Reading acquisition parameters.

        Returns:
            ReadingResult with fetched files, manual capture list, and errors.
        """
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

        buckets = self._bucket_entries(self._collect_entries(request))
        out_dir = Path(request.out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        pdf_dir = out_dir / "downloaded_pdfs"

        fetched: list[str] = []
        manual: list[tuple[str, str]] = []
        self._process_pdfs(request, buckets, pdf_dir, fetched, manual)
        self._process_articles(request, buckets, out_dir, pdf_dir, fetched, manual)
        self._append_gated(buckets, manual)
        self._write_manual_capture(request, out_dir, buckets, manual)

        return ReadingResult(
            success=True,
            fetched=fetched,
            manual_capture=manual,
            downloaded_pdfs=(
                [str(p) for p in pdf_dir.glob("*.pdf")]
                if pdf_dir.exists() else []
            ),
            skipped=[],
            errors=[],
        )

    def _collect_entries(self, request: ReadingRequest) -> list[tuple[int | None, str]]:
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
        return entries

    def _bucket_entries(
        self, entries: list[tuple[int | None, str]]
    ) -> dict[str, list[tuple[int | None, str]]]:
        """Deduplicate and categorise entries into article/pdf/video/gated."""
        seen: set[str] = set()
        unique: list[tuple[int | None, str]] = []
        for page, url in entries:
            key = url.rstrip("/")
            if key not in seen:
                seen.add(key)
                unique.append((page, url))

        buckets: dict[str, list[tuple[int | None, str]]] = {
            "article": [], "pdf": [], "video": [], "gated": []}
        for page, url in unique:
            buckets[self._repo.categorise(url)].append((page, url))
        return buckets

    def _process_pdfs(
        self,
        request: ReadingRequest,
        buckets: dict[str, list[tuple[int | None, str]]],
        pdf_dir: Path,
        fetched: list[str],
        manual: list[tuple[str, str]],
    ) -> None:
        """Download each categorised PDF, recording failures as manual captures."""
        for _, url in buckets["pdf"]:
            pdf_dir.mkdir(exist_ok=True)
            target = pdf_dir / (self._repo.safe_filename(url) + ".pdf")
            if target.exists() and not request.overwrite:
                continue
            body, _ctype, err, _ = self._repo.fetch_url(
                url, request.timeout, max_size=100 * 1024 * 1024
            )
            time.sleep(request.delay)
            if body is None:
                manual.append((url, err))
                continue
            if not body.startswith(b"%PDF"):
                manual.append((url, "server did not return a PDF "
                                     "(likely a login or landing page)"))
                continue
            Path(target).write_bytes(body)
            fetched.append(str(target))

    def _process_articles(
        self,
        request: ReadingRequest,
        buckets: dict[str, list[tuple[int | None, str]]],
        out_dir: Path,
        pdf_dir: Path,
        fetched: list[str],
        manual: list[tuple[str, str]],
    ) -> None:
        """Fetch and extract each article, recording gates as manual captures."""
        for page, url in buckets["article"]:
            stem = self._repo.safe_filename(url)
            target = out_dir / (stem + ".txt")
            pdf_target = pdf_dir / (stem + ".pdf")
            if not request.overwrite and (target.exists() or pdf_target.exists()):
                continue
            source = _fetch_article_source(
                self._repo, self._extract_article, request, url, pdf_dir,
                fetched, manual,
            )
            if source is None:
                continue
            text, title, extractor, raw_html = source
            text, _ = sanitize(text)
            title, _ = sanitize(title)
            words = len(text.split())
            reason = self._page_looks_gated(
                raw_html, text, words, min_words=request.min_words
            )
            if reason:
                manual.append((url, reason))
                continue
            header = format_reading_header(url, title, extractor, words, page)
            Path(target).write_text(header + text, encoding="utf-8")
            fetched.append(str(target))

    def _append_gated(
        self,
        buckets: dict[str, list[tuple[int | None, str]]],
        bucket_manual: list[tuple[str, str]],
    ) -> None:
        """Record gated URLs as manual captures."""
        bucket_manual.extend(
            (url, "subscription or institutional login required")
            for _, url in buckets["gated"]
        )

    def _write_manual_capture(
        self,
        request: ReadingRequest,
        out_dir: Path,
        buckets: dict[str, list[tuple[int | None, str]]],
        manual: list[tuple[str, str]],
    ) -> None:
        """Write the MANUAL_CAPTURE.txt report for unfetchable readings."""
        manual_path = out_dir / "MANUAL_CAPTURE.txt"
        lines = [
            "=" * 72,
            "READINGS THAT COULD NOT BE FETCHED AUTOMATICALLY",
            "=" * 72,
            "",
            "These need to be saved by hand. Open each in a browser where you",
            "are signed in (institutional proxy, subscription, etc.), then use",
            "Ctrl+P -> 'Save as PDF' and put the file with your other PDFs so",
            "preprocess_pdf.py can process it.",
            "",
            "Nothing was written for these URLs. A login or error page was NOT",
            "saved as if it were the reading.",
            "",
        ]
        if manual:
            for url, reason in manual:
                lines.append(f"  {url}")
                lines.append(f"      reason: {reason}")
                lines.append("")
        else:
            lines.append("  (none - everything fetched successfully)")
            lines.append("")
        if buckets["video"] and not request.include_videos:
            lines += ["", "VIDEOS (watch directly; not text)", ""]
            lines += [f"  {u}" for _, u in buckets["video"]]
        Path(manual_path).write_text("\n".join(lines) + "\n", encoding="utf-8")

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
                        continue
            except Exception as e:
                print(f"  [debug] could not read link annotations on page "
                      f"{page_num}: {type(e).__name__}: {e}", file=sys.stderr)
            try:
                text = page.extract_text() or ""
                for m in ReadingService._TEXT_URL_RE.finditer(text):
                    found.append((page_num, ReadingService._trim_url(m.group(0))))
            except Exception as e:
                print(f"  [debug] could not extract text from page "
                      f"{page_num}: {type(e).__name__}: {e}", file=sys.stderr)

        seen: set[str] = set()
        unique: list[tuple[int, str]] = []
        for page_num, url in found:
            key = url.rstrip("/")
            if key not in seen:
                seen.add(key)
                unique.append((page_num, url))
        return unique

    @staticmethod
    def _trim_url(url: str) -> str:
        url = url.rstrip(".,;")
        while url.endswith(")") and url.count("(") < url.count(")"):
            url = url[:-1]
        return url

    @staticmethod
    def _decode_body(raw: bytes, content_type: str = "") -> str:
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

    @staticmethod
    def _extract_article(raw: bytes, content_type: str = "") -> tuple[str, str, str]:
        """Return (text, title, extractor_name)."""
        import html as html_mod
        raw_html = raw.decode("utf-8", errors="replace")
        title = ""
        m = re.search(r"<title[^>]*>(.*?)</title>", raw_html, re.IGNORECASE | re.DOTALL)
        if m:
            title = html_mod.unescape(re.sub(r"\s+", " ", m.group(1))).strip()
        text, extractor = _extract_article_text(raw)
        return text, title, extractor

    @staticmethod
    def _html_to_text_builtin(raw_html: str) -> str:
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

    @staticmethod
    def _page_looks_gated(html: str, text: str, word_count: int,
                          min_words: int = 120) -> str:
        """Check both raw HTML structure and extracted text for gate signals."""
        if ReadingService._has_login_form(html):
            if word_count < min_words:
                return "page contains a login form and extracted text is short"
            if ReadingService._login_form_dominates(html):
                return "page contains a login form that dominates the page"
        return ReadingService._looks_gated(text, word_count, min_words=min_words)

    @staticmethod
    def _looks_gated(text: str, word_count: int, min_words: int = 120) -> str:
        """Return a reason string if this looks like a gate/error page."""
        low = text[:4000].lower()
        for phrase in ReadingService._GATE_PHRASES:
            if phrase in low:
                return f"page contains '{phrase}'"
        if word_count < min_words:
            return f"only {word_count} words retrieved (likely a stub or gate)"
        return ""

    @staticmethod
    def _has_login_form(html: str) -> bool:
        low_html = html.lower()
        for form in ReadingService._LOGIN_FORM_RE.finditer(low_html):
            block = form.group(0)
            if any(marker in block for marker in ReadingService._LOGIN_FORM_MARKERS):
                return True
        return False

    @staticmethod
    def _login_form_dominates(html: str) -> bool:
        low_html = html.lower()
        body_match = re.search(r"<body[^>]*>(.*?)</body>", low_html, re.DOTALL)
        body = body_match.group(1) if body_match else low_html
        if not body:
            return False
        form_len = 0
        for form in ReadingService._LOGIN_FORM_RE.finditer(low_html):
            if any(
                marker in form.group(0)
                for marker in ReadingService._LOGIN_FORM_MARKERS
            ):
                form_len += len(form.group(0))
                break
        return form_len > 0 and form_len / len(body) > 0.4

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

    return ReadingService._html_to_text_builtin(raw_html), "built-in stripper"


def _fetch_article_source(
    repo: HttpReadingRepository,
    extract_article: Callable[[bytes, str], tuple[str, str, str]],
    request: ReadingRequest,
    url: str,
    pdf_dir: Path,
    fetched: list[str],
    manual: list[tuple[str, str]],
) -> tuple[str, str, str, str] | None:
    """Fetch article source and return (text, title, extractor, raw_html).

    Returns None if the URL was handled (saved as PDF or recorded as manual).
    """
    if request.use_browser:
        html, err = repo.fetch_rendered_html(url, request.browser_timeout)
        time.sleep(request.delay)
        if not html:
            manual.append((url, err or "browser returned no content"))
            return None
        text, title, extractor = extract_article(html.encode("utf-8"), "")
        return text, title, extractor, html

    body, ctype, err, _ = repo.fetch_url(
        url, request.timeout, max_size=10 * 1024 * 1024
    )
    time.sleep(request.delay)
    if body is None:
        manual.append((url, err))
        return None
    if body.startswith(b"%PDF"):
        pdf_dir.mkdir(exist_ok=True)
        pdf_target = pdf_dir / (repo.safe_filename(url) + ".pdf")
        Path(pdf_target).write_bytes(body)
        fetched.append(str(pdf_target))
        return None
    text, title, extractor = extract_article(body, ctype)
    return text, title, extractor, body.decode("utf-8", errors="replace")
