# Changelog

All notable changes to this project are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/), and this project adheres to
[Semantic Versioning](https://semver.org/).

## [1.0.0] - 2026-08-08

First public release.

### Added
- `preprocess_pdf.py` — extracts complete, searchable text from large or
  scanned PDFs, with OCR fallback (tesseract) only for pages that need it,
  verified page counts, per-page `--- PAGE N ---` markers, a book/chapter
  index, and a measured quality report at the top of every output file.
- `fetch_readings.py` — reads a syllabus PDF, extracts every reading link
  (including URLs hidden behind anchor text), and fetches open-access
  articles and direct PDFs. Paywalled/proxied readings are routed to
  `MANUAL_CAPTURE.txt` rather than fetched.
- `RUN-ME.bat` / `run-me.sh` — no-command-line launchers for Windows and
  macOS/Linux.
- Documentation: setup, workflow, quality, using-with-AI, paywalled readings,
  and a security/trust guide.

### Tested
- 211 real course PDFs (162 general readings, 49 space module), zero
  extraction failures.
- Reference result: a 30 MB, 743-page scanned edition of Clausewitz's *On War*
  extracted completely — 743 of 743 pages, page order verified, 4.6% of pages
  requiring OCR — against a prior ceiling of roughly 50 pages before an AI
  assistant truncates a whole-file ingest.

### Known limitations
- `RUN-ME.bat` has been exercised on one Windows machine only.
- `fetch_readings.py` has had one full production run.
- Python 3.9 compatibility is reasoned from the code, not tested; verified
  working on 3.14.
- Chapter indexes built by text-pattern matching (rather than from an embedded
  PDF outline) can miss chapters with unusual heading formats and can
  occasionally list a cross-reference. Page markers are always reliable.

[1.0.0]: https://github.com/richarddeegan88/acsc-reading-toolkit/releases/tag/v1.0.0
