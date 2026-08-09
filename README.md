# ACSC Reading Toolkit

Two scripts that solve a specific, expensive problem: **large PDF readings get
truncated when you hand them to an AI assistant, and you often can't tell.**

Point an assistant at a 700-page scanned Clausewitz and it will read the first
50 pages or so and then stop. It will not usually say it stopped. What comes
back looks like a summary of the book. It is a summary of the first seven
percent of the book.

These scripts extract the whole text on your own machine, verify the page count
against the PDF's own count, and hand you a plain `.txt` file you can search,
quote from, and feed to an assistant in targeted pieces.

Measured on the course's Howard/Paret *On War* (30 MB, 743 pages):

| | Before | After |
|---|---|---|
| Pages readable | roughly 48-69 | 743 of 743 |
| Page order verified | no | yes |
| Text known character-exact | unknown | 95.4% (rest tagged) |

---

## What's here

| File | What it does |
|---|---|
| `preprocess_pdf.py` | PDF -> complete searchable text, with OCR for scanned pages |
| `fetch_readings.py` | Syllabus PDF -> fetches the readings that are only links |
| `RUN-ME.bat` / `run-me.sh` | No-command-line launchers (Windows / macOS-Linux) |
| `docs/SETUP.md` | Install, per operating system. Start here. |
| `docs/SECURITY.md` | What you're installing and how to verify it. Read before installing. |
| `docs/WORKFLOW.md` | The whole loop: Drive, extraction, study guides |
| `docs/USING-WITH-AI.md` | How to actually get good study guides out of this |
| `docs/PAYWALLED-READINGS.md` | The readings you can't fetch, and what to do |
| `docs/QUALITY.md` | Reading the quality report; when to trust OCR text |

---

## Quickstart

```
git clone https://github.com/richarddeegan88/acsc-reading-toolkit.git
cd acsc-reading-toolkit
pip install -r requirements.txt
python preprocess_pdf.py --check          # verify tools are installed
python preprocess_pdf.py "path/to/books" --out-dir extracted
```

**No command line?** Double-click `RUN-ME.bat` (Windows), or run `./run-me.sh`
(macOS/Linux) — both walk you through it and prompt for a folder.

Then read `docs/QUALITY.md` before you quote anything.

> First time on a managed or work machine? Read `docs/SECURITY.md` before
> installing — it covers what each tool is and how to verify it.

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

## Requirements

- Python 3.9 or newer
- poppler-utils (`pdftotext`, `pdftoppm`, `pdfinfo`)
- tesseract-ocr (for scanned pages)
- ImageMagick (optional, straightens crooked scans)
- Python packages: `pip install -r requirements.txt`

See `docs/SETUP.md`. On Windows, tesseract usually needs adding to PATH by hand;
that is the single most common setup failure and the doc covers it.

---

## Version

v1.0.0 — see `CHANGELOG.md` for release notes and known limits.

---

## License

MIT — see `LICENSE`. The licence covers this software only, **not** the
documents you process; extracted book text remains the copyright of its
rights-holders (see the sharing note above).

Issues and pull requests welcome.
