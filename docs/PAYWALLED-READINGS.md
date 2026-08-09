# Readings you can't fetch automatically

Some assigned readings sit behind a paywall, a subscription, or your
institution's library proxy. A script hitting those gets a sign-in page, not the
article.

`fetch_readings.py` detects this and **writes nothing** for them, listing them in
`MANUAL_CAPTURE.txt` with a reason. That's deliberate: a saved login page that
looks like a successful download is worse than an obvious failure, because you
find out at the wrong moment.

---

## What gets routed to manual capture

| Kind | Example | Why |
|---|---|---|
| Library proxy | `research-ebsco-com.aufric.idm.oclc.org` | Needs your institutional login |
| Journal paywall | JSTOR, Taylor & Francis, Wiley, ScienceDirect | Subscription required |
| Bot protection | Some ResearchGate pages | Serves a challenge page |
| Dead or bare links | A syllabus link pointing at a homepage | Nothing specific to fetch |

A real reading list of 49 links broke down as: 19 fetchable articles, 16 direct
PDFs, 4 gated, 10 videos.

---

## The manual capture routine

Per item in `MANUAL_CAPTURE.txt`:

1. **Open the URL in a browser where you're already signed in.** For a library
   proxy link, that means signed in to your institution.
2. **Ctrl+P** (Cmd+P on Mac), destination **Save as PDF**.
3. Save it into your PDFs folder with a sensible name: `Author_Year_Title.pdf`.
4. When you've done them all, run the extractor over the folder:

```powershell
python preprocess_pdf.py "path/to/manual_pdfs" --out-dir extracted
```

From there they behave exactly like any other reading.

---

## Tips that save time

**Use the site's own PDF button first.** Most journals offer a proper PDF
download once you're authenticated. That's better than print-to-PDF: real text
layer, no navigation furniture, no OCR needed.

**Print-to-PDF gives you a text layer.** Unlike a scan, a browser-printed PDF
carries real text, so extraction is character-exact with no OCR. Check the
quality report to confirm 0% OCR.

**Check reader mode before printing.** Firefox's Reader View and Safari's Reader
strip navigation and ads, giving a much cleaner print. Chrome users can print
and untick "Headers and footers".

**Do them in one sitting.** Four to six gated readings takes about fifteen
minutes as a batch, versus a frustrating interruption each time one turns up
mid-assignment.

---

## Videos

Assigned videos can't be text-extracted and are skipped by default. If you want
a transcript, use the platform's own caption or transcript feature rather than
any third-party tool. `--include-videos` writes a placeholder note recording the
URL, so your reading inventory stays complete.

---

## What not to do

**Don't try to defeat a paywall.** The script deliberately makes no attempt, and
neither should you. Your institution's library subscription is the legitimate
route and it already covers these.

**Don't skip a gated reading silently.** It's assigned. If you genuinely can't
get access, say so rather than producing a study guide that quietly omits it —
and tell your instructor, since a broken syllabus link is worth fixing for
everyone.

**Don't redistribute what you capture.** A print-to-PDF of a paywalled article
is still the publisher's copyrighted work. Personal study use only.
