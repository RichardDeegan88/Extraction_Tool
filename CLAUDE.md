# Instructions for an AI agent working in this folder

If you are an AI assistant with the ability to run commands on this machine
(Claude Code, Cowork, or similar), this file tells you how to operate this
toolkit on the user's behalf. If you are a chat assistant without local
command execution, you cannot run these scripts — say so plainly rather than
producing instructions the user then has to run themselves without being told.

---

## What this toolkit is for

Large or scanned PDFs get truncated when read directly by an assistant, often
silently. These scripts extract the complete text locally so nothing is lost.

- `preprocess_pdf.py` — PDF to complete searchable text, OCR for scanned pages
- `fetch_readings.py` — syllabus PDF to fetched web readings

---

## Before doing anything

Run the dependency check and report the result:

```
python preprocess_pdf.py --check
```

If anything required is MISSING, stop and point the user at `docs/SETUP.md`.
Do not attempt to install system packages without asking first. On Windows the
usual cause is Tesseract being installed but not on PATH.

---

## Extracting a folder of PDFs

```
python preprocess_pdf.py "<folder>" --out-dir "<folder>/extracted"
```

Notes:
- It recurses into subfolders and skips files already processed. Safe to re-run.
- Large scanned books take minutes each. Do not assume it has hung.
- Never pass `--overwrite` unless the user asked for a redo.
- Do not run two instances against the same output folder at once.

**After the run, report the per-file quality figures, not just "done".** The
summary flags files with page-count mismatches, broken page order, or high OCR
percentages. Those matter more than the fact it finished.

---

## Reading a specific assigned range

Assignments give printed page numbers. Page markers carry PDF page numbers.
**These are not always the same.**

1. Verify the offset once per book before trusting any range: compare a page
   marker against the page number printed on that page.
2. Then locate and pull the range:

```
grep -n "^--- PAGE 227 " book.txt
sed -n '8371,8900p' book.txt
```

PowerShell:

```
Select-String -Path book.txt -Pattern '^--- PAGE 227 ' -Context 0,50
```

Read the range you pulled. Do not summarise a book from scattered samples; a
summary built from a light sample is capped at the depth of the sample no
matter how much prose is written around it.

---

## Rules you must follow when using the extracted text

**Check the quality report first.** Every `.txt` opens with one. If page count
does not match the PDF's own count, or page order is broken, treat the file as
unreliable and say so rather than working around it.

**Never quote verbatim from a page tagged `[OCR]` without flagging it.** OCR
misreads characters — real observed examples: `SIX` read as `SIx`, `II.` read as
`Il.`. Tell the user which pages are affected and that the wording needs
checking against the original PDF.

**Do not trust the `.txt.index` as authoritative** unless its header says it came
from an embedded PDF outline. A pattern-matched index can miss chapters and can
occasionally list a cross-reference as a heading. Page markers are always
reliable.

**Do not invent locators.** If you cannot find a passage, say you could not find
it. Search the text file rather than recalling from training data — the user's
edition and translation are specific and your memory of the work may be a
different one.

**Never fill a gap from memory or another translation.** Mark it missing.

---

## Fetching link-based readings

```
python fetch_readings.py "<syllabus>.pdf" --list-only          # inventory only
python fetch_readings.py "<syllabus>.pdf" --out-dir web_readings
```

Paywalled and institutional-proxy readings are deliberately **not** fetched;
they are listed in `MANUAL_CAPTURE.txt`. Do not attempt to work around a
paywall. Report those to the user for manual browser capture and point them at
`docs/PAYWALLED-READINGS.md`.

Direct PDF links are downloaded to `web_readings/downloaded_pdfs/`. Run the
extractor over that folder afterwards.

---

## Things you must not do

- **Do not modify or delete the source PDFs.** The scripts only read them.
- **Do not redistribute extracted text.** These are complete copyrighted books
  held for personal study. If the user asks you to publish, share, or commit
  them, say why that is a problem.
- **Do not commit `.txt`, `.pdf`, or `extracted/` to any repository.**
- **Do not write the user's graded work.** Helping them read and understand
  assigned material is the purpose here. Producing prose they submit is not, and
  their institution has a policy on this that governs.

---

## Reporting back

A good report after an extraction run states: how many files processed, any
flagged for quality problems with the specific numbers, the OCR percentage for
anything the user is about to cite from, and what remains outstanding (manual
captures, unprocessed files). A bad report says "all done".
