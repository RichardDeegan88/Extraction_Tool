"""Reading acquisition contract models."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

RequirementLevel = Literal["required", "recommended", "unknown"]
ReadingCategory = Literal["article", "pdf", "video", "gated"]


class ReadingOccurrence(BaseModel):
    """One place a URL appears in the syllabus."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "source_page": 8,
                "label": None,
                "lesson": None,
                "requirement": "unknown",
            }
        }
    )

    source_page: int | None = Field(
        None, description="Page number in the syllabus PDF"
    )
    label: str | None = Field(
        None, description="Anchor label or title when deterministically available"
    )
    lesson: str | None = Field(
        None, description="Lesson or unit name when deterministically available"
    )
    requirement: RequirementLevel = Field(
        "unknown", description="Required, recommended, or unknown"
    )


class PlannedReading(BaseModel):
    """A unique reading with every syllabus occurrence preserved."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "url": "https://example.com/article",
                "category": "article",
                "occurrences": [
                    {"source_page": 8, "label": None,
                     "lesson": None, "requirement": "unknown"},
                    {"source_page": 15, "label": None,
                     "lesson": None, "requirement": "unknown"},
                ],
            }
        }
    )

    url: str = Field(..., description="The normalised URL")
    category: ReadingCategory = Field(..., description="Category of the reading")
    occurrences: list[ReadingOccurrence] = Field(
        default_factory=list, description="Every syllabus occurrence"
    )


class ReadingPlan(BaseModel):
    """Result of the non-network planning operation."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "category_counts": {
                    "article": 13, "pdf": 10, "gated": 6, "video": 3,
                },
                "total_unique": 32,
                "total_occurrences": 35,
                "entries": [],
            }
        }
    )

    category_counts: dict[str, int] = Field(
        default_factory=dict,
        description="Counts per category",
    )
    total_unique: int = Field(0, description="Number of unique URLs")
    total_occurrences: int = Field(
        0, description="Total URL occurrences across the syllabus"
    )
    entries: list[PlannedReading] = Field(
        default_factory=list, description="Planned readings grouped by URL"
    )


class ManualCaptureEntry(BaseModel):
    """A reading that could not be fetched automatically."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "url": "https://example.com/gated",
                "category": "gated",
                "failure_class": "institutional_login",
                "reason": "subscription or institutional login required",
                "pages": [8, 15],
                "label": None,
            }
        }
    )

    url: str = Field(..., description="The URL")
    category: ReadingCategory = Field(..., description="Category")
    failure_class: str = Field(..., description="Typed failure class")
    reason: str = Field(..., description="Human-readable failure reason")
    pages: list[int] = Field(default_factory=list, description="Syllabus pages")
    label: str | None = Field(None, description="Anchor label when available")


class ReadingRequest(BaseModel):
    """Request to acquire readings from a source."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "source": "syllabus.pdf",
                "urls_file": None,
                "out_dir": "readings",
                "include_videos": False,
                "delay": 1.5,
                "timeout": 30,
                "overwrite": False,
                "min_words": 120,
                "use_browser": False,
                "browser_timeout": 30,
                "gated_hosts": [],
            }
        }
    )

    source: str | None = Field(None, description="Path to syllabus PDF")
    urls_file: str | None = Field(None, description="Path to URLs text file")
    out_dir: str = Field("readings", description="Output directory")
    include_videos: bool = Field(
        False, description="Write placeholder notes for videos"
    )
    delay: float = Field(1.5, ge=0, description="Seconds between requests")
    timeout: int = Field(30, ge=1, description="Per-request timeout in seconds")
    overwrite: bool = Field(False, description="Refetch even if output exists")
    min_words: int = Field(120, ge=1, description="Minimum words for successful fetch")
    use_browser: bool = Field(
        False, description="Render article pages in a headless browser (Selenium)"
    )
    browser_timeout: int = Field(
        30, ge=1, description="Headless browser render timeout in seconds"
    )
    gated_hosts: list[str] = Field(
        default_factory=list,
        description="Additional host substrings treated as gated sources",
    )

    @field_validator("gated_hosts")
    @classmethod
    def _reject_empty_gated_hosts(cls, values: list[str]) -> list[str]:
        """Empty substrings would match every host; reject them."""
        for value in values:
            if not value.strip():
                raise ValueError("gated_hosts entries must be non-empty strings")
        return values


class ReadingResult(BaseModel):
    """Result of a reading acquisition operation."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "success": True,
                "fetched": ["readings/article1.txt"],
                "manual_capture": [],
                "downloaded_pdfs": [],
                "skipped": [],
                "errors": [],
                "discovered": 1,
                "fetched_count": 1,
                "downloaded_pdfs_count": 0,
                "skipped_count": 0,
                "manual_count": 0,
                "videos_count": 0,
                "unexpected_errors": 0,
            }
        }
    )

    success: bool = Field(..., description="Whether the operation completed")
    fetched: list[str] = Field(
        default_factory=list, description="Successfully fetched file paths"
    )
    manual_capture: list[ManualCaptureEntry] = Field(
        default_factory=list,
        description="Readings requiring manual capture",
    )
    downloaded_pdfs: list[str] = Field(
        default_factory=list, description="Downloaded PDF paths"
    )
    skipped: list[str] = Field(
        default_factory=list, description="Skipped URL/file paths"
    )
    errors: list[str] = Field(default_factory=list, description="Operation errors")
    discovered: int = Field(0, description="Unique URLs discovered")
    fetched_count: int = Field(0, description="Article text files fetched")
    downloaded_pdfs_count: int = Field(0, description="PDFs downloaded")
    skipped_count: int = Field(0, description="Existing outputs skipped")
    manual_count: int = Field(0, description="Readings routed to manual capture")
    videos_count: int = Field(0, description="Video links skipped")
    unexpected_errors: int = Field(0, description="Unexpected failures")


class UrlCategory(BaseModel):
    """A categorized URL from a syllabus."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "url": "https://example.com/article",
                "category": "article",
                "source_page": 5,
            }
        }
    )

    url: str = Field(..., description="The URL")
    category: str = Field(..., description="One of: article, pdf, video, gated")
    source_page: int | None = Field(None, description="Page number in syllabus PDF")
