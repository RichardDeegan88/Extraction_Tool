"""OCR detection module."""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

_WORD_RE = re.compile(r"[^\W\d_]{2,}", re.UNICODE)


def page_needs_ocr(page_text: str, threshold: int) -> bool:
    """Return True if the page has fewer than *threshold* words."""
    return len(_WORD_RE.findall(page_text)) < threshold


def _imagemagick_cmd() -> list[str] | None:
    """Resolve the ImageMagick CLI safely across platforms."""
    magick = shutil.which("magick")
    if magick:
        return [magick]
    convert = shutil.which("convert")
    if convert and "system32" not in convert.lower():
        return [convert]
    return None


def ocr_page(
    pdf_path: str,
    page_num: int,
    dpi: int,
    lang: str,
    workdir: str,
    deskew: bool = True,
) -> str:
    """Render a single page to PNG, optionally deskew, and OCR it."""
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
        except Exception as e:
            print(f"  [debug] deskew skipped for page {page_num}: "
                  f"{type(e).__name__}: {e}", file=sys.stderr)

    result = subprocess.run(
        ["tesseract", img_path, "stdout", "-l", lang],
        capture_output=True, text=True, timeout=120,
        encoding="utf-8", errors="replace",
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"tesseract exited {result.returncode}: "
            f"{(result.stderr or '').strip()[:200]}")
    return result.stdout.replace("\f", "")


def _installed_tesseract_langs() -> list[str]:
    try:
        result = subprocess.run(
            ["tesseract", "--list-langs"],
            capture_output=True, text=True, timeout=30,
            encoding="utf-8", errors="replace",
        )
        if result.returncode != 0:
            return []
        lines = result.stdout.splitlines()
        if lines and lines[0].startswith("List of available languages"):
            lines = lines[1:]
        return [line.strip() for line in lines if line.strip()]
    except Exception:
        return []


def _validate_ocr_lang(
    lang: str, installed_langs_fn: Callable[[], list[str]] | None = None
) -> tuple[bool, list[str]]:
    if installed_langs_fn is None:
        installed_langs_fn = _installed_tesseract_langs
    if not lang:
        return True, []
    installed = set(installed_langs_fn())
    if not installed:
        return True, []
    requested = [
        lang_code.strip()
        for lang_code in lang.split("+") if lang_code.strip()
    ]
    missing = [lang_code for lang_code in requested if lang_code not in installed]
    return not missing, missing


def check_dependencies(ocr_lang: str | None = None) -> None:
    checks = [
        ("pdftotext", shutil.which("pdftotext") is not None, "poppler-utils", True),
        ("pdftoppm", shutil.which("pdftoppm") is not None, "poppler-utils", True),
        ("pdfinfo", shutil.which("pdfinfo") is not None, "poppler-utils", False),
        ("tesseract", shutil.which("tesseract") is not None, "tesseract-ocr", True),
        ("ImageMagick (magick/convert)", _imagemagick_cmd() is not None,
         "imagemagick", False),
    ]
    try:
        import pypdf  # noqa: F401
        pypdf_ok = True
    except ImportError:
        pypdf_ok = False
    checks.append(("pypdf (python fallback)", pypdf_ok, 'pip install pypdf', False))

    print("Dependency check:")
    any_missing_required = False
    for name, ok, install_hint, required in checks:
        status = "OK" if ok else "MISSING"
        tag = "required" if required else "optional"
        print(f"  [{status:7}] {name:26} ({tag})"
              + ("" if ok else f"  ->  install: {install_hint}"))
        if not ok and required:
            any_missing_required = True

    if ocr_lang:
        ok, missing = _validate_ocr_lang(ocr_lang)
        if not ok:
            print(f"  [MISSING] tesseract lang pack(s): {', '.join(missing)}")
            any_missing_required = True

    if any_missing_required:
        print("\nSome required tools are missing. Install them before processing PDFs.")
        sys.exit(1)
    else:
        print("\nAll required tools are present.")
