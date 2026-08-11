#!/usr/bin/env python3
"""
fetch_readings.py — companion to preprocess_pdf.py

Reading lists mix PDFs you hold with readings that are only links. This
script reads a syllabus / reading-calendar PDF, pulls out every URL it
contains (including links hidden behind anchor text like "Part I"), then
fetches what it can as plain text in the same format preprocess_pdf.py
produces.

It is deliberately loud about failure. A paywalled or login-gated article
returns a sign-in page, not the reading — writing that to disk as if it
succeeded would be worse than useless. Anything that cannot be fetched
cleanly is listed at the end for manual capture.

WHAT IT DOES
  1. Extracts URLs from a PDF's link annotations AND visible text.
  2. Sorts them: video / direct-PDF / gated / fetchable article.
  3. Downloads direct PDFs (feed them to preprocess_pdf.py afterwards).
  4. Fetches articles and writes readable text with the same quality
     header and provenance notes as preprocess_pdf.py.
  5. Writes MANUAL_CAPTURE.txt listing everything you must save yourself.

WHAT IT DOES NOT DO
  It does not summarise, paraphrase, or generate text, and contains no AI
  model. It cannot invent content. It also makes no attempt to bypass
  paywalls, logins, or institutional proxies — those are listed for you
  to open in a browser where you are already signed in.

USAGE
  python fetch_readings.py "Reading master.pdf" --out-dir readings
  python fetch_readings.py syllabus.pdf --list-only      # just show URLs
  python fetch_readings.py --urls my_links.txt --out-dir readings

OPTIONS
  --out-dir DIR     Where to write output (default: ./readings)
  --list-only       Print the categorised URL list and exit; fetch nothing
  --urls FILE       Read URLs from a text file (one per line) instead of
                     or in addition to a PDF
  --include-videos  Write placeholder notes for video links (default: skip)
  --delay SECONDS   Pause between requests (default 1.5, be polite)
  --timeout SECONDS Per-request timeout (default 30)
  --overwrite       Refetch even if an output file already exists

REQUIRES
  Python 3.9+ and pypdf (pip install pypdf).
  Optional but STRONGLY recommended for much cleaner article text:
      pip install trafilatura
  Without it, a built-in fallback stripper is used, which is cruder and
  may leave navigation text behind. The output header always states which
  extractor was used.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

# --------------------------------------------------------------------------
# URL extraction from PDF
# --------------------------------------------------------------------------

_TEXT_URL_RE = re.compile(r"https?://[^\s<>\"'\)\]}]+", re.IGNORECASE)


def urls_from_pdf(pdf_path: str) -> list[tuple[int, str]]:
    """Return [(page_number, url), ...] found in a PDF.

    Checks link annotations first: syllabus documents usually hide the URL
    behind anchor text ("Part I", "Part II"), so scanning visible text
    alone misses most of them. Visible-text URLs are then added for the
    cases where a link was pasted as plain text.
    """
    try:
        import pypdf
    except ImportError:
        print("Error: pypdf is required to read PDFs. Install it with:\n"
              "    pip install pypdf", file=sys.stderr)
        sys.exit(1)

    found: list[tuple[int, str]] = []
    try:
        reader = pypdf.PdfReader(pdf_path)
    except Exception as e:
        print(f"Error: could not open {pdf_path}: {type(e).__name__}: {e}",
              file=sys.stderr)
        sys.exit(1)

    for page_num, page in enumerate(reader.pages, start=1):
        # 1) Link annotations (the important ones)
        try:
            for annot in page.get("/Annots") or []:
                try:
                    obj = annot.get_object()
                    action = obj.get("/A")
                    if action and "/URI" in action:
                        uri = str(action["/URI"]).strip()
                        if uri.lower().startswith(("http://", "https://")):
                            found.append((page_num, uri))
                except Exception:
                    continue
        except Exception:
            pass
        # 2) URLs written out as visible text
        try:
            for m in _TEXT_URL_RE.finditer(page.extract_text() or ""):
                found.append((page_num, m.group(0).rstrip(".,;)")))
        except Exception:
            pass

    seen: set[str] = set()
    unique: list[tuple[int, str]] = []
    for page_num, url in found:
        key = url.rstrip("/")
        if key not in seen:
            seen.add(key)
            unique.append((page_num, url))
    return unique


# --------------------------------------------------------------------------
# Categorisation
# --------------------------------------------------------------------------

_VIDEO_HOSTS = ("youtube.com", "youtu.be", "vimeo.com", "ted.com")

# Hosts that require a subscription or an institutional/library login.
# Fetching these returns a sign-in page, never the reading, so the script
# does not pretend otherwise — it routes them to manual capture.
_GATED_MARKERS = (
    "idm.oclc.org",        # institutional/library proxy (EZproxy / OCLC)
    "jstor.org",
    "tandfonline.com",
    "sciencedirect.com",
    "springer.com",
    "wiley.com",
    "ebscohost.com",
    "research-ebsco",
    "proquest.com",
    "muse.jhu.edu",
    "academic.oup.com",
)


def categorise(url: str) -> str:
    """Return one of: 'video', 'pdf', 'gated', 'article'."""
    host = urlparse(url).netloc.lower()
    path = urlparse(url).path.lower()
    # Exact host / subdomain match: substring matching mis-files legitimate
    # articles (e.g. "ted.com" in "hosted.com") as videos and silently skips them.
    if any(host == v or host.endswith("." + v) for v in _VIDEO_HOSTS):
        return "video"
    if any(g in host for g in _GATED_MARKERS):
        return "gated"
    if path.endswith(".pdf"):
        return "pdf"
    return "article"


def safe_filename(url: str, max_len: int = 80) -> str:
    """Build a readable, filesystem-safe filename from a URL."""
    parsed = urlparse(url)
    host = parsed.netloc.replace("www.", "")
    slug = parsed.path.strip("/").replace("/", "_") or "index"
    slug = re.sub(r"\.(html?|php|aspx)$", "", slug, flags=re.IGNORECASE)
    name = f"{host}_{slug}"
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-._")
    stem = name[:max_len]
    # Always append a short hash of the full URL. Building the stem is lossy —
    # the query string is dropped, non-alnum runs collapse to "-", the name is
    # truncated, and on a case-insensitive filesystem case-only differences
    # collide — so distinct URLs can produce the same readable stem. Without
    # the hash the second URL is silently skipped as "already fetched".
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:8]
    stem = f"{stem}-{digest}" if stem else digest
    return stem


# --------------------------------------------------------------------------
# Fetching
# --------------------------------------------------------------------------

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/122.0 Safari/537.36")


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Refuse to follow a redirect that leaves http(s).

    urllib's default handler permits redirects to ftp:// (and would to file://
    were it not separately blocked), so a compromised server could otherwise
    escalate a fetch to another scheme. Route such hops to manual capture.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urlparse(newurl).scheme.lower() not in ("http", "https"):
            raise urllib.error.HTTPError(
                newurl, code,
                f"refused redirect to non-http(s) URL: {newurl}", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(_SafeRedirectHandler)


def fetch_url(url: str, timeout: int) -> tuple[bytes | None, str, str]:
    """Fetch a URL. Returns (body_bytes, content_type, error_message)."""
    # Only ever fetch over HTTP(S). urllib also honours file:// and ftp://, so
    # an untrusted URL list could otherwise read local files (e.g.
    # file:///C:/Users/.../id_rsa) into the output folder. Redirects are
    # scheme-checked too, via _SafeRedirectHandler.
    scheme = urlparse(url).scheme.lower()
    if scheme not in ("http", "https"):
        return None, "", f"refused non-http(s) URL scheme: {scheme or 'none'}"
    req = urllib.request.Request(url, headers={
        "User-Agent": _UA,
        "Accept": "text/html,application/xhtml+xml,application/pdf,*/*",
        "Accept-Language": "en-GB,en;q=0.9",
    })
    try:
        with _OPENER.open(req, timeout=timeout) as resp:
            return resp.read(), resp.headers.get("Content-Type", ""), ""
    except urllib.error.HTTPError as e:
        return None, "", f"HTTP {e.code} {e.reason}"
    except urllib.error.URLError as e:
        return None, "", f"connection failed: {e.reason}"
    except Exception as e:
        return None, "", f"{type(e).__name__}: {e}"


# --------------------------------------------------------------------------
# HTML -> text
# --------------------------------------------------------------------------

_STRIP_BLOCKS = re.compile(
    r"<(script|style|noscript|svg|form|nav|header|footer|aside)\b.*?</\1>",
    re.IGNORECASE | re.DOTALL)
_BLOCK_END = re.compile(
    r"</(p|div|section|article|h[1-6]|li|tr|blockquote)\s*>",
    re.IGNORECASE)
_BR = re.compile(r"<br\s*/?>", re.IGNORECASE)
_TAG = re.compile(r"<[^>]+>")
_MULTI_NL = re.compile(r"\n{3,}")
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)


def html_to_text_builtin(raw_html: str) -> str:
    """Crude but dependency-free HTML text extraction.

    Used only when trafilatura is unavailable. It removes scripts, styles
    and obvious chrome, converts block ends to newlines, strips remaining
    tags and unescapes entities. It can leave navigation text behind —
    which is why the output header records that this extractor was used.
    """
    text = _STRIP_BLOCKS.sub(" ", raw_html)
    text = _BR.sub("\n", text)
    text = _BLOCK_END.sub("\n\n", text)
    text = _TAG.sub(" ", text)
    text = html.unescape(text)
    text = "\n".join(re.sub(r"[ \t\xa0]+", " ", ln).strip()
                     for ln in text.splitlines())
    return _MULTI_NL.sub("\n\n", text).strip()


def extract_article(raw: bytes) -> tuple[str, str, str]:
    """Return (text, title, extractor_name)."""
    try:
        raw_html = raw.decode("utf-8", errors="replace")
    except Exception:
        raw_html = str(raw)

    title = ""
    m = _TITLE.search(raw_html)
    if m:
        title = html.unescape(re.sub(r"\s+", " ", m.group(1))).strip()

    try:
        import trafilatura
        extracted = trafilatura.extract(
            raw_html, include_comments=False, include_tables=True,
            favor_precision=True)
        if extracted and len(extracted.split()) > 50:
            return extracted.strip(), title, "trafilatura"
    except ImportError:
        pass
    except Exception:
        pass

    return html_to_text_builtin(raw_html), title, "built-in stripper"


# --------------------------------------------------------------------------
# Gate detection — never let a login page masquerade as a reading
# --------------------------------------------------------------------------

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


def _has_login_form(html: str) -> bool:
    """Return True if the HTML contains a form that looks like a login gate."""
    low_html = html.lower()
    for form in _LOGIN_FORM_RE.finditer(low_html):
        block = form.group(0)
        if any(marker in block for marker in _LOGIN_FORM_MARKERS):
            return True
    return False


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
    if _has_login_form(html):
        return "page contains a login form"
    return looks_gated(text, word_count, min_words=min_words)


# --------------------------------------------------------------------------
# Sanitize invisible/bidi characters — fetched web pages are the only
# attacker-influenced input here, and the output is destined for an assistant,
# so strip exactly the hidden-character classes preprocess_pdf.py removes.
#
# This mirrors preprocess_pdf.py.sanitize() codepoint-for-codepoint. It used to
# be a regex character class, which had silently drifted out of sync — it missed
# U+034F, U+061C, U+180E and the Hangul fillers (U+115F/U+1160/U+3164/U+FFA0)
# that the sibling strips, while over-matching a few deprecated ranges it does
# not. An explicit codepoint set keeps the two provably in lockstep.
# --------------------------------------------------------------------------

_ZERO_WIDTH_CODEPOINTS = frozenset({
    0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF, 0x00AD, 0x034F, 0x180E,
    0x2061, 0x2062, 0x2063, 0x2064,
})
_BIDI_CONTROL_CODEPOINTS = frozenset({
    0x200E, 0x200F, 0x061C, 0x202A, 0x202B, 0x202C, 0x202D, 0x202E,
    0x2066, 0x2067, 0x2068, 0x2069,
})
_INVISIBLE_LETTER_CODEPOINTS = frozenset({0x115F, 0x1160, 0x3164, 0xFFA0})
_INVISIBLE_CODEPOINTS = (
    _ZERO_WIDTH_CODEPOINTS | _BIDI_CONTROL_CODEPOINTS | _INVISIBLE_LETTER_CODEPOINTS
)
_TAG_BLOCK_START, _TAG_BLOCK_END = 0xE0000, 0xE007F


def strip_hidden(s: str) -> str:
    return "".join(
        ch for ch in s
        if ord(ch) not in _INVISIBLE_CODEPOINTS
        and not (_TAG_BLOCK_START <= ord(ch) <= _TAG_BLOCK_END)
    )


# --------------------------------------------------------------------------
# Output formatting — mirrors preprocess_pdf.py conventions
# --------------------------------------------------------------------------

def format_header(url: str, title: str, extractor: str, words: int,
                  source_page: int | None) -> str:
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


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Extract reading URLs from a syllabus PDF and fetch them "
                    "as text.")
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
    ap.add_argument("--min-words", type=int, default=120,
                    help="minimum word count for an article to be considered "
                         "successfully fetched (default 120)")
    ap.add_argument("--dry-run", action="store_true",
                    help="categorise URLs and report what would be fetched, "
                         "but make no network requests and write no files")
    args = ap.parse_args()

    if not args.pdf and not args.urls:
        ap.error("give a syllabus PDF, or --urls FILE (or both)")

    entries: list[tuple[int | None, str]] = []
    if args.pdf:
        if not Path(args.pdf).is_file():
            print(f"Error: {args.pdf} not found", file=sys.stderr)
            sys.exit(1)
        entries += urls_from_pdf(args.pdf)
    if args.urls:
        if not Path(args.urls).is_file():
            print(f"Error: {args.urls} not found", file=sys.stderr)
            sys.exit(1)
        for line in Path(args.urls).read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if not line.lower().startswith(("http://", "https://")):
                print(f"  skip (not http/https): {line}", file=sys.stderr)
                continue
            entries.append((None, line))

    # Deduplicate, preserving order.
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
        buckets[categorise(url)].append((page, url))

    print(f"Found {len(unique)} unique URL(s):", file=sys.stderr)
    print(f"  {len(buckets['article'])} article(s) to fetch", file=sys.stderr)
    print(f"  {len(buckets['pdf'])} direct PDF(s) to download", file=sys.stderr)
    print(f"  {len(buckets['gated'])} gated/paywalled (manual capture needed)",
          file=sys.stderr)
    print(f"  {len(buckets['video'])} video(s) "
          f"({'noted' if args.include_videos else 'skipped'})", file=sys.stderr)

    if args.list_only:
        for kind in ("article", "pdf", "gated", "video"):
            if not buckets[kind]:
                continue
            print(f"\n--- {kind.upper()} ---")
            for page, url in buckets[kind]:
                loc = f"[p.{page}] " if page else ""
                print(f"  {loc}{url}")
        return

    if args.dry_run:
        print(f"\n=== DRY RUN - no network requests, no files written ===",
              file=sys.stderr)
        print(f"Output directory would be: {args.out_dir}", file=sys.stderr)
        for kind, label in (
            ("article", "would fetch as text"),
            ("pdf", "would download as PDF"),
            ("gated", "would route to MANUAL_CAPTURE.txt"),
            ("video", "would be noted as video" if args.include_videos
             else "would be skipped (video)"),
        ):
            if not buckets[kind]:
                continue
            print(f"\n--- {label} ---", file=sys.stderr)
            for page, url in buckets[kind]:
                loc = f"[p.{page}] " if page else ""
                print(f"  {loc}{url}", file=sys.stderr)
        print(f"\nEstimated MANUAL_CAPTURE.txt entries: "
              f"{len(buckets['gated'])}", file=sys.stderr)
        return

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    pdf_dir = out_dir / "downloaded_pdfs"

    fetched: list[str] = []
    manual: list[tuple[str, str]] = []   # (url, reason)

    # ---- direct PDFs -----------------------------------------------------
    for page, url in buckets["pdf"]:
        pdf_dir.mkdir(exist_ok=True)
        target = pdf_dir / (safe_filename(url) + ".pdf")
        if target.exists() and not args.overwrite:
            print(f"  skip (exists): {target.name}", file=sys.stderr)
            continue
        print(f"  downloading PDF: {url[:70]}...", file=sys.stderr)
        body, ctype, err = fetch_url(url, args.timeout)
        time.sleep(args.delay)
        if body is None:
            manual.append((url, err))
            continue
        if not body.startswith(b"%PDF"):
            manual.append((url, "server did not return a PDF "
                                "(likely a login or landing page)"))
            continue
        target.write_bytes(body)
        fetched.append(str(target))

    # ---- articles --------------------------------------------------------
    for page, url in buckets["article"]:
        stem = safe_filename(url)
        target = out_dir / (stem + ".txt")
        # An "article" URL can turn out to serve a PDF (publisher landing pages
        # do this). That produces a .pdf, never the .txt, so checking only the
        # .txt would re-fetch and overwrite that PDF on every run. Skip if
        # either output already exists.
        pdf_target = pdf_dir / (stem + ".pdf")
        if not args.overwrite and (target.exists() or pdf_target.exists()):
            existing = target if target.exists() else pdf_target
            print(f"  skip (exists): {existing.name}", file=sys.stderr)
            continue
        print(f"  fetching: {url[:70]}...", file=sys.stderr)
        body, ctype, err = fetch_url(url, args.timeout)
        time.sleep(args.delay)
        if body is None:
            manual.append((url, err))
            continue
        if body.startswith(b"%PDF"):
            pdf_dir.mkdir(exist_ok=True)
            pdf_target.write_bytes(body)
            fetched.append(str(pdf_target))
            continue

        text, title, extractor = extract_article(body)
        text, title = strip_hidden(text), strip_hidden(title)
        words = len(text.split())
        raw_html = body.decode("utf-8", errors="replace")
        reason = page_looks_gated(raw_html, text, words, min_words=args.min_words)
        if reason:
            manual.append((url, reason))
            continue
        target.write_text(
            format_header(url, title, extractor, words, page) + text,
            encoding="utf-8")
        fetched.append(str(target))

    # ---- videos ----------------------------------------------------------
    if args.include_videos:
        for page, url in buckets["video"]:
            target = out_dir / (safe_filename(url) + ".txt")
            if target.exists() and not args.overwrite:
                continue
            target.write_text(
                "=" * 72 + "\nVIDEO READING - NOT TEXT-EXTRACTABLE\n"
                + "=" * 72 + f"\n\n  URL: {url}\n"
                + (f"  Listed on page {page} of the syllabus PDF\n" if page else "")
                + "\n  This is a video. Watch it directly; no transcript was\n"
                  "  retrieved. If you need a transcript, use the platform's\n"
                  "  own caption/transcript feature.\n",
                encoding="utf-8")
    for page, url in buckets["gated"]:
        manual.append((url, "subscription or institutional login required"))

    # ---- manual capture list --------------------------------------------
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
    if buckets["video"] and not args.include_videos:
        lines += ["", "VIDEOS (watch directly; not text)", ""]
        lines += [f"  {u}" for _, u in buckets["video"]]
    manual_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"\n=== Summary ===", file=sys.stderr)
    print(f"  fetched OK:      {len(fetched)}", file=sys.stderr)
    print(f"  manual capture:  {len(manual)}  -> {manual_path}", file=sys.stderr)
    if pdf_dir.exists():
        print(f"\n  Downloaded PDFs are in {pdf_dir}", file=sys.stderr)
        print(f"  Process them with:", file=sys.stderr)
        print(f"      python preprocess_pdf.py \"{pdf_dir}\" "
              f"--out-dir \"{out_dir}\"", file=sys.stderr)


if __name__ == "__main__":
    try:
        main()
    except BrokenPipeError:
        sys.exit(0)
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        sys.exit(130)
