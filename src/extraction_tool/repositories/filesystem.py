"""Filesystem repository for PDF and text file operations."""

import contextlib
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


class FilesystemRepository:
    """Handles PDF and text file operations on the local filesystem.

    This repository is responsible for:
    - Resolving PDF inputs from paths, directories, and globs
    - Counting PDF pages via pdfinfo/pypdf
    - Extracting text via pdftotext/pypdf
    - Atomic writes for output files
    - Reading/writing metadata and index files
    """

    def __init__(self, out_dir: str | None = None) -> None:
        """Initialize the filesystem repository.

        Args:
            out_dir: Default output directory for extracted text.
        """
        self._out_dir = Path(out_dir) if out_dir else None

    async def get(self, key: str) -> Any:
        """Not used for filesystem repository."""
        raise NotImplementedError("FilesystemRepository does not support get()")

    async def save(self, key: str, value: Any) -> None:
        """Not used for filesystem repository."""
        raise NotImplementedError("FilesystemRepository does not support save()")

    async def delete(self, key: str) -> None:
        """Not used for filesystem repository."""
        raise NotImplementedError("FilesystemRepository does not support delete()")

    async def list_all(self) -> dict[str, Any]:
        """Not used for filesystem repository."""
        raise NotImplementedError("FilesystemRepository does not support list_all()")

    def resolve_pdf_inputs(self, inputs: list[str]) -> list[Path]:
        """Expand a mix of PDF file paths, directories, and glob patterns.

        Returns a deduplicated, sorted list of PDF files.
        """
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

    def count_pages(self, pdf_path: str) -> int:
        """Count pages in a PDF using pdfinfo or pypdf."""
        if shutil.which("pdfinfo"):
            try:
                result = subprocess.run(
                    ["pdfinfo", pdf_path], capture_output=True, text=True, timeout=30,
                )
                for line in result.stdout.splitlines():
                    if line.startswith("Pages:"):
                        return int(line.split(":")[1].strip())
            except Exception as e:
                print(
                    f"  [debug] pdfinfo failed for {pdf_path}, falling back to "
                    f"pypdf: {type(e).__name__}: {e}", file=sys.stderr)
        try:
            import pypdf
            with open(pdf_path, "rb") as f:
                return len(pypdf.PdfReader(f).pages)
        except Exception:
            return 0

    def extract_pages_pdftotext(
        self, pdf_path: str, total_pages: int
    ) -> list[str] | None:
        """Extract text per page via pdftotext -layout."""
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
                if total_pages:
                    while len(pages) > total_pages and not pages[-1].strip():
                        pages.pop()
                else:
                    while pages and not pages[-1].strip():
                        pages.pop()
                return pages
        except Exception as e:
            print(
                f"  [warn] pdftotext failed: {type(e).__name__}: {e}",
                file=sys.stderr,
            )
        return None

    def extract_pages_pypdf(self, pdf_path: str) -> list[str] | None:
        """Extract text per page via pypdf."""
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
            print(
                f"  [warn] pypdf failed: {type(e).__name__}: {e}",
                file=sys.stderr,
            )
            return None

    def extract_pages_any(
        self, pdf_path: str, total_pages: int
    ) -> tuple[list[str], str]:
        """Try each non-OCR extractor in order."""
        pages = self.extract_pages_pdftotext(pdf_path, total_pages)
        if pages:
            return pages, "pdftotext -layout"
        pages = self.extract_pages_pypdf(pdf_path)
        if pages:
            return pages, "pypdf"
        print("  [warn] no text-layer extractor available or succeeded — "
              "every page will need OCR", file=sys.stderr)
        return [""] * max(total_pages, 1), "none (OCR required for all pages)"

    def atomic_write_text(self, path: Path, text: str, encoding: str = "utf-8") -> None:
        """Write text atomically via a temporary sibling file."""
        tmp = path.with_suffix(path.suffix + ".tmp")
        try:
            tmp.write_text(text, encoding=encoding)
            tmp.replace(path)
        except Exception:
            with contextlib.suppress(Exception):
                tmp.unlink(missing_ok=True)
            raise

    def atomic_write_bytes(self, path: Path, data: bytes) -> None:
        """Write bytes atomically via a temporary sibling file."""
        tmp = path.with_suffix(path.suffix + ".tmp")
        try:
            tmp.write_bytes(data)
            tmp.replace(path)
        except Exception:
            with contextlib.suppress(Exception):
                tmp.unlink(missing_ok=True)
            raise

    def extract_pdf_metadata(self, pdf_path: str) -> dict[str, str]:
        """Read Title/Author/year from a PDF's metadata."""
        result: dict[str, str] = {
            "title": "", "author": "", "year": "", "title_rejected": ""
        }
        try:
            import pypdf
        except ImportError:
            return result
        try:
            meta: dict[str, Any] = pypdf.PdfReader(pdf_path).metadata or {}
        except Exception:
            return result

        raw_title = self._clean_meta_string(meta.get("/Title"))
        if raw_title:
            if self._title_is_usable(raw_title):
                result["title"] = raw_title
            elif not re.match(r"^untitled\s*$", raw_title, re.IGNORECASE):
                result["title_rejected"] = raw_title

        author = self._clean_meta_string(meta.get("/Author"))
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

    def _clean_meta_string(self, value: Any) -> str:
        if value is None:
            return ""
        text = " ".join(str(value).split())
        return text.strip(" ;,·|-")

    def _title_is_usable(self, title: str) -> bool:
        if not title or len(title) < 4 or len(title) > 200:
            return False
        junk_patterns = [
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
        if any(p.search(title) for p in junk_patterns):
            return False
        words = [w for w in re.split(r"\s+", title) if re.search(r"[A-Za-z]", w)]
        return len(words) >= 2

    def extract_pdf_outline(self, pdf_path: str) -> list[tuple[int, int, str]]:
        """Read the PDF's embedded outline (bookmarks) via pypdf."""
        try:
            import pypdf
        except ImportError:
            return []
        entries: list[tuple[int, int, str]] = []
        try:
            reader = pypdf.PdfReader(pdf_path)

            def walk(items: Any, depth: int = 0) -> None:
                for it in items:
                    if isinstance(it, list):
                        walk(it, depth + 1)
                        continue
                    try:
                        page_num = reader.get_destination_page_number(it)
                        page = (page_num or 0) + 1
                    except Exception as e:
                        print(f"  [debug] skipped malformed outline item: "
                              f"{type(e).__name__}: {e}", file=sys.stderr)
                        continue
                    title = " ".join(str(it.title).split())
                    if title:
                        entries.append((page, depth, title))

            walk(reader.outline)
        except Exception as e:
            print(f"  [warn] could not read PDF outline: {type(e).__name__}: {e}",
                  file=sys.stderr)
            return []
        entries.sort(key=lambda t: (t[0], t[1]))
        return entries
