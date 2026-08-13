"""Page validation module."""

from __future__ import annotations

import re


def validate_page_sequence(text: str) -> tuple[bool, list[int], list[int]]:
    """Validate that page markers are in strict sequence.

    Returns:
        (is_valid, found_pages, missing_pages)
    """
    found_pages = [int(m) for m in
                   re.findall(r"^--- PAGE (\d+)", text, flags=re.MULTILINE)]
    expected = list(range(1, len(found_pages) + 1))
    missing = [p for p in expected if p not in found_pages]
    out_of_sequence = [p for i, p in enumerate(found_pages) if p != i + 1]
    return (len(missing) == 0 and len(out_of_sequence) == 0), found_pages, missing
