"""Extraction-specific contract models."""


from pydantic import BaseModel, ConfigDict, Field


class ExtractionRequest(BaseModel):
    """Request to extract text from a PDF."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "pdf_path": "/data/clausewitz.pdf",
                "ocr_lang": "eng",
                "ocr_dpi": 300,
                "ocr_threshold": 8,
                "force_ocr": False,
                "no_deskew": False,
            }
        }
    )

    pdf_path: str = Field(..., description="Path to the PDF file")
    ocr_lang: str = Field("eng", description="Tesseract language code")
    ocr_dpi: int = Field(300, ge=72, le=600, description="OCR render resolution")
    ocr_threshold: int = Field(
        8, ge=0, description="Word-count threshold for OCR fallback"
    )
    force_ocr: bool = Field(
        False, description="OCR every page regardless of text layer"
    )
    no_deskew: bool = Field(
        False, description="Skip deskew before OCR"
    )


class ExtractionResult(BaseModel):
    """Result of a PDF extraction operation."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "success": True,
                "text": "--- PAGE 1 ---\nContent...",
                "pages_found": 743,
                "pages_expected": 743,
                "page_count_ok": True,
                "sequence_ok": True,
                "ocr_pages": 0,
                "ocr_pct": 0.0,
                "words": 450000,
                "words_per_page": 605.0,
                "method": "pdftotext -layout",
                "errors": [],
            }
        }
    )

    success: bool = Field(..., description="Whether extraction succeeded")
    text: str = Field("", description="Extracted text with page markers")
    pages_found: int = Field(0, description="Number of pages extracted")
    pages_expected: int = Field(0, description="Expected page count from PDF metadata")
    page_count_ok: bool = Field(
        False, description="Whether observed count matches expected"
    )
    sequence_ok: bool = Field(
        False, description="Whether page markers are in sequence"
    )
    ocr_pages: int = Field(0, description="Number of pages read by OCR")
    ocr_pct: float = Field(0.0, description="Percentage of pages read by OCR")
    words: int = Field(0, description="Total word count")
    words_per_page: float = Field(0.0, description="Average words per page")
    method: str = Field("", description="Extraction method(s) used")
    errors: list[str] = Field(default_factory=list, description="Extraction errors")


class PageValidationResult(BaseModel):
    """Result of validating extracted page markers."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "valid": True,
                "found_pages": [1, 2, 3],
                "missing_pages": [],
                "out_of_sequence": [],
            }
        }
    )

    valid: bool = Field(..., description="Whether page sequence is valid")
    found_pages: list[int] = Field(
        default_factory=list, description="Page numbers found"
    )
    missing_pages: list[int] = Field(
        default_factory=list, description="Missing page numbers"
    )
    out_of_sequence: list[int] = Field(
        default_factory=list, description="Pages out of sequence"
    )


class OcrDetectionResult(BaseModel):
    """Result of OCR detection for a page."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "needs_ocr": True,
                "word_count": 3,
                "threshold": 8,
            }
        }
    )

    needs_ocr: bool = Field(..., description="Whether the page needs OCR")
    word_count: int = Field(0, description="Word count of extracted text")
    threshold: int = Field(8, description="OCR threshold used")
