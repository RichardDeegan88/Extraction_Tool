"""Text normalization module.

Handles cleaning, sanitization, heading detection, quality reporting,
metadata extraction, and filename building.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from extraction_tool.contracts.results import (
    DocumentMetadata,
    HeadingEntry,
    QualityReport,
)

_PDF_PAGE_NUM = re.compile(
    r"^\s*(?:\d{1,4}|"
    r"(?=[ivxlcdm])m{0,4}(?:cm|cd|d?c{0,3})(?:xc|xl|l?x{0,3})(?:ix|iv|v?i{0,3}))"
    r"\s*$",
    re.IGNORECASE)
_PDF_HYPHEN_WRAP = re.compile(r"([^\W\d_])-\n([^\W\d_])")
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
_BOOK_PATTERN = re.compile(
    r"^\s*BOOK\s+([A-Za-z]+|\d{1,3}|[IVXLCDM]{1,7})\b\.?\s*$|"
    r"^\s*BOOK\s+([A-Za-z]+|\d{1,3}|[IVXLCDM]{1,7})\s*[:\-–—]\s*\S",
    re.IGNORECASE,
)
_CHAPTER_PATTERNS = [
    re.compile(r"^\s*CHAPTER\s+(\d{1,3}|[IVXLCDM]{1,7}|[A-Za-z]+)\b", re.IGNORECASE),
]
_BARE_NUMERAL_PATTERN = re.compile(r"^\s*([IVXLCDM]{1,7})\s*[\.\-–—:]\s+\S")
_HEADING_TAIL_OK = re.compile(r"^\s*$|^\s*[:.\-–—]?\s*[A-Z0-9]")
_BACK_MATTER_TITLES = re.compile(
    r"^\s*(NOTES|ENDNOTES|Notes|Endnotes|BIBLIOGRAPHY|Bibliography|"
    r"INDEX|Index|APPENDIX|Appendix|GLOSSARY|Glossary)\s*$"
)
_JUNK_TITLE_PATTERNS = [
    re.compile(r"^\s*$"),
    re.compile(r"^untitled", re.IGNORECASE),
    re.compile(r"^(microsoft )?word[ \-_]", re.IGNORECASE),
    re.compile(r"^document\d*$", re.IGNORECASE),
    re.compile(r"\.(docx?|pdf|indd|qxd|tex|pages|rtf|txt)\s*$", re.IGNORECASE),
    re.compile(r"^imageitem", re.IGNORECASE),
    re.compile(r"^[0-9\-#_ ]+$"),
    re.compile(r"^[0-9a-f]{16,}$", re.IGNORECASE),
    re.compile(r"#_#"),
    re.compile(r"^\d{9,13}$"),
    re.compile(r"^print$|^layout$|^cover$|^final$", re.IGNORECASE),
]
_UNSAFE_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}
_ROMAN_VALUES = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
_WORD_NUMBERS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
    "twenty": 20, "first": 1, "second": 2, "third": 3, "fourth": 4,
    "fifth": 5, "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10,
}


def sanitize(text: str) -> tuple[str, int]:
    """Strip invisible/bidi/tag-block characters."""
    kept, removed = [], 0
    for ch in text:
        cp = ord(ch)
        if cp in _INVISIBLE_CODEPOINTS or _TAG_BLOCK_START <= cp <= _TAG_BLOCK_END:
            removed += 1
            continue
        kept.append(ch)
    return "".join(kept), removed


def clean_and_mark_pages(text: str, ocr_pages: set[int] | None = None) -> str:
    """Split on form-feed page breaks, drop boilerplate, rejoin hyphen-wrapped words."""
    ocr_pages = ocr_pages or set()
    pages = text.split("\f")

    if len(pages) >= 3:
        edge: Counter[str] = Counter()
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
            if i in (first, last) and (s in boiler or _PDF_PAGE_NUM.match(s)):
                continue
            kept.append(ln)
        tag = " [OCR]" if page_num in ocr_pages else ""
        blank_tag = " [BLANK]" if not any(ln.strip() for ln in kept) else ""
        out_lines.append(f"--- PAGE {page_num}{tag}{blank_tag} ---")
        out_lines.append("\n".join(kept))

    joined = "\n".join(out_lines)
    return _PDF_HYPHEN_WRAP.sub(r"\1\2", joined)


def _clean_meta_string(value: Any) -> str:
    if value is None:
        return ""
    text = " ".join(str(value).split())
    return text.strip(" ;,·|-")


def _title_is_usable(title: str) -> bool:
    if not title or len(title) < 4 or len(title) > 200:
        return False
    if any(p.search(title) for p in _JUNK_TITLE_PATTERNS):
        return False
    words = [w for w in re.split(r"\s+", title) if re.search(r"[A-Za-z]", w)]
    return len(words) >= 2


_AUTHOR_SUFFIX_RE = re.compile(
    r"^(jr|sr|ii|iii|iv|v|vi|vii|viii|ix|x|phd|md|esq|jd|rn|cpa)\.?$",
    re.IGNORECASE,
)


def _normalize_author_for_filename(author: str) -> str:
    if not author or " and " in author.lower():
        return author
    parts = [p.strip() for p in author.split(",")]
    if len(parts) == 2:
        last, first = parts
        if last and first:
            return f"{first} {last}"
    if len(parts) == 3:
        last, middle, first = parts
        if last and first and _AUTHOR_SUFFIX_RE.match(middle):
            return f"{first} {last}, {middle}"
    return author


def build_metadata_filename(meta: DocumentMetadata | dict[str, str], fallback_stem: str,
                            max_len: int = 120) -> tuple[str, str]:
    """Build 'Author - Title (Year)' from metadata."""
    if isinstance(meta, dict):
        title = meta.get("title", "")
        author = meta.get("author", "")
        year = meta.get("year", "")
        title_rejected = meta.get("title_rejected", "")
    else:
        title, author, year = meta.title, meta.author, meta.year
        title_rejected = meta.title_rejected

    if not title:
        why = (f"PDF's title field was not a real title "
               f"({title_rejected[:40]!r})" if title_rejected
               else "PDF has no title in its metadata")
        return fallback_stem, why

    parts = []
    if author:
        author = _normalize_author_for_filename(author)
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
    token = token.strip().rstrip(".:")
    if token.isdigit():
        return int(token)
    roman = _roman_to_int(token)
    if roman is not None:
        return roman
    return _WORD_NUMBERS.get(token.lower())


def _is_real_heading_tail(rest: str) -> bool:
    return bool(_HEADING_TAIL_OK.match(rest))


def find_headings(text: str) -> list[HeadingEntry]:
    """Return HeadingEntry list for detected book/chapter headings."""
    lines = text.splitlines()
    total = len(lines)

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
            rest = s[m.end():].strip()
            if len(rest.split()) <= 8 and not rest.endswith((".", ",", ";")):
                hits.append((i, "heading", s))

    suppressed = suppress_running_headers(hits, _line_to_page_map(lines))
    return [
        HeadingEntry(line_number=ln, level=lvl, text=txt)
        for ln, lvl, txt in suppressed
    ]


def suppress_running_headers(
    hits: list[tuple[int, str, str]],
    line_pages: list[int],
    window_pages: int = 20,
) -> list[tuple[int, str, str]]:
    """Collapse running-header repeats in a detected-heading list."""
    kept: list[tuple[int, str, str]] = []
    last_seen: dict[str, int] = {}
    for line_no, level, text in hits:
        page = line_pages[line_no - 1] if line_no - 1 < len(line_pages) else 0
        key = " ".join(text.split()).upper()
        prev = last_seen.get(key)
        if prev is not None and page - prev <= window_pages:
            last_seen[key] = page
            continue
        last_seen[key] = page
        kept.append((line_no, level, text))
        if level == "book":
            last_seen = {k: v for k, v in last_seen.items()
                         if k.startswith("BOOK")}
    return kept


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


def build_page_line_map(text: str) -> dict[int, int]:
    """Map page number -> line number of its '--- PAGE N ---' marker."""
    mapping: dict[int, int] = {}
    for i, line in enumerate(text.splitlines(), start=1):
        m = re.match(r"^--- PAGE (\d+)", line)
        if m:
            mapping[int(m.group(1))] = i
    return mapping


def compute_quality_report(
    text: str, ocr_pages: list[int], expected_pages: int
) -> QualityReport:
    """Measure extraction quality."""
    found_pages = [int(m) for m in
                   re.findall(r"^--- PAGE (\d+)", text, flags=re.MULTILINE)]
    blank_pages = len(re.findall(r"^--- PAGE \d+.*\[BLANK\]", text,
                                 flags=re.MULTILINE))
    body_only = re.sub(r"^--- PAGE \d+[^\n]*---$", "", text, flags=re.MULTILINE)
    words = len(body_only.split())

    sequence_ok = found_pages == list(range(1, len(found_pages) + 1))
    page_count_ok = (expected_pages == 0) or (len(found_pages) == expected_pages)
    ocr_pct = (len(ocr_pages) / len(found_pages) * 100) if found_pages else 0.0
    density = (words / len(found_pages)) if found_pages else 0

    return QualityReport(
        pages_found=len(found_pages),
        pages_expected=expected_pages,
        page_count_ok=page_count_ok,
        sequence_ok=sequence_ok,
        blank_pages=blank_pages,
        ocr_pages=len(ocr_pages),
        ocr_pct=ocr_pct,
        words=words,
        words_per_page=density,
    )


def format_quality_header(report: QualityReport, pdf_name: str,
                          meta: DocumentMetadata | None = None) -> str:
    """Human-readable quality banner written at the top of every output file."""
    meta = meta or DocumentMetadata()
    lines = [
        "=" * 72,
        f"EXTRACTED TEXT - {pdf_name}",
        "=" * 72,
        "",
    ]

    if meta.title or meta.author or meta.year:
        lines.append("DOCUMENT (from the PDF's own metadata)")
        if meta.title:
            lines.append(f"  Title:   {meta.title}")
        if meta.author:
            lines.append(f"  Author:  {meta.author}")
        if meta.year:
            lines.append(f"  File date: {meta.year}  (when the PDF was made -")
            lines.append("             NOT necessarily the publication year)")
        lines.append("  NOTE: PDF metadata is set by whoever made the file and")
        lines.append("        is often wrong or incomplete. Verify against the")
        lines.append("        title page before citing.")
        lines.append("")
    elif meta.title_rejected:
        lines.append("DOCUMENT")
        lines.append(f"  This PDF's metadata title ({meta.title_rejected[:50]!r})")
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
        f"  Pages extracted:      {report.pages_found}"
        + (
            f" of {report.pages_expected} reported by the PDF"
            if report.pages_expected else ""
        ),
        "  Page count matches:   " + (
            "COULD NOT VERIFY (no pdfinfo/pypdf)" if not report.pages_expected
            else ("YES" if report.page_count_ok else "NO - SEE WARNINGS")),
        f"  Page order intact:    "
        f"{'YES' if report.sequence_ok else 'NO - SEE WARNINGS'}",
        f"  Blank pages:          {report.blank_pages}",
        f"  Pages read by OCR:    {report.ocr_pages} ({report.ocr_pct:.1f}%)",
        f"  Words extracted:      {report.words:,} "
        f"({report.words_per_page:.0f}/page average)",
        "",
    ]

    warnings = []
    if not report.page_count_ok:
        warnings.append(
            "  ! Extracted page count does NOT match the PDF's own count.\n"
            "    Pages may be missing. Verify before relying on this file.")
    if not report.sequence_ok:
        warnings.append(
            "  ! Page markers are not in strict sequence. Treat page\n"
            "    references in this file as unreliable.")
    if report.ocr_pages:
        warnings.append(
            f"  ! {report.ocr_pages} page(s) had no text layer and were read by OCR.\n"
            "    They are tagged '[OCR]' on their page marker. OCR can misread\n"
            "    characters (real examples: 'SIX'->'SIx', 'II.'->'Il.').\n"
            "    DO NOT quote verbatim from an [OCR] page without checking the\n"
            "    wording against the original PDF page.")
    if report.ocr_pct > 50:
        warnings.append(
            "  ! MORE THAN HALF of this document came from OCR. Treat the whole\n"
            "    file as approximate and verify any quotation against the PDF.")
    if report.words_per_page < 50 and report.pages_found > 5:
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
