#!/usr/bin/env python3
"""
preprocess_pdf.py — turn large/scanned PDF books into clean, grep-able .txt
files so they never have to be re-ingested whole (fixes the Claude PDF
ingestion size ceiling that truncates 30MB+ scans around pages 48-69).

Pipeline (adapted from virgiliojr94/book-to-skill, extraction layer only —
no synthesis, no summarization, output is the full clean source text):

  1. Extract text locally, per page, via pdftotext -layout (falling back to
     pypdf if pdftotext is unavailable).
  2. OCR fallback: any page whose extracted text falls below a word-count
     threshold (i.e. a scanned/image page with no real text layer) is
     deskewed/contrast-cleaned, rendered to an image with pdftoppm, and
     OCR'd with tesseract. Typeset pages are left alone — OCR only runs
     where it's actually needed, which keeps a mostly-typeset book fast.
  3. Clean: strip repeated running headers/footers and bare edge-of-page
     numbers, rejoin hyphenated line-wraps.
  4. Strip invisible/bidi/tag-block Unicode characters that can hide
     prompt-injection in scanned/OCR'd text.
  5. Insert clear "--- PAGE N ---" markers (OCR'd pages marked "[OCR]") so
     ranges can be pulled with sed.
  6. Detect BOOK-level and CHAPTER-level headings (Arabic numerals, Roman
     numerals, and spelled-out numbers like "BOOK ONE") separately, and
     print a line-number index so you can jump straight to an assigned
     range instead of hand-locating it.

Usage — single file:
    python3 preprocess_pdf.py clausewitz.pdf
    python3 preprocess_pdf.py clausewitz.pdf -o clausewitz.txt

Usage — batch (folder or glob), skips files already processed:
    python3 preprocess_pdf.py "~/Semester 1 Readings/"
    python3 preprocess_pdf.py "~/Semester 1 Readings/*.pdf" --out-dir ./extracted

Usage — preflight check (no processing):
    python3 preprocess_pdf.py --check

Options:
    -o, --out PATH       Explicit output path. Only valid when exactly one
                          PDF is being processed.
    --out-dir DIR        Write all outputs into DIR instead of alongside
                          each source PDF.
    --overwrite          Reprocess even if a matching .txt output already
                          exists (default: skip already-processed files).
    --force-ocr          OCR every page regardless of extracted text (use
                          for books that are scans throughout).
    --ocr-lang LANG      tesseract language code, default "eng". Use "+" to
                          combine, e.g. "eng+lat" for Latin quotations.
    --ocr-dpi N          Render resolution for OCR, default 300 (higher =
                          more accurate, slower). Try 400 if OCR text looks
                          garbled on small/dense print, especially Roman
                          numerals (tesseract confuses "II." with "Il.").
    --ocr-threshold N    Pages with fewer than N extracted words are treated
                          as scans and OCR'd. Default 8.
    --no-deskew          Skip the deskew/contrast pass before OCR (it's on
                          by default — turn off only if it's making a
                          particular scan worse).
    --check              Report which required/optional tools are installed
                          and exit. Run this first on a new machine.

Requires: poppler-utils (pdftotext, pdftoppm, pdfinfo) and tesseract-ocr on
PATH for OCR. ImageMagick (convert) is optional, used for deskew.
Install:
  Linux:    sudo apt install poppler-utils tesseract-ocr imagemagick
  macOS:    brew install poppler tesseract imagemagick
  Windows:  winget install --id=oschwartz10612.Poppler
            winget install --id=UB-Mannheim.TesseractOCR
            winget install --id=ImageMagick.ImageMagick
            (then ensure each install's bin folder is on PATH)

Then, instead of ingesting the PDF, pull only the range you need:
    grep -n "^--- PAGE" output.txt | head -80           # find page markers
    sed -n '1500,2200p' output.txt                       # pull just that slice
    grep -n "^\\[BOOK\\]\\|^\\[CH\\]" output.txt.index    # book/chapter index (see .index file)
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

# ---------------------------------------------------------------------------
# Step 1 — extraction (fallback chain)
# ---------------------------------------------------------------------------

# A bare page number: Arabic, or a *valid* roman numeral. The roman branch is
# strict (lookahead requires at least one roman letter, then a canonical
# numeral) so real words like "civil" or "mild" aren't deleted as page numbers.
_PDF_PAGE_NUM = re.compile(
    r"^\s*(?:\d{1,4}|"
    r"(?=[ivxlcdm])m{0,4}(?:cm|cd|d?c{0,3})(?:xc|xl|l?x{0,3})(?:ix|iv|v?i{0,3}))"
    r"\s*$",
    re.IGNORECASE)
# Letters only on both sides: a digit-side match corrupts wrapped ranges
# ("1914-\n1918" -> "19141918").
_PDF_HYPHEN_WRAP = re.compile(r"([^\W\d_])-\n([^\W\d_])")
# Count words in any script, not just Latin, so a non-Latin --ocr-lang doesn't
# force needless OCR over a perfectly good text layer. English is unaffected.
_WORD_RE = re.compile(r"[^\W\d_]{2,}", re.UNICODE)


def count_pages(pdf_path: str) -> int:
    if shutil.which("pdfinfo"):
        try:
            result = subprocess.run(
                ["pdfinfo", pdf_path], capture_output=True, text=True, timeout=30,
            )
            for line in result.stdout.splitlines():
                if line.startswith("Pages:"):
                    return int(line.split(":")[1].strip())
        except Exception:
            pass
    try:
        import pypdf
        with open(pdf_path, "rb") as f:
            return len(pypdf.PdfReader(f).pages)
    except Exception:
        return 0


def extract_pages_pdftotext(pdf_path: str, total_pages: int) -> list[str] | None:
    """Preferred: preserves per-page layout via form-feed (\\f) separators,
    which we need both for header/footer detection and per-page OCR
    fallback. A scanned page with no text layer produces an *empty* string
    between form-feeds — that emptiness is the OCR trigger, not noise to
    strip, so we only trim a genuine trailing artifact (never below the
    known page count from pdfinfo)."""
    if not shutil.which("pdftotext"):
        return None
    try:
        result = subprocess.run(
            ["pdftotext", "-layout", pdf_path, "-"],
            capture_output=True, text=True, timeout=600,
            encoding="utf-8", errors="replace",
        )
        if result.returncode == 0 and result.stdout:
            pages = result.stdout.split("\f")
            # pdftotext emits a trailing \f after the last real page, producing
            # one (occasionally two) extra empty element(s). Trim trailing blank
            # elements, but never below total_pages when it's known — so a
            # genuinely blank final page is preserved while the +1/+2 form-feed
            # artifact is healed rather than surfacing as a page-count mismatch.
            if total_pages:
                while len(pages) > total_pages and not pages[-1].strip():
                    pages.pop()
            else:
                while pages and not pages[-1].strip():
                    pages.pop()
            return pages
    except Exception as e:
        print(f"  [warn] pdftotext failed: {type(e).__name__}: {e}", file=sys.stderr)
    return None


def extract_pages_pypdf(pdf_path: str) -> list[str] | None:
    try:
        import pypdf
    except ImportError:
        return None
    try:
        pages = []
        with open(pdf_path, "rb") as f:
            reader = pypdf.PdfReader(f)
            for page in reader.pages:
                try:
                    pages.append(page.extract_text() or "")
                except Exception:
                    pages.append("")
        return pages
    except Exception as e:
        print(f"  [warn] pypdf failed: {type(e).__name__}: {e}", file=sys.stderr)
        return None


def extract_pages_any(pdf_path: str, total_pages: int) -> tuple[list[str], str]:
    """Try each non-OCR extractor in order. Returns (pages, method_used).
    If both fail, returns a list of empty strings so the OCR fallback in
    main() picks up every page."""
    pages = extract_pages_pdftotext(pdf_path, total_pages)
    if pages:
        return pages, "pdftotext -layout"
    pages = extract_pages_pypdf(pdf_path)
    if pages:
        return pages, "pypdf"
    print("  [warn] no text-layer extractor available or succeeded — "
          "every page will need OCR", file=sys.stderr)
    return [""] * max(total_pages, 1), "none (OCR required for all pages)"


# ---------------------------------------------------------------------------
# Step 2 (new) — OCR fallback for scanned/image-only pages
# ---------------------------------------------------------------------------

def page_needs_ocr(page_text: str, threshold: int) -> bool:
    return len(_WORD_RE.findall(page_text)) < threshold


def _imagemagick_cmd() -> list[str] | None:
    """Resolve the ImageMagick CLI safely across platforms.
    Prefers 'magick' (ImageMagick 7 — the only command name on modern
    Windows installs). Falls back to 'convert' (ImageMagick 6) ONLY when it
    is not Windows' built-in System32 convert.exe — that program is the
    NTFS filesystem converter, not an image tool, and must never be
    invoked here."""
    magick = shutil.which("magick")
    if magick:
        return [magick]
    convert = shutil.which("convert")
    if convert and "system32" not in convert.lower():
        return [convert]
    return None


def ocr_page(pdf_path: str, page_num: int, dpi: int, lang: str, workdir: str,
             deskew: bool = True) -> str:
    """Render a single page to PNG with pdftoppm, optionally deskew/clean it
    with ImageMagick, and OCR it with tesseract. Raises RuntimeError with a
    clear message if a required tool is missing."""
    if not shutil.which("pdftoppm"):
        raise RuntimeError(
            "pdftoppm not found (needed for OCR). Install poppler-utils: "
            "Linux: sudo apt install poppler-utils | macOS: brew install poppler | "
            "Windows: winget install oschwartz10612.Poppler (add bin to PATH)"
        )
    if not shutil.which("tesseract"):
        raise RuntimeError(
            "tesseract not found. Linux: sudo apt install tesseract-ocr | "
            "macOS: brew install tesseract | "
            "Windows: winget install UB-Mannheim.TesseractOCR (add to PATH)"
        )
    prefix = str(Path(workdir) / f"pg{page_num}")
    subprocess.run(
        ["pdftoppm", "-f", str(page_num), "-l", str(page_num),
         "-r", str(dpi), "-png", "-gray", pdf_path, prefix],
        capture_output=True, timeout=120, check=True,
    )
    img_path = f"{prefix}-{page_num}.png"
    if not Path(img_path).is_file():
        # Some poppler versions omit zero-padding differently; find whatever
        # was produced for this prefix instead of guessing the exact name.
        matches = list(Path(workdir).glob(f"pg{page_num}-*.png"))
        if not matches:
            raise RuntimeError(f"pdftoppm did not produce an image for page {page_num}")
        img_path = str(matches[0])

    _im = _imagemagick_cmd()
    if deskew and _im:
        deskewed_path = f"{prefix}-deskewed.png"
        try:
            subprocess.run(
                _im + [img_path,
                        "-deskew", "40%",
                        "-contrast-stretch", "0.5%x0.5%",
                        deskewed_path],
                capture_output=True, timeout=60, check=True,
            )
            if Path(deskewed_path).is_file():
                img_path = deskewed_path
        except Exception:
            pass  # fall back to the un-deskewed image rather than fail the page

    result = subprocess.run(
        ["tesseract", img_path, "stdout", "-l", lang],
        capture_output=True, text=True, timeout=120,
        encoding="utf-8", errors="replace",
    )
    # A nonzero exit (e.g. a missing language pack) yields empty stdout, which
    # would otherwise be stored as a blank page and reported as a successful
    # OCR read — silent data loss. Fail loudly instead.
    if result.returncode != 0:
        raise RuntimeError(
            f"tesseract exited {result.returncode}: "
            f"{(result.stderr or '').strip()[:200]}")
    # Some tesseract versions append a form-feed page separator; strip it so it
    # can't inject a phantom page break when pages are \f-joined.
    return result.stdout.replace("\f", "")


def extract_text_any(
    pdf_path: str,
    ocr_lang: str = "eng",
    ocr_dpi: int = 300,
    ocr_threshold: int = 8,
    force_ocr: bool = False,
    deskew: bool = True,
) -> tuple[str, str, list[int], int]:
    """Full extraction pipeline with per-page OCR fallback.
    Returns (form-feed-joined text, method summary, list of OCR'd page numbers,
    total page count from pdfinfo/pypdf). The page count is returned rather than
    recomputed by the caller so both the trim logic here and the quality report
    downstream see the same authoritative number from a single pdfinfo call.
    """
    # Absolutise so a filename starting with '-' can't be read as an option by
    # pdfinfo/pdftotext/pdftoppm, and relative paths resolve consistently.
    pdf_path = os.path.abspath(pdf_path)
    total_pages = count_pages(pdf_path)
    pages, method = extract_pages_any(pdf_path, total_pages)

    ocr_needed = [
        i + 1 for i, p in enumerate(pages)
        if force_ocr or page_needs_ocr(p, ocr_threshold)
    ]

    if ocr_needed:
        print(f"  {len(ocr_needed)} of {len(pages)} page(s) need OCR "
              f"(scanned/no text layer) — this is the slow part, ~1-3s/page",
              file=sys.stderr)
        ocr_failed: list[int] = []
        with tempfile.TemporaryDirectory(prefix="preprocess_pdf_ocr_") as workdir:
            for n, page_num in enumerate(ocr_needed, start=1):
                print(f"    OCR page {page_num} ({n}/{len(ocr_needed)})...",
                      file=sys.stderr, end="\r")
                try:
                    pages[page_num - 1] = ocr_page(
                        pdf_path, page_num, ocr_dpi, ocr_lang, workdir,
                        deskew=deskew,
                    )
                except Exception as e:
                    ocr_failed.append(page_num)
                    print(f"\n  [warn] OCR failed on page {page_num}: "
                          f"{type(e).__name__}: {e}", file=sys.stderr)
            print(file=sys.stderr)  # newline after \r progress
        if ocr_failed:
            # A page whose OCR failed keeps its (near-empty) extracted text.
            # Drop it from the OCR list so it is NOT tagged [OCR] or counted as
            # a successful OCR read in the quality report — reporting a failure
            # as a success is exactly what this tool exists to prevent.
            print(f"  [warn] OCR failed on {len(ocr_failed)} page(s): "
                  f"{', '.join(map(str, ocr_failed))}. Left as extracted text, "
                  f"not tagged [OCR]; check these pages against the PDF.",
                  file=sys.stderr)
            failed_set = set(ocr_failed)
            ocr_needed = [p for p in ocr_needed if p not in failed_set]
        method = f"{method} + tesseract OCR ({len(ocr_needed)} page(s))"

    return "\f".join(pages), method, ocr_needed, total_pages


# ---------------------------------------------------------------------------
# Step 2 — clean: strip running headers/footers, page numbers, dehyphenate
# ---------------------------------------------------------------------------

def clean_and_mark_pages(text: str, ocr_pages: set[int] | None = None) -> str:
    """Split on form-feed page breaks, drop boilerplate running
    headers/footers (a top/bottom line repeated on >50% of pages) and bare
    edge-of-page numbers, rejoin hyphen-wrapped words, and re-emit with
    explicit '--- PAGE N ---' markers (OCR'd pages tagged '[OCR]' so you
    know which text passed through OCR and may need a closer read for exact
    quotes).

    Does NOT trim trailing empty pages — extract_text_any() already produces
    exactly one entry per real page (verified against pdfinfo's page count),
    so a trailing blank here is a genuinely blank page (e.g. an endpaper),
    not an extraction artifact. Silently dropping it would misnumber or
    hide real pages if that assumption is ever wrong."""
    ocr_pages = ocr_pages or set()
    pages = text.split("\f")

    if len(pages) >= 3:
        edge = Counter()
        for p in pages:
            nb = [ln.strip() for ln in p.splitlines() if ln.strip()]
            if nb:
                edge[nb[0]] += 1
                edge[nb[-1]] += 1
        boiler = {ln for ln, c in edge.items() if c > len(pages) / 2}
    else:
        boiler = set()

    out_lines = []
    for page_num, page in enumerate(pages, start=1):
        lines = page.splitlines()
        nb_idx = [i for i, ln in enumerate(lines) if ln.strip()]
        first = nb_idx[0] if nb_idx else None
        last = nb_idx[-1] if nb_idx else None
        kept = []
        for i, ln in enumerate(lines):
            s = ln.strip()
            # Only strip a repeated running header/footer or a bare page number
            # when it sits at the very top or bottom of the page — never a body
            # line that merely happens to equal the running header.
            if i in (first, last) and (s in boiler or _PDF_PAGE_NUM.match(s)):
                continue
            kept.append(ln)
        tag = " [OCR]" if page_num in ocr_pages else ""
        blank_tag = " [BLANK]" if not any(ln.strip() for ln in kept) else ""
        out_lines.append(f"--- PAGE {page_num}{tag}{blank_tag} ---")
        out_lines.append("\n".join(kept))

    joined = "\n".join(out_lines)
    # Rejoin words split by a line-wrapping hyphen. Naive: may over-join a
    # genuinely hyphenated compound that happened to wrap ("well-\nknown" ->
    # "wellknown"). Spot-check chapter openings if that matters for a quote.
    return _PDF_HYPHEN_WRAP.sub(r"\1\2", joined)


# ---------------------------------------------------------------------------
# Step 3 — sanitize invisible/bidi/tag-block characters
# ---------------------------------------------------------------------------

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


def sanitize(text: str) -> tuple[str, int]:
    kept, removed = [], 0
    for ch in text:
        cp = ord(ch)
        if cp in _INVISIBLE_CODEPOINTS or _TAG_BLOCK_START <= cp <= _TAG_BLOCK_END:
            removed += 1
            continue
        kept.append(ch)
    return "".join(kept), removed


# ---------------------------------------------------------------------------
# Step 4 — heading index: embedded PDF outline first, text regex fallback
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# PDF metadata — title/author, with validation
# ---------------------------------------------------------------------------

# PDF Title fields are frequently garbage: an internal asset ID, the
# originating Word/InDesign filename, an ISBN, or boilerplate. These are
# real examples encountered in testing, e.g. a scanned book whose Title
# read "imageItem8901132859708402734#_#9780190265687". A wrong-but-
# confident filename is worse than no rename, so titles are validated
# before use and rejected on any of these signals.
_JUNK_TITLE_PATTERNS = [
    re.compile(r"^\s*$"),
    re.compile(r"^untitled", re.IGNORECASE),
    re.compile(r"^(microsoft )?word[ \-_]", re.IGNORECASE),
    re.compile(r"^document\d*$", re.IGNORECASE),
    re.compile(r"\.(docx?|pdf|indd|qxd|tex|pages|rtf|txt)\s*$", re.IGNORECASE),
    re.compile(r"^imageitem", re.IGNORECASE),
    re.compile(r"^[0-9\-#_ ]+$"),                    # all digits/punctuation
    re.compile(r"^[0-9a-f]{16,}$", re.IGNORECASE),   # long hex/asset id
    re.compile(r"#_#"),                              # asset-id separator
    re.compile(r"^\d{9,13}$"),                       # bare ISBN
    re.compile(r"^print$|^layout$|^cover$|^final$", re.IGNORECASE),
]


def _clean_meta_string(value) -> str:
    if value is None:
        return ""
    text = " ".join(str(value).split())
    # Strip trailing separators publishers leave behind ("David Kilcullen;")
    return text.strip(" ;,·|-")


def _title_is_usable(title: str) -> bool:
    if not title or len(title) < 4 or len(title) > 200:
        return False
    if any(p.search(title) for p in _JUNK_TITLE_PATTERNS):
        return False
    # Needs at least two letter-containing words to look like a real title.
    words = [w for w in re.split(r"\s+", title) if re.search(r"[A-Za-z]", w)]
    return len(words) >= 2


def extract_pdf_metadata(pdf_path: str) -> dict:
    """Read Title/Author/year from a PDF's metadata.

    Returns a dict with 'title', 'author', 'year' — each an empty string
    when absent or judged unreliable. 'title_rejected' records a junk
    title that was found but discarded, so the header can show it rather
    than silently hiding what the file claims."""
    result = {"title": "", "author": "", "year": "", "title_rejected": ""}
    try:
        import pypdf
    except ImportError:
        return result
    try:
        meta = pypdf.PdfReader(pdf_path).metadata or {}
    except Exception:
        return result

    raw_title = _clean_meta_string(meta.get("/Title"))
    if raw_title:
        if _title_is_usable(raw_title):
            result["title"] = raw_title
        elif not re.match(r"^untitled\s*$", raw_title, re.IGNORECASE):
            # Only report a rejected title when there was a real string to
            # reject; a literal "untitled" is the same as having none.
            result["title_rejected"] = raw_title

    author = _clean_meta_string(meta.get("/Author"))
    if author and 2 <= len(author) <= 120 and re.search(r"[A-Za-z]", author):
        result["author"] = author

    for key in ("/CreationDate", "/ModDate"):
        m = re.search(r"D:(\d{4})", str(meta.get(key) or ""))
        if m:
            year = int(m.group(1))
            if 1400 <= year <= 2100:
                result["year"] = str(year)
                break
    return result


# Characters Windows forbids in filenames, plus control chars.
_UNSAFE_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def build_metadata_filename(meta: dict, fallback_stem: str,
                            max_len: int = 120) -> tuple[str, str]:
    """Build 'Author - Title (Year)' from metadata.

    Returns (stem, reason). If metadata is insufficient the fallback stem
    is returned unchanged with a reason explaining why — this never
    invents a title it does not have."""
    title, author, year = meta["title"], meta["author"], meta["year"]

    if not title:
        why = (f"PDF's title field was not a real title "
               f"({meta['title_rejected'][:40]!r})" if meta["title_rejected"]
               else "PDF has no title in its metadata")
        return fallback_stem, why

    parts = []
    if author:
        # "Surname, First" -> "First Surname" reads better in a filename.
        if author.count(",") == 1 and " and " not in author.lower():
            last, first = (s.strip() for s in author.split(","))
            if last and first:
                author = f"{first} {last}"
        parts.append(author)
    parts.append(title)
    stem = " - ".join(parts)
    if year:
        stem += f" ({year})"

    stem = _UNSAFE_FILENAME.sub("-", stem)
    stem = re.sub(r"\s+", " ", stem).strip(" .")
    if stem.upper().split(".")[0] in _WINDOWS_RESERVED:
        stem = f"_{stem}"
    if len(stem) > max_len:
        stem = stem[:max_len].rstrip(" -")
    return (stem or fallback_stem), ""


def extract_pdf_outline(pdf_path: str) -> list[tuple[int, int, str]]:
    """Read the PDF's embedded outline (bookmarks) via pypdf.
    Returns [(page_number, depth, title), ...] sorted by page — the
    authoritative chapter structure straight from the publisher, when
    present. Empty list if no outline or pypdf unavailable."""
    try:
        import pypdf
    except ImportError:
        return []
    entries: list[tuple[int, int, str]] = []
    try:
        reader = pypdf.PdfReader(pdf_path)

        def walk(items, depth=0):
            for it in items:
                if isinstance(it, list):
                    walk(it, depth + 1)
                    continue
                try:
                    page = reader.get_destination_page_number(it) + 1
                except Exception:
                    continue
                title = " ".join(str(it.title).split())  # collapse \n / nbsp
                if title:
                    entries.append((page, depth, title))

        walk(reader.outline)
    except Exception as e:
        print(f"  [warn] could not read PDF outline: {type(e).__name__}: {e}",
              file=sys.stderr)
        return []
    entries.sort(key=lambda t: (t[0], t[1]))
    return entries


_ROMAN_VALUES = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}

_WORD_NUMBERS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
    "twenty": 20, "first": 1, "second": 2, "third": 3, "fourth": 4,
    "fifth": 5, "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10,
}


def _roman_to_int(s: str) -> int | None:
    s = s.upper()
    total = prev = 0
    for ch in reversed(s):
        v = _ROMAN_VALUES.get(ch)
        if v is None:
            return None
        total += -v if v < prev else v
        prev = max(prev, v)
    return total if 0 < total <= 200 else None


def _numeral_value(token: str) -> int | None:
    """Resolve a heading's number token — Arabic, Roman, or spelled-out
    (e.g. "ONE", "First") — to an int, or None if it isn't a real number."""
    token = token.strip().rstrip(".:")
    if token.isdigit():
        return int(token)
    roman = _roman_to_int(token)
    if roman is not None:
        return roman
    return _WORD_NUMBERS.get(token.lower())


# BOOK is checked before CHAPTER: many classic translations (e.g. Howard/
# Paret's "On War") structure the top level as "BOOK ONE" / "BOOK TWO" in
# caps, with numbered chapters nested inside each book. Treating these as a
# separate, higher level matters — a heading index that only sees "Chapter"
# loses the book boundary entirely.
_BOOK_PATTERN = re.compile(
    r"^\s*BOOK\s+([A-Za-z]+|\d{1,3}|[IVXLCDM]{1,7})\b\.?\s*$|"
    r"^\s*BOOK\s+([A-Za-z]+|\d{1,3}|[IVXLCDM]{1,7})\s*[:\-–—]\s*\S",
    re.IGNORECASE,
)
_CHAPTER_PATTERNS = [
    re.compile(r"^\s*CHAPTER\s+(\d{1,3}|[IVXLCDM]{1,7}|[A-Za-z]+)\b", re.IGNORECASE),
]
# A bare Roman numeral heading with no "Chapter"/"Book" label (e.g. Moby-
# Dick's "I. Loomings") — ambiguous which level it is, reported separately
# as [#] so it doesn't get silently mislabeled as a chapter.
_BARE_NUMERAL_PATTERN = re.compile(r"^\s*([IVXLCDM]{1,7})\s*[\.\-–—:]\s+\S")

# Guards against the single biggest false-positive source in real books:
# pdftotext -layout wraps prose to a fixed width, so an in-text cross-
# reference like "...as discussed in Chapter 5, the 1991 Gulf War..." can
# land with "Chapter 5, the 1991 Gulf War..." starting its own line — which
# matches _CHAPTER_PATTERNS just as well as a real "Chapter 5" heading does.
# A real heading's number is followed by nothing, or a colon/dash/period +
# a Title-Case word or digit — never a comma, closing paren, or a lowercase
# word (which is how a wrapped sentence continues, including across an
# em-dash used as sentence punctuation rather than a title separator).
_HEADING_TAIL_OK = re.compile(r"^\s*$|^\s*[:.\-–—]?\s*[A-Z0-9]")


def _is_real_heading_tail(rest: str) -> bool:
    return bool(_HEADING_TAIL_OK.match(rest))


# Back-matter section titles: a "Chapter N" line appearing after one of
# these (near the end of the book) is almost certainly an endnotes divider
# ("Notes ... Chapter 1 ... Chapter 2 ...") rather than a real chapter
# opening — the exact false-positive pattern found in real-world testing.
_BACK_MATTER_TITLES = re.compile(
    r"^\s*(NOTES|ENDNOTES|Notes|Endnotes|BIBLIOGRAPHY|Bibliography|"
    r"INDEX|Index|APPENDIX|Appendix|GLOSSARY|Glossary)\s*$"
)


def find_headings(text: str) -> list[tuple[int, str, str]]:
    """Return [(line_number, level, heading_text), ...] where level is
    'book', 'chapter', 'chapter?' (suspected endnotes divider, found after
    a back-matter section title in the last third of the text), or
    'heading' (an unlabeled numbered heading)."""
    lines = text.splitlines()
    total = len(lines)

    # Locate the first back-matter title in the last third of the text —
    # "Chapter N" hits after that point get demoted to 'chapter?'.
    back_matter_start: int | None = None
    for i in range(max(0, (2 * total) // 3), total):
        if _BACK_MATTER_TITLES.match(lines[i].strip()):
            back_matter_start = i + 1
            break

    hits: list[tuple[int, str, str]] = []
    for i, line in enumerate(lines, start=1):
        s = line.strip()
        if not s or len(s) > 90:
            continue

        m = _BOOK_PATTERN.match(s)
        if m:
            grp = m.group(1) or m.group(2)
            if _numeral_value(grp) is not None:
                hits.append((i, "book", s))
                continue

        matched_chapter = False
        for pat in _CHAPTER_PATTERNS:
            m = pat.match(s)
            if m and _numeral_value(m.group(1)) is not None:
                if _is_real_heading_tail(s[m.end():]):
                    level = ("chapter?" if back_matter_start and i >= back_matter_start
                             else "chapter")
                    hits.append((i, level, s))
                    matched_chapter = True
                break
        if matched_chapter:
            continue

        m = _BARE_NUMERAL_PATTERN.match(s)
        if m and _roman_to_int(m.group(1)) is not None:
            # Reject numbered list items in prose: a real unlabeled heading
            # is a short title line, not the opening of a sentence that
            # runs on. "I. Loomings" is a heading; "I. The war must be
            # fought in the interior of the country." is a list item.
            rest = s[m.end():].strip()
            if len(rest.split()) <= 8 and not rest.endswith((".", ",", ";")):
                hits.append((i, "heading", s))

    return suppress_running_headers(hits, _line_to_page_map(lines))


def build_page_line_map(text: str) -> dict[int, int]:
    """Map page number -> line number of its '--- PAGE N ---' marker, so
    outline entries (which give page numbers) can be reported as line
    numbers usable with sed."""
    mapping: dict[int, int] = {}
    for i, line in enumerate(text.splitlines(), start=1):
        m = re.match(r"^--- PAGE (\d+)", line)
        if m:
            mapping[int(m.group(1))] = i
    return mapping


def _line_to_page_map(lines: list[str]) -> list[int]:
    """For each line index (0-based), the page number it falls on."""
    out: list[int] = []
    current = 0
    for line in lines:
        m = re.match(r"^--- PAGE (\d+)", line)
        if m:
            current = int(m.group(1))
        out.append(current)
    return out


def suppress_running_headers(
    hits: list[tuple[int, str, str]],
    line_pages: list[int],
    window_pages: int = 20,
) -> list[tuple[int, str, str]]:
    """Collapse running-header repeats in a detected-heading list.

    In a printed book, the chapter title is reprinted at the top of every
    page of that chapter ("CHAPTER SIXTEEN" on pp. 227, 228, 229...).
    Header/footer stripping only removes lines repeated across a majority
    of ALL pages, so a header scoped to one chapter or book survives and
    gets indexed once per page — which is what turned Clausewitz's index
    into ~30 copies of "BOOK SIX".

    Rule: drop a heading if the same normalised text was already recorded
    within the previous `window_pages` pages. Genuine reuse across distant
    parts of a book (Book One ch.2 vs Book Five ch.2) is far enough apart
    to survive; page-by-page reprints are not. Normalisation is
    case-insensitive and whitespace-collapsed, so OCR slips like
    'BOOK SIx' still match 'BOOK SIX'."""
    kept: list[tuple[int, str, str]] = []
    last_seen: dict[str, int] = {}
    for line_no, level, text in hits:
        page = line_pages[line_no - 1] if line_no - 1 < len(line_pages) else 0
        key = " ".join(text.split()).upper()
        prev = last_seen.get(key)
        if prev is not None and page - prev <= window_pages:
            last_seen[key] = page  # still a repeat; extend the run
            continue
        last_seen[key] = page
        kept.append((line_no, level, text))
        if level == "book":
            # A new BOOK starts a fresh chapter sequence, so "CHAPTER ONE"
            # opening Book Two is a real heading even if Book One's
            # "CHAPTER ONE" was only a few pages back. Keep the book keys
            # themselves so book running-headers stay suppressed.
            last_seen = {k: v for k, v in last_seen.items()
                         if k.startswith("BOOK")}
    return kept


# ---------------------------------------------------------------------------
# Quality reporting — measured facts about the extraction, for the user
# ---------------------------------------------------------------------------

def compute_quality_report(
    text: str,
    ocr_pages: list[int],
    expected_pages: int,
) -> dict:
    """Measure extraction quality so users know what they're holding.

    Everything here is a measurement of the produced output, not a guess:
    page counts are compared against pdfinfo's authoritative count, and
    OCR pages are known exactly because this script chose them."""
    found_pages = [int(m) for m in
                   re.findall(r"^--- PAGE (\d+)", text, flags=re.MULTILINE)]
    blank_pages = len(re.findall(r"^--- PAGE \d+.*\[BLANK\]", text,
                                 flags=re.MULTILINE))
    # Count real body words only — excluding the '--- PAGE N ---' marker lines,
    # which would otherwise inflate the count (~4-5 tokens/page) and mask a
    # zero-content extraction.
    body_only = re.sub(r"^--- PAGE \d+[^\n]*---$", "", text, flags=re.MULTILINE)
    words = len(body_only.split())

    sequence_ok = found_pages == list(range(1, len(found_pages) + 1))
    page_count_ok = (expected_pages == 0) or (len(found_pages) == expected_pages)
    ocr_pct = (len(ocr_pages) / len(found_pages) * 100) if found_pages else 0.0
    density = (words / len(found_pages)) if found_pages else 0

    return {
        "pages_found": len(found_pages),
        "pages_expected": expected_pages,
        "page_count_ok": page_count_ok,
        "sequence_ok": sequence_ok,
        "blank_pages": blank_pages,
        "ocr_pages": len(ocr_pages),
        "ocr_pct": ocr_pct,
        "words": words,
        "words_per_page": density,
    }


def format_quality_header(report: dict, pdf_name: str,
                          meta: dict | None = None) -> str:
    """Human-readable quality banner written at the top of every output
    file, so anyone who opens it — including someone it was shared with —
    sees the caveats before quoting from it."""
    meta = meta or {"title": "", "author": "", "year": "", "title_rejected": ""}
    lines = [
        "=" * 72,
        f"EXTRACTED TEXT - {pdf_name}",
        "=" * 72,
        "",
    ]

    if meta["title"] or meta["author"] or meta["year"]:
        lines.append("DOCUMENT (from the PDF's own metadata)")
        if meta["title"]:
            lines.append(f"  Title:   {meta['title']}")
        if meta["author"]:
            lines.append(f"  Author:  {meta['author']}")
        if meta["year"]:
            lines.append(f"  File date: {meta['year']}  (when the PDF was made -")
            lines.append("             NOT necessarily the publication year)")
        lines.append("  NOTE: PDF metadata is set by whoever made the file and")
        lines.append("        is often wrong or incomplete. Verify against the")
        lines.append("        title page before citing.")
        lines.append("")
    elif meta["title_rejected"]:
        lines.append("DOCUMENT")
        lines.append(f"  This PDF's metadata title ({meta['title_rejected'][:50]!r})")
        lines.append("  looks like an internal ID, not a real title, so it was")
        lines.append("  ignored. Take the title from the title page below.")
        lines.append("")

    lines += [
        "HOW TO USE THIS FILE",
        "  Page markers ('--- PAGE N ---') correspond to PDF page numbers.",
        "  Pull a range rather than reading the whole file, e.g.:",
        "      grep -n '^--- PAGE 227 ' <thisfile>",
        "  Windows PowerShell:",
        "      Select-String -Path <thisfile> -Pattern '^--- PAGE 227 '",
        "",
        "QUALITY REPORT (measured from this extraction)",
        f"  Pages extracted:      {report['pages_found']}"
        + (f" of {report['pages_expected']} reported by the PDF"
           if report['pages_expected'] else ""),
        "  Page count matches:   " + (
            "COULD NOT VERIFY (no pdfinfo/pypdf)" if not report['pages_expected']
            else ("YES" if report['page_count_ok'] else "NO - SEE WARNINGS")),
        f"  Page order intact:    {'YES' if report['sequence_ok'] else 'NO - SEE WARNINGS'}",
        f"  Blank pages:          {report['blank_pages']}",
        f"  Pages read by OCR:    {report['ocr_pages']} ({report['ocr_pct']:.1f}%)",
        f"  Words extracted:      {report['words']:,} "
        f"({report['words_per_page']:.0f}/page average)",
        "",
    ]

    warnings = []
    if not report["page_count_ok"]:
        warnings.append(
            "  ! Extracted page count does NOT match the PDF's own count.\n"
            "    Pages may be missing. Verify before relying on this file.")
    if not report["sequence_ok"]:
        warnings.append(
            "  ! Page markers are not in strict sequence. Treat page\n"
            "    references in this file as unreliable.")
    if report["ocr_pages"]:
        warnings.append(
            f"  ! {report['ocr_pages']} page(s) had no text layer and were read by OCR.\n"
            "    They are tagged '[OCR]' on their page marker. OCR can misread\n"
            "    characters (real examples: 'SIX'->'SIx', 'II.'->'Il.').\n"
            "    DO NOT quote verbatim from an [OCR] page without checking the\n"
            "    wording against the original PDF page.")
    if report["ocr_pct"] > 50:
        warnings.append(
            "  ! MORE THAN HALF of this document came from OCR. Treat the whole\n"
            "    file as approximate and verify any quotation against the PDF.")
    if report["words_per_page"] < 50 and report["pages_found"] > 5:
        warnings.append(
            "  ! Very low text density. This PDF may be mostly images, or\n"
            "    extraction may have partly failed. Inspect before using.")

    if warnings:
        lines.append("WARNINGS")
        lines.extend(warnings)
        lines.append("")

    lines += [
        "WHAT THIS TOOL DOES AND DOES NOT DO",
        "  This is a deterministic text extractor (pdftotext / pypdf /",
        "  tesseract OCR). It does NOT summarise, paraphrase, or generate",
        "  text, and contains no AI model. It cannot invent content that is",
        "  not in the source PDF. Its failure modes are garbled characters",
        "  (OCR) and omissions - never fabrication. The text below is the",
        "  source document's own words.",
        "",
        "  Applied automatically: running headers/footers and bare page",
        "  numbers removed; words split by a line-break hyphen rejoined",
        "  (which can occasionally merge a genuine hyphenated compound);",
        "  invisible/bidi Unicode characters stripped.",
        "=" * 72,
        "",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Dependency preflight
# ---------------------------------------------------------------------------

def check_dependencies() -> None:
    checks = [
        ("pdftotext", shutil.which("pdftotext") is not None, "poppler-utils", True),
        ("pdftoppm", shutil.which("pdftoppm") is not None, "poppler-utils", True),
        ("pdfinfo", shutil.which("pdfinfo") is not None, "poppler-utils", False),
        ("tesseract", shutil.which("tesseract") is not None, "tesseract-ocr", True),
        ("ImageMagick (magick/convert)", _imagemagick_cmd() is not None, "imagemagick", False),
    ]
    try:
        import pypdf  # noqa: F401
        pypdf_ok = True
    except ImportError:
        pypdf_ok = False
    checks.append(("pypdf (python fallback)", pypdf_ok, 'pip install -r requirements.txt', False))

    print("Dependency check:")
    any_missing_required = False
    for name, ok, install_hint, required in checks:
        status = "OK" if ok else "MISSING"
        tag = "required" if required else "optional"
        print(f"  [{status:7}] {name:26} ({tag})"
              + ("" if ok else f"  ->  install: {install_hint}"))
        if not ok and required:
            any_missing_required = True

    print()
    if any_missing_required:
        print("Some required tools are missing. Text extraction and/or OCR will "
              "not work fully until they're installed.")
        print("Typical fixes:")
        print("  Linux:   sudo apt install poppler-utils tesseract-ocr imagemagick")
        print("  macOS:   brew install poppler tesseract imagemagick")
        print("  Windows: winget install oschwartz10612.Poppler UB-Mannheim.TesseractOCR "
              "ImageMagick.ImageMagick  (then add each bin folder to PATH)")
    else:
        print("All required tools are present. Optional tools improve quality "
              "(ImageMagick deskew) or add a fallback (pypdf) but aren't essential.")


# ---------------------------------------------------------------------------
# Batch input resolution
# ---------------------------------------------------------------------------

def resolve_pdf_inputs(inputs: list[str]) -> list[Path]:
    """Expand a mix of PDF file paths, directories, and glob patterns into a
    deduplicated, sorted list of PDF files.

    A non-glob argument that doesn't exist on disk is a hard error, not a
    silent skip — it's almost always a typo or a leftover from the old
    two-positional-argument syntax (input.pdf output.txt), and silently
    ignoring it can leave the run writing to an unexpected default filename
    with only a buried warning to explain why."""
    import glob as glob_mod

    resolved: list[Path] = []
    for item in inputs:
        expanded = str(Path(item).expanduser())
        p = Path(expanded)
        is_glob = any(ch in expanded for ch in ("*", "?", "["))
        if p.is_dir():
            resolved.extend(sorted(p.rglob("*.pdf")) + sorted(p.rglob("*.PDF")))
        elif is_glob:
            resolved.extend(
                Path(m) for m in sorted(glob_mod.glob(expanded, recursive=True))
                if Path(m).suffix.lower() == ".pdf"
            )
        elif p.is_file():
            resolved.append(p)
        else:
            print(f"Error: input not found: {item}", file=sys.stderr)
            print("  (if this was meant as an output filename, use -o/--out "
                  "or --out-dir instead of a second positional argument)",
                  file=sys.stderr)
            sys.exit(1)

    seen: set[Path] = set()
    unique: list[Path] = []
    for p in resolved:
        rp = p.resolve()
        if rp not in seen:
            seen.add(rp)
            unique.append(p)
    return unique


# ---------------------------------------------------------------------------
# Per-file processing
# ---------------------------------------------------------------------------

def process_one_pdf(pdf_path: Path, out_path: Path, args) -> dict:
    """Run the full pipeline on one PDF. Returns a stats dict."""
    print(f"\n=== {pdf_path.name} ===", file=sys.stderr)
    raw_text, method, ocr_page_nums, expected_pages = extract_text_any(
        str(pdf_path),
        ocr_lang=args.ocr_lang,
        ocr_dpi=args.ocr_dpi,
        ocr_threshold=args.ocr_threshold,
        force_ocr=args.force_ocr,
        deskew=not args.no_deskew,
    )
    print(f"  extractor used: {method}", file=sys.stderr)

    cleaned = clean_and_mark_pages(raw_text, ocr_pages=set(ocr_page_nums))
    sanitized, removed_count = sanitize(cleaned)
    if removed_count:
        print(f"  stripped {removed_count} invisible/bidi/tag characters "
              f"(possible hidden content or PDF artifacts)", file=sys.stderr)

    report = compute_quality_report(sanitized, ocr_page_nums, expected_pages)
    meta = extract_pdf_metadata(str(pdf_path))
    # Metadata is attacker-controllable and lands in the header; run it through
    # the same invisible/bidi stripper as the body so it can't smuggle hidden
    # content past the sanitization the header advertises.
    for _k in ("title", "author"):
        if meta.get(_k):
            meta[_k] = sanitize(meta[_k])[0]

    # Build the header once and reuse it for both the file and the index line
    # offset below. Rebuilding it separately risked the two renders drifting if
    # report/meta were ever mutated between them, silently misaligning every
    # index line number. Empty when --no-header, so the offset is 0.
    header = ("" if getattr(args, "no_header", False)
              else format_quality_header(report, pdf_path.name, meta))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(header + sanitized, encoding="utf-8")

    word_count = report["words"]
    page_count = report["pages_found"]
    print(f"  wrote {out_path}  ({word_count:,} words, {page_count} pages, "
          f"{report['ocr_pages']} OCR'd = {report['ocr_pct']:.1f}%)",
          file=sys.stderr)

    # Surface quality problems on the console too, not just in the file.
    if not report["page_count_ok"]:
        print(f"  ** WARNING: extracted {report['pages_found']} pages but the PDF "
              f"reports {report['pages_expected']} — pages may be missing",
              file=sys.stderr)
    if not report["sequence_ok"]:
        print("  ** WARNING: page markers are not in strict sequence",
              file=sys.stderr)
    if report["ocr_pct"] > 50:
        print(f"  ** WARNING: {report['ocr_pct']:.0f}% of pages came from OCR — "
              f"verify quotations against the PDF", file=sys.stderr)
    if report["words_per_page"] < 50 and report["pages_found"] > 5:
        print("  ** WARNING: very low text density — PDF may be mostly images",
              file=sys.stderr)
    if report["words"] == 0:
        print("  ** WARNING: no text was extracted at all — the PDF may be "
              "corrupt, empty, or unreadable", file=sys.stderr)

    # --- Build the index: embedded PDF outline first, text regex fallback ---
    # The quality header is prepended to the output file, which shifts every
    # line number. Index line numbers MUST match the file as written, or
    # every sed/grep range the user pulls will be wrong. Derive the offset from
    # the exact header string written above so the two can never disagree.
    line_offset = header.count("\n")

    index_path = out_path.with_suffix(out_path.suffix + ".index")
    outline = extract_pdf_outline(str(pdf_path))
    page_lines = {p: ln + line_offset
                  for p, ln in build_page_line_map(sanitized).items()}
    ocr_page_set = set(ocr_page_nums)
    headings_count = 0

    # Map a line number in the text back to its page, so index entries can
    # be flagged when they sit on an OCR'd (less reliable) page.
    line_page_lookup = _line_to_page_map(sanitized.splitlines())

    def _ocr_flag_for_line(text_line_no: int) -> str:
        idx = text_line_no - 1
        if 0 <= idx < len(line_page_lookup):
            return "  [on OCR page]" if line_page_lookup[idx] in ocr_page_set else ""
        return ""

    index_banner = [
        f"INDEX — {pdf_path.name}",
        "=" * 72,
        "Line numbers refer to the .txt file produced alongside this index.",
        "Pull a section with:  sed -n '<start>,<end>p' <file.txt>",
        "  PowerShell:         Get-Content <file.txt> | Select-Object "
        "-Index (<start>..<end>)",
        "",
    ]

    if outline:
        # Authoritative structure from the PDF's own bookmarks.
        index_lines = index_banner + [
            "SOURCE: the PDF's own embedded outline (bookmarks).",
            "  This is the publisher's structure and is reliable.",
            "",
        ]
        for page, depth, title in outline:
            title = sanitize(title)[0]  # outline titles bypass the body sanitize
            line_no = page_lines.get(page)
            loc = f"line {line_no:>7}" if line_no else f"page {page} (no marker)"
            flag = ("  [on OCR page]" if page in ocr_page_set else "")
            index_lines.append(f"{'  ' * depth}[p.{page:>4}] {loc}: {title}{flag}")
        index_path.write_text("\n".join(index_lines) + "\n", encoding="utf-8")
        headings_count = len(outline)
        print(f"  index from embedded PDF outline: {len(outline)} entries "
              f"-> {index_path}", file=sys.stderr)
    else:
        # Fallback: text-pattern detection (BOOK / Chapter N / bare Roman
        # numerals), with suspected endnotes dividers demoted to [CH?].
        headings = find_headings(sanitized)
        headings_count = len(headings)
        if headings:
            index_lines = index_banner + [
                "SOURCE: text-pattern detection. This PDF has NO embedded",
                "outline, so headings were found by matching text patterns.",
                "",
                "  THIS INDEX IS A NAVIGATION AID, NOT AN AUTHORITY.",
                "  Known limits of pattern detection:",
                "    - a book may repeat its title as a running header, so a",
                "      heading can appear more than once (repeats within 20",
                "      pages are already suppressed)",
                "    - chapters whose headings are formatted unusually, or",
                "      garbled by OCR, may be MISSING from this list",
                "    - an in-text cross-reference may occasionally appear here",
                "  Verify against the book's printed table of contents.",
                "",
                "  TAGS: [BOOK] book-level  [CH] chapter  [#] unlabeled heading",
                "        [CH?] sits after a Notes/Index/Bibliography title —",
                "              probably an endnote divider, not a real chapter",
                "",
            ]
            tag_map = {"book": "[BOOK]", "chapter": "[CH]  ",
                       "chapter?": "[CH?] ", "heading": "[#]   "}
            for line_no, level, htext in headings:
                shifted = line_no + line_offset
                index_lines.append(
                    f"{tag_map[level]} line {shifted:>7}: {htext}"
                    f"{_ocr_flag_for_line(line_no)}")
            index_path.write_text("\n".join(index_lines) + "\n", encoding="utf-8")
            book_n = sum(1 for _, lvl, _ in headings if lvl == "book")
            ch_n = sum(1 for _, lvl, _ in headings if lvl == "chapter")
            susp_n = sum(1 for _, lvl, _ in headings if lvl == "chapter?")
            other_n = len(headings) - book_n - ch_n - susp_n
            print(f"  no embedded outline; text detection found {book_n} book(s), "
                  f"{ch_n} chapter(s)"
                  + (f", {susp_n} suspected endnote divider(s)" if susp_n else "")
                  + (f", {other_n} unlabeled heading(s)" if other_n else "")
                  + f" -> {index_path}", file=sys.stderr)
        else:
            index_path.write_text(
                "\n".join(index_banner) +
                f"\nNo embedded PDF outline, and no BOOK/CHAPTER headings were\n"
                f"detected by pattern matching in {pdf_path.name}.\n\n"
                f"This is normal for books whose chapters are titled without the\n"
                f"word 'Chapter' (e.g. '1 The Dragon and the Snakes').\n"
                f"Navigate by page marker instead:\n"
                f"  grep -n '^--- PAGE' <file.txt>\n",
                encoding="utf-8",
            )
            print(f"  no embedded outline and no headings auto-detected "
                  f"-> {index_path}", file=sys.stderr)

    return {
        "pdf": pdf_path, "out": out_path, "words": word_count,
        "pages": page_count, "ocr_pages": len(ocr_page_nums),
        "headings": headings_count,
        "page_count_ok": report["page_count_ok"],
        "sequence_ok": report["sequence_ok"],
        "ocr_pct": report["ocr_pct"],
        "words_per_page": report["words_per_page"],
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract + clean + OCR PDF book(s) into grep-able .txt files.",
        add_help=True,
    )
    parser.add_argument("inputs", nargs="*",
                         help="PDF file(s), a folder, or a glob pattern (quote globs)")
    parser.add_argument("-o", "--out", default=None,
                         help="explicit output path (single-file mode only)")
    parser.add_argument("--out-dir", default=None,
                         help="write all outputs into this directory (batch mode)")
    parser.add_argument("--overwrite", action="store_true",
                         help="reprocess even if a matching .txt already exists")
    parser.add_argument("--force-ocr", action="store_true",
                         help="OCR every page regardless of extracted text")
    parser.add_argument("--ocr-lang", default="eng",
                         help='tesseract language code, default "eng"')
    parser.add_argument("--ocr-dpi", type=int, default=300,
                         help="OCR render resolution, default 300")
    parser.add_argument("--ocr-threshold", type=int, default=8,
                         help="pages with fewer extracted words than this are OCR'd, default 8")
    parser.add_argument("--no-deskew", action="store_true",
                         help="skip the deskew/contrast pass before OCR")
    parser.add_argument("--no-header", action="store_true",
                         help="omit the quality-report header from output files "
                              "(raw extracted text only)")
    parser.add_argument("--name-from-metadata", action="store_true",
                         help="name output files 'Author - Title (Year)' using "
                              "the PDF's metadata, falling back to the original "
                              "filename when metadata is missing or unusable")
    parser.add_argument("--preview-names", action="store_true",
                         help="show what --name-from-metadata would produce, "
                              "then exit without processing anything")
    parser.add_argument("--check", action="store_true",
                         help="report which required/optional tools are installed and exit")
    parser.add_argument("--dry-run", action="store_true",
                         help="resolve inputs and output paths, report what would be "
                              "processed, but write no files")
    args = parser.parse_args()

    if args.check:
        check_dependencies()
        return

    if not args.inputs:
        parser.error("at least one PDF path, folder, or glob is required "
                      "(or use --check)")

    pdf_files = resolve_pdf_inputs(args.inputs)
    if not pdf_files:
        print("No PDF files found among the given input(s).", file=sys.stderr)
        sys.exit(1)

    if args.out and len(pdf_files) > 1:
        parser.error("-o/--out only works with a single PDF; "
                      "use --out-dir for batches")

    print(f"Found {len(pdf_files)} PDF file(s) to process.", file=sys.stderr)

    # --- Resolve output stems, optionally from PDF metadata ---------------
    def resolve_stem(pdf: Path) -> tuple[str, str]:
        if not (args.name_from_metadata or args.preview_names):
            return pdf.stem, ""
        meta = extract_pdf_metadata(str(pdf))
        return build_metadata_filename(meta, pdf.stem)

    if args.preview_names:
        print("\nPreview of --name-from-metadata output names:\n", file=sys.stderr)
        used_preview: dict[str, int] = {}
        for pdf in pdf_files:
            stem, why = resolve_stem(pdf)
            count = used_preview.get(stem.lower(), 0)
            used_preview[stem.lower()] = count + 1
            shown = stem if count == 0 else f"{stem} ({count + 1})"
            print(f"  {pdf.name}", file=sys.stderr)
            print(f"    -> {shown}.txt"
                  + (f"   [kept original: {why}]" if why else "   [from metadata]"),
                  file=sys.stderr)
        print("\nNothing was processed. Re-run without --preview-names to go ahead.",
              file=sys.stderr)
        return

    results = []
    skipped = []
    dry_run_plan: list[tuple[Path, Path, str]] = []  # (pdf, out_path, action)
    used_stems: dict[str, int] = {}
    for pdf_path in pdf_files:
        stem, why = resolve_stem(pdf_path)
        # Two different PDFs can yield the same metadata name (e.g. two
        # volumes sharing a title). Never let one silently overwrite the
        # other — disambiguate with a counter.
        seen_count = used_stems.get(stem.lower(), 0)
        used_stems[stem.lower()] = seen_count + 1
        if seen_count:
            stem = f"{stem} ({seen_count + 1})"

        if args.out:
            out_path = Path(args.out)
        elif args.out_dir:
            out_path = Path(args.out_dir) / (stem + ".txt")
        else:
            out_path = pdf_path.with_name(stem + ".txt")

        # Never write over the source PDF — the tool promises it only reads them.
        if out_path.resolve() == pdf_path.resolve():
            action = "error: would overwrite source PDF"
            if args.dry_run:
                dry_run_plan.append((pdf_path, out_path, action))
                continue
            print(f"\n=== {pdf_path.name} ===", file=sys.stderr)
            print("  [error] refusing to write output over the source PDF; "
                  "choose a different -o/--out-dir path", file=sys.stderr)
            continue

        if args.name_from_metadata and stem != pdf_path.stem:
            if not args.dry_run:
                print(f"\n=== {pdf_path.name} ===", file=sys.stderr)
                print(f"  naming from metadata -> {stem}.txt", file=sys.stderr)

        if out_path.exists() and not args.overwrite:
            action = "skip: output already exists"
            if args.dry_run:
                dry_run_plan.append((pdf_path, out_path, action))
                continue
            print(f"\n=== {pdf_path.name} ===", file=sys.stderr)
            print(f"  skipping — {out_path} already exists (use --overwrite to redo)",
                  file=sys.stderr)
            skipped.append(pdf_path)
            continue

        if args.dry_run:
            dry_run_plan.append((pdf_path, out_path, "process"))
            continue

        try:
            results.append(process_one_pdf(pdf_path, out_path, args))
        except Exception as e:
            print(f"  [error] failed on {pdf_path.name}: {type(e).__name__}: {e}",
                  file=sys.stderr)

    if args.dry_run:
        print(f"\n=== DRY RUN - no files written ===", file=sys.stderr)
        process_count = sum(1 for _, _, a in dry_run_plan if a == "process")
        skip_count = sum(1 for _, _, a in dry_run_plan if a.startswith("skip"))
        error_count = sum(1 for _, _, a in dry_run_plan if a.startswith("error"))
        for pdf_path, out_path, action in dry_run_plan:
            print(f"\n=== {pdf_path.name} ===", file=sys.stderr)
            print(f"  action: {action}", file=sys.stderr)
            print(f"  output: {out_path}", file=sys.stderr)
        print(f"\nWould process: {process_count}   skip: {skip_count}   "
              f"error: {error_count}", file=sys.stderr)
        return

    failed = len(pdf_files) - len(results) - len(skipped)
    print(f"\n=== Summary ===", file=sys.stderr)
    print(f"  processed: {len(results)}   skipped: {len(skipped)}   "
          f"failed: {failed}", file=sys.stderr)
    for r in results:
        flags = []
        if not r.get("page_count_ok", True):
            flags.append("PAGE COUNT MISMATCH")
        if not r.get("sequence_ok", True):
            flags.append("PAGE ORDER BROKEN")
        if r.get("ocr_pct", 0) > 50:
            flags.append(f"{r['ocr_pct']:.0f}% OCR")
        if r.get("words_per_page", 999) < 50 and r["pages"] > 5:
            flags.append("LOW TEXT DENSITY")
        flag_str = ("   ** " + "; ".join(flags)) if flags else ""
        print(f"    {r['pdf'].name}: {r['pages']} pages "
              f"({r['ocr_pages']} OCR'd), {r['headings']} headings "
              f"-> {r['out']}{flag_str}", file=sys.stderr)

    flagged = [r for r in results
               if not r.get("page_count_ok", True)
               or not r.get("sequence_ok", True)
               or r.get("ocr_pct", 0) > 50
               or r.get("words", 1) == 0]
    if flagged:
        print(f"\n  {len(flagged)} file(s) flagged above need a closer look — "
              f"see the QUALITY REPORT at the top of each .txt file.",
              file=sys.stderr)

    if results:
        sample = results[0]["out"]
        print(f"\nTo pull a range instead of re-ingesting a whole file:", file=sys.stderr)
        print(f"    cat {sample}.index                              # book/chapter index", file=sys.stderr)
        print(f"    grep -n '^--- PAGE' {sample} | head -40", file=sys.stderr)
        print(f"    sed -n '<start_line>,<end_line>p' {sample}", file=sys.stderr)

    # Non-zero exit if any file hard-failed OR produced no text at all, so a
    # corrupt/empty PDF that "processed" without an exception still signals
    # failure to launchers and CI.
    empty = [r for r in results if r.get("words", 1) == 0]
    if failed or empty:
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except BrokenPipeError:
        # Output was piped into something that closed early (e.g. `| head`).
        # Exit quietly rather than dumping a traceback at the user.
        try:
            sys.stdout.close()
        except Exception:
            pass
        sys.exit(0)
    except KeyboardInterrupt:
        print("\nInterrupted. Partial output files may be incomplete.",
              file=sys.stderr)
        sys.exit(130)
