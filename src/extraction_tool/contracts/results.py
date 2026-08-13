"""Result contract models."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class QualityReport(BaseModel):
    """Measured facts about an extraction."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "pages_found": 743,
                "pages_expected": 743,
                "page_count_ok": True,
                "sequence_ok": True,
                "blank_pages": 2,
                "ocr_pages": 0,
                "ocr_pct": 0.0,
                "words": 450000,
                "words_per_page": 605.0,
            }
        }
    )

    pages_found: int = Field(0, description="Number of pages extracted")
    pages_expected: int = Field(
        0, description="Expected page count from PDF metadata"
    )
    page_count_ok: bool = Field(
        False, description="Whether observed count matches expected"
    )
    sequence_ok: bool = Field(
        False, description="Whether page markers are in sequence"
    )
    blank_pages: int = Field(0, description="Number of blank pages")
    ocr_pages: int = Field(0, description="Number of pages read by OCR")
    ocr_pct: float = Field(0.0, description="Percentage of pages read by OCR")
    words: int = Field(0, description="Total word count")
    words_per_page: float = Field(0.0, description="Average words per page")

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)


class DocumentMetadata(BaseModel):
    """PDF document metadata."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "title": "On War",
                "author": "Carl von Clausewitz",
                "year": "1832",
                "title_rejected": "",
            }
        }
    )

    title: str = Field("", description="Document title from PDF metadata")
    author: str = Field("", description="Document author from PDF metadata")
    year: str = Field("", description="Document year from PDF metadata")
    title_rejected: str = Field("", description="Junk title that was rejected")


class HeadingEntry(BaseModel):
    """A detected heading in extracted text."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "line_number": 42,
                "level": "chapter",
                "text": "CHAPTER 1",
            }
        }
    )

    line_number: int = Field(..., description="Line number in extracted text")
    level: str = Field(
        ..., description="Heading level: book, chapter, chapter?, heading"
    )
    text: str = Field(..., description="Heading text")

    def __iter__(self) -> Any:
        return iter((self.line_number, self.level, self.text))


class DependencyCheckResult(BaseModel):
    """Result of a dependency preflight check."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "tool": "pdftotext",
                "status": "OK",
                "required": True,
                "install_hint": "poppler-utils",
            }
        }
    )

    tool: str = Field(..., description="Tool name")
    status: str = Field(..., description="OK or MISSING")
    required: bool = Field(..., description="Whether tool is required")
    install_hint: str = Field("", description="Installation hint if missing")
