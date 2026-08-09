# The whole workflow

From "I have a folder of course PDFs" to "I can ask an assistant about any page
of any book without it silently reading only the first fifty."

Do the extraction **once per book**. After that, every study session just reads
the text file.

---

## One-time: extract everything

```powershell
python preprocess_pdf.py "C:\path\to\Semester 1 Readings" --out-dir "C:\path\to\Semester 1 Readings\extracted"
```

The script recurses into subfolders, skips anything already done, and prints
progress. A large library with several scanned books takes one to two hours.
Start it and walk away.

Re-run the same command any time you add new PDFs. It only processes what's new.
Add `--overwrite` to force a redo.

Each PDF produces two files:

- `Book.txt` — the complete text, with `--- PAGE N ---` markers
- `Book.txt.index` — detected book/chapter structure with line numbers

Writing `--out-dir` into a Drive-synced folder means the outputs upload
themselves. No manual step.

---

## One-time: fetch the readings that are only links

Reading lists mix PDFs with articles that exist only as URLs. The second script
reads your syllabus PDF and pulls out every link, including ones hidden behind
anchor text like "Part I".

See what's there first:

```powershell
python fetch_readings.py "Reading master.pdf" --list-only
```

That prints a categorised inventory and fetches nothing. It's also the fastest
way to see what your reading list actually contains.

Then fetch:

```powershell
python fetch_readings.py "Reading master.pdf" --out-dir web_readings
```

Direct PDF links get downloaded into `web_readings/downloaded_pdfs/`. Run the
first script over that folder to extract them too:

```powershell
python preprocess_pdf.py "web_readings\downloaded_pdfs" --out-dir web_readings
```

Anything paywalled or behind an institutional login is **not** fetched. It's
listed in `web_readings/MANUAL_CAPTURE.txt`. See `PAYWALLED-READINGS.md`.

---

## Before you trust any of it: check the quality reports

Every `.txt` opens with a measured quality report. Scan them:

```powershell
Get-ChildItem extracted\*.txt | ForEach-Object {
    $head = Get-Content $_ -TotalCount 25
    $pages = $head | Select-String "Pages extracted"
    $ocr   = $head | Select-String "Pages read by OCR"
    "$($_.Name)`n  $pages`n  $ocr`n"
}
```

You're looking for two things: page count matching, and OCR percentage. Full
detail in `QUALITY.md`.

---

## Per assignment: find and pull the range

Reading lists give printed page numbers ("pp. 227-241"). Page markers carry PDF
page numbers. **These are not always the same** — front matter can offset them.

**Check the offset once per book.** Look at what's on the marker and compare to
what's printed on that page in the PDF:

```powershell
Select-String -Path "extracted\Clausewitz.txt" -Pattern "^--- PAGE 227 " -Context 0,20
```

In the Howard/Paret *On War* the offset is zero: PDF page 227 is printed page
227. Other books in the same course run up to 14 pages out. Check, note it, move
on.

Then pull the range:

```powershell
Select-String -Path "extracted\Clausewitz.txt" -Pattern "^--- PAGE 241 "
Get-Content "extracted\Clausewitz.txt" | Select-Object -Index (8371..8900)
```

macOS/Linux:

```bash
grep -n "^--- PAGE 227 " extracted/Clausewitz.txt
sed -n '8371,8900p' extracted/Clausewitz.txt
```

Copy that range into your assistant. It's a few thousand words, not a 30 MB
book, so nothing truncates and nothing gets silently dropped.

---

## Per assignment: the chapter index

```powershell
type extracted\Clausewitz.txt.index
```

If the header says **embedded PDF outline**, that's the publisher's own
structure and it's reliable.

If it says **text-pattern detection**, treat it as a rough guide only. It can
miss chapters whose headings are formatted oddly or garbled by OCR, and can
occasionally list a cross-reference as a heading. Cross-check against the book's
printed table of contents. Page markers are always reliable; the index is a
convenience.

---

## Recommended folder layout

```
Semester 1 Readings/
├── Clausewitz_On_War.pdf          <- originals, untouched
├── Sun_Tzu_Griffith.pdf
├── extracted/                     <- generated, safe to delete and rebuild
│   ├── Clausewitz_On_War.txt
│   └── Clausewitz_On_War.txt.index
└── web_readings/                  <- from fetch_readings.py
    ├── MANUAL_CAPTURE.txt
    └── downloaded_pdfs/
```

Everything under `extracted/` is reproducible from the PDFs. Delete and rebuild
it freely.

---

## Sharing with classmates

Share the **scripts and docs**. Not the `extracted/` folder — those files are
complete copyrighted books, and redistributing them is infringement regardless
of who owns what.

Each person runs the tool on their own course-issued PDFs. One afternoon, and
the result is identical.
