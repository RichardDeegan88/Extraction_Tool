# Quality: what to trust, and when to check

Every extracted file opens with a measured quality report. Read it before you
quote anything. It takes ten seconds and it is the difference between citing the
book and citing an OCR guess.

---

## A real report

```
QUALITY REPORT (measured from this extraction)
  Pages extracted:      743 of 743 reported by the PDF
  Page count matches:   YES
  Page order intact:    YES
  Blank pages:          21
  Pages read by OCR:    34 (4.6%)
  Words extracted:      330,876 (445/page average)

WARNINGS
  ! 34 page(s) had no text layer and were read by OCR.
```

That is the Howard/Paret *On War*. It says: nothing is missing, nothing is out
of order, and 95.4% of the text came straight from the PDF's own text layer and
is character-exact. The remaining 4.6% went through OCR and is individually
tagged.

---

## The four things to look at

### 1. Page count matches

`YES` means the number of pages extracted equals the number the PDF itself
reports. This is the check that catches truncation.

`NO` is a **hard stop**. Pages are missing. Do not treat the file as a complete
source until you know why.

### 2. Page order intact

`YES` means page markers run 1, 2, 3 with no gaps. `NO` means page references in
the file are unreliable.

### 3. OCR percentage

The number that matters most for citation.

| OCR | What it means |
|---|---|
| Under 10% | Nearly all character-exact. Check individual `[OCR]` pages only. |
| 10-50% | Mixed. Verify any quotation from a tagged page. |
| Over 50% | Treat the whole file as approximate. Paraphrase by default. |

### 4. Words per page

Under 50 with a real page count usually means the PDF is images the OCR
struggled with. Investigate before relying on it.

---

## OCR errors are real

Observed in this course's own material:

- `BOOK SIX` read as `BOOK SIx`
- `II.` read as `Il.` (capital i versus lowercase L)

Both are the same class of error: visually similar characters. They are
invisible when you skim and fatal in a direct quotation.

**Rule: never quote verbatim from a page tagged `[OCR]` without checking the
wording against the original PDF page.**

Find the tagged pages:

```powershell
Select-String -Path "extracted\Book.txt" -Pattern "^--- PAGE .*\[OCR\]"
```

```bash
grep -n "^--- PAGE .*\[OCR\]" extracted/Book.txt
```

A useful pattern from real use: in *On War*, 21 of the 34 OCR'd pages were
`[BLANK]` (no text at all, so no risk), and the remaining 13 turned out to be
book-division title pages — "BOOK SIX / Defense" on its own leaf. So the
practical citation risk was close to zero, but you only know that by looking.

---

## What the tool cannot do to you

Neither script contains an AI model. Neither summarises, paraphrases, or
generates text. **They cannot fabricate content.**

| Failure | Can it invent text? | How you'd catch it |
|---|---|---|
| OCR misreads a character | No, it garbles what's there | `[OCR]` tag on the page |
| A chapter missing from the index | No, omission only | Content won't match the heading |
| A prose line listed as a heading | No, that text really is there | Obviously not a heading |
| Hyphenated word over-joined | No, rejoins existing characters | Rare, visible in context |

Every failure is **garbling or omission, never invention**. That's the property
that makes the output safe to build on: worst case you get less than the book
says, never something the book doesn't say.

The risk of fabrication enters later, when an assistant writes about the text.
See `USING-WITH-AI.md`.

---

## Other things worth knowing

**Hyphenation.** Words split across a line break by a hyphen get rejoined. This
occasionally merges a genuine compound (`well-known` becoming `wellknown`).
Rare, but check when quoting across a line break.

**Running headers.** Lines repeated at the top or bottom of most pages are
stripped. A header scoped to one chapter or book may survive; it shows up as a
repeated entry in the index, not as corrupted text.

**PDF metadata.** The Title and Author in the file header come from the PDF's
own metadata, which is set by whoever made the file and is frequently wrong. One
real book's title field read `imageItem8901132859708402734#_#9780190265687`.
Verify against the title page.

**Metadata filenames.** When `--name-from-metadata` is used, the tool tries to
swap "Surname, First" into "First Surname" so filenames read naturally. It
handles simple suffix cases such as "Meyer, Jr., David" -> "David Meyer, Jr.",
but unusual author strings (multiple commas, "Jr." in unexpected positions,
multi-author "X and Y" strings) are left as-is rather than guessed. The output
name is safest when the PDF's `/Author` field is already in "First Last" form.

**Blank pages** are tagged `[BLANK]` rather than silently dropped, so the page
numbering stays honest.
