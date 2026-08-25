# ACSC Reading Toolkit

[![CI](https://github.com/RichardDeegan88/Extraction_Tool/actions/workflows/ci.yml/badge.svg)](https://github.com/RichardDeegan88/Extraction_Tool/actions/workflows/ci.yml)

Two scripts for a specific, expensive problem in AI-assisted study: **the
readings never fully reach the assistant — and it doesn't tell you.** Two ways
that happens:

- **Large or scanned PDFs get truncated.** An assistant has a ceiling on how
  much it can ingest at once; hand it a 700-page scanned Clausewitz and it
  reads the first 50 pages or so, then stops — usually without saying so. What
  comes back looks like a summary of the book. It is a summary of the first
  seven percent of the book.
- **Half your readings aren't PDFs.** A syllabus links out to articles — some
  open, some paywalled behind an institutional login — that never get read
  unless something fetches them first.

`preprocess_pdf.py` extracts the whole PDF on your own machine, verifies the
page count against the PDF's own count, and hands you a plain `.txt` you can
search, quote from, and feed to an assistant **in targeted pieces** instead of
whole. `fetch_readings.py` pulls reading links out of a syllabus PDF or a plain
`--urls` file and fetches what it can, routing paywalled ones to a
manual-capture list rather than pretending it got them. Both tools are **honest about what they couldn't
get** — OCR'd text is tagged, page-count gaps are flagged, paywalled readings
are listed. The assistant's failure is silent; this isn't.

Measured on the course's Howard/Paret *On War* (30 MB, 743 pages):

| | Before | After |
|---|---|---|
| Pages readable | roughly 48-69 | 743 of 743 |
| Page order verified | no | yes |
| Text known character-exact | unknown | 95.4% (rest tagged) |

---

## Why not just use a free PDF converter?

A free converter turns a PDF into text. This tool makes sure the whole PDF
reaches the assistant and tells you when it didn't.

| Free converter | This tool |
|---|---|
| One big text dump | Verifies the extracted page count matches the PDF |
| OCRs everything or nothing | OCRs only scanned pages, so typeset books stay fast |
| No page markers | Inserts `--- PAGE 1 ---`, `--- PAGE 2 ---`, etc. for exact ranges |
| No quality report | Reports page count, OCR percentage, and missing-page warnings |
| Leaves headers/footers in | Strips repeated running headers, footers, and page numbers |
| Doesn't handle syllabus links | Fetches open articles; lists paywalled ones for manual capture |
| Uploads to a server | Runs entirely on your machine |

---

## What's here

| File | What it does |
|---|---|
| `preprocess_pdf.py` | PDF -> complete searchable text, with OCR for scanned pages |
| `fetch_readings.py` | Syllabus PDF / URL list -> fetches the readings that are only links |
| `RUN-ME.bat` / `run-me.sh` | No-command-line launchers (Windows / macOS-Linux) |
| `docs/QUICKSTART.md` | **Start here if you are not technical.** Click-by-click setup and run guide. |
| `docs/SETUP.md` | Install, per operating system. More detail than QUICKSTART. |
| `docs/SECURITY.md` | What you're installing and how to verify it. Read before installing. |
| `docs/WORKFLOW.md` | The whole loop: Drive, extraction, study guides |
| `docs/USING-WITH-AI.md` | How to actually get good study guides out of this |
| `docs/PAYWALLED-READINGS.md` | The readings you can't fetch, and what to do |
| `docs/QUALITY.md` | Reading the quality report; when to trust OCR text |

---

## Quickstart

**Not comfortable with the command line?** Use `docs/QUICKSTART.md` — it has
click-by-click instructions for Windows, macOS, and Linux.

If you are comfortable with the command line:

```
git clone https://github.com/RichardDeegan88/Extraction_Tool.git
cd Extraction_Tool
pip install -r requirements.txt
python preprocess_pdf.py --check          # verify tools are installed
python preprocess_pdf.py "path/to/books" --out-dir extracted
```

**No command line?** Double-click `RUN-ME.bat` (Windows), or run `./run-me.sh`
(macOS/Linux) — both walk you through it and prompt for a folder.

Then read `docs/QUALITY.md` before you quote anything.

> First time on a managed or work machine? Read `docs/SECURITY.md` before
> installing — it covers what each tool is and how to verify it.

To preview what a run would do without writing any files:

```
python preprocess_pdf.py "path/to/books" --out-dir extracted --dry-run
python fetch_readings.py syllabus.pdf --out-dir readings --dry-run
# or, if you already have a list of URLs:
python fetch_readings.py --urls urls.txt --out-dir readings --dry-run
```

If you installed the package (`pip install .` or `uv pip install .`), the same
commands are available as `preprocess-pdf` and `fetch-readings`.

---

## Fetch readings from the web

If your syllabus or reading list links out to articles instead of PDFs:

```
# Extract links from a syllabus PDF and fetch what is openly available
python fetch_readings.py syllabus.pdf --out-dir readings

# Or give it a plain text file with one URL per line
python fetch_readings.py --urls urls.txt --out-dir readings
```

It writes each fetched article as a `.txt` file, downloads any direct PDFs it
finds, and creates `readings/MANUAL_CAPTURE.txt` listing anything it could not
fetch — paywalled pages, login-gated articles, or bot-protected content. It does
not bypass paywalls; save those through your browser and then point
`preprocess_pdf.py` at the saved PDFs.

Preview what it would fetch without making network requests or writing files:

```
python fetch_readings.py --urls urls.txt --out-dir readings --dry-run
```

List the discovered URLs grouped by category without fetching anything:

```
python fetch_readings.py syllabus.pdf --list-only
python fetch_readings.py --urls urls.txt --list-only
```

If the same URL appears on multiple syllabus pages, it is fetched once but
reported with every page where it appears.

### Exit codes

`fetch_readings.py` now reports honest exit codes:

- `0` — all non-video readings were successfully fetched or already present.
- `2` — partial completion; some readings need manual capture or hit
  recoverable failures. Check `MANUAL_CAPTURE.txt`.
- `1` — fatal failure, invalid input, no URLs discovered, or every attempted
  retrieval failed unexpectedly.

A run that acquires no readings will never silently return `0`.

### Configuring gated sources

Known institutional resolver hosts (such as `aul.primo.exlibrisgroup.com`)
are treated as gated by default. You can add your own host substrings with
`--gated-host` (repeatable):

```
python fetch_readings.py syllabus.pdf --out-dir readings \
  --gated-host myproxy.example.edu --gated-host catalog.example.edu
```

---

## Use with an AI assistant

This toolkit is designed so an AI assistant can run it for you. A typical
workflow:

1. **Point the AI at this repo.** Give it the URL
   `https://github.com/RichardDeegan88/Extraction_Tool` and ask it to set the
   tool up on your machine.

2. **Upload your syllabus or reading list.** A PDF syllabus works best; a plain
   text file with one URL per line also works.

3. **Ask the AI to fetch the web readings.** For example:
   "Run `fetch_readings.py` on my syllabus and tell me what it downloaded and
   what needs manual capture."

4. **Ask the AI to extract any PDFs.** For example:
   "Run `preprocess_pdf.py` on the readings folder and verify the page counts."

5. **Feed the extracted text back to the AI in pieces.** Use the
   `--- PAGE N ---` markers to pull a chapter or page range, not the whole book.
   Check `docs/QUALITY.md` before quoting from `[OCR]` pages.

See `docs/USING-WITH-AI.md` for prompt advice, page-range strategies, and
academic-integrity notes.

---

## Important: what you can and cannot share

**Share the tools freely.** Scripts and docs, no restrictions.

**Do not share the extracted text files.** A `.txt` of the Howard/Paret
translation is the complete copyrighted work. Redistributing it is
infringement, whether or not the recipient also owns the book, and whether or
not the folder is private.

Everyone runs the tool on their own copy. That takes an afternoon and keeps the
whole thing clean.

---

## What these tools do not do

Neither script summarises, paraphrases, rewrites, or generates any text.
Neither contains an AI model. They cannot invent content that is not in the
source.

Their failure modes are **garbled characters** (from OCR) and **omissions**,
never fabrication. Both are labelled in the output: OCR pages carry an `[OCR]`
tag, and every output file opens with a measured quality report.

The AI comes later, when you use the extracted text. That part is on you, and
`docs/USING-WITH-AI.md` covers how to keep it honest.

---

## Limitations

- **Paywalls and institutional logins are not bypassed.** Save those readings as
  PDFs through your browser, then point `preprocess_pdf.py` at the saved files.
  `fetch_readings.py` writes any gated links to `MANUAL_CAPTURE.txt`.
- **`fetch_readings.py` fetches only openly available pages.** Paywalled,
  login-gated, or bot-protected content is listed for manual capture rather than
  bypassed.
- **Videos are not transcribed.** Video links are skipped by default.
- **Output is raw text, not a summary.** The tool only makes the source readable.

See `docs/QUICKSTART.md` for a recommended folder layout and storage setup.

---

## Requirements

- Python 3.12 or newer
- poppler-utils (`pdftotext`, `pdftoppm`, `pdfinfo`)
- tesseract-ocr (for scanned pages)
- ImageMagick (optional, straightens crooked scans)
- Python packages: `pip install -r requirements.txt`

See `docs/SETUP.md`. On Windows, tesseract usually needs adding to PATH by hand;
that is the single most common setup failure and the doc covers it.

---

## Tests

```
pip install -r requirements.txt -r requirements-test.txt
pytest tests/
```

The suite uses synthetic PDF fixtures, so it does not need any copyrighted books.

The two scripts above are thin command-line adapters. The extraction and
fetching logic now lives in the `src/extraction_tool` package (Data Access
Factory layout). Contributors should read `ARCHITECTURE.md` for the layer model,
security invariants, and the Power-of-Ten complexity gates before changing that
code.

## REST API

The same extraction and reading-acquisition logic is also available as a
FastAPI router in `src/extraction_tool/adapters/fastapi.py` for integrating
into a larger FastAPI application. It is not a standalone server yet; see the
module docstring for router usage and rate-limit defaults.

## Version

v1.2.1 — see `CHANGELOG.md` for release notes and known limits.

---

## License

MIT — see `LICENSE`. The licence covers this software only, **not** the
documents you process; extracted book text remains the copyright of its
rights-holders (see the sharing note above).

Issues and pull requests welcome.
