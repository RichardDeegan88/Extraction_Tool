"""Reading acquisition contract models."""


from pydantic import BaseModel, ConfigDict, Field


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
            }
        }
    )

    success: bool = Field(..., description="Whether the operation completed")
    fetched: list[str] = Field(
        default_factory=list, description="Successfully fetched file paths"
    )
    manual_capture: list[tuple[str, str]] = Field(
        default_factory=list, description="URLs requiring manual capture and reasons"
    )
    downloaded_pdfs: list[str] = Field(
        default_factory=list, description="Downloaded PDF paths"
    )
    skipped: list[str] = Field(
        default_factory=list, description="Skipped URL/file paths"
    )
    errors: list[str] = Field(default_factory=list, description="Operation errors")


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
