# Quickstart for non-technical users

This guide assumes you have never used the command line and do not want to. If
you are comfortable with `python` and `pip`, use `docs/SETUP.md` and
`docs/WORKFLOW.md` instead — they are faster.

---

## What this tool does

It turns your course PDFs into plain text files you can search and copy from.
That matters because AI assistants often stop reading a big PDF after the first
few dozen pages without telling you. This tool extracts the **whole** PDF on
your own computer, page by page, and tells you honestly if any page had to be
read by OCR (machine vision).

It also fetches the articles your syllabus links to, and makes a list of any
paywalled ones you need to save yourself.

---

## What you need before you start

1. A Windows, Mac, or Linux computer.
2. Your course PDFs saved somewhere on that computer (a folder is fine).
3. About 20 minutes for setup, plus run time for the extraction.

You do **not** need a programming background.

---

## Windows — step by step

### Step 1: Install Python

1. Open a web browser and go to <https://python.org/downloads>.
2. Click the big yellow **Download Python** button.
3. Run the downloaded installer.
4. **Important:** on the first screen, tick the box that says **"Add Python to
   PATH"**. It is small and easy to miss.
5. Click **Install Now**.

### Step 2: Install the toolkit tools

1. Right-click the Start button and choose **Terminal (Admin)** or
   **Windows PowerShell (Admin)**.
2. Copy and paste these four lines, one at a time. Press Enter after each:

```powershell
winget install oschwartz10612.Poppler
winget install UB-Mannheim.TesseractOCR
winget install ImageMagick.ImageMagick
pip install -r requirements.txt
```

3. Say `Y` or click **Yes** to any prompts.
4. **Close the PowerShell window and open a new one.** This is required; the
   tools you just installed are not visible to the old window.

### Step 3: Check that everything worked

In the new PowerShell window, type:

```powershell
python preprocess_pdf.py --check
```

You should see a list ending with:

```
All required tools are present.
```

If `tesseract` says MISSING, see the fix in `docs/SETUP.md` under
"If tesseract shows MISSING". That is the most common problem.

### Step 4: Run the tool

1. Find the folder on your computer that contains your course PDFs.
2. In File Explorer, click once on that folder to highlight it.
3. Hold **Shift** and right-click the folder. Choose **Copy as path**.
4. Double-click `RUN-ME.bat` in the toolkit folder.
5. When it asks for the folder path, right-click in the window and choose
   **Paste**.
6. Press Enter.
7. The tool will ask if you want to continue if anything is missing. If the
   check in Step 3 was green, press `Y`.

A new `extracted` folder will appear inside your readings folder. That is where
the `.txt` files go.

---

## macOS — step by step

### Step 1: Install Homebrew

If you do not already have Homebrew, open **Terminal** and paste this:

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

Follow the prompts.

### Step 2: Install the toolkit tools

In Terminal, paste these two commands:

```bash
brew install poppler tesseract imagemagick
pip3 install -r requirements.txt
```

### Step 3: Run the tool

1. In Terminal, type `cd ` (with a space after it).
2. Drag the toolkit folder from Finder into the Terminal window. The path will
   appear.
3. Press Enter.
4. Type `./run-me.sh` and press Enter.
5. Drag your readings folder into the Terminal window when it asks for it.
6. Press Enter.

---

## Linux — step by step

Open a terminal in the toolkit folder and run:

```bash
sudo apt install poppler-utils tesseract-ocr imagemagick
pip install -r requirements.txt
./run-me.sh
```

---

## What happens while it runs

- The tool reads each PDF page by page.
- Pages that already have text are extracted quickly.
- Pages that are scanned images are sent to OCR. This is much slower — roughly
  one to three seconds per page.
- A big scanned book can take a few minutes. A whole semester's readings can
  take an hour or two. Start it and walk away.
- Already-processed files are skipped, so it is safe to re-run the same folder
  after adding new PDFs.

---

## What you get

For every PDF, the tool creates two files in the `extracted` folder:

- `Book.txt` — the full text with `--- PAGE 1 ---`, `--- PAGE 2 ---`, etc.
- `Book.txt.index` — a list of detected chapters and their line numbers.

Open `Book.txt`. The first thing you see is a **quality report**. Read it.
If it says the page count matches and the OCR percentage is low, the file is
reliable. If it flags problems, see `docs/QUALITY.md`.

---

## Fetching syllabus links (optional)

If your reading list has links instead of PDFs:

1. Find your syllabus PDF.
2. In PowerShell / Terminal, run:

```powershell
python fetch_readings.py "path\to\syllabus.pdf" --out-dir web_readings
```

3. The tool downloads what it can and writes a `MANUAL_CAPTURE.txt` file
   listing anything behind a paywall.

---

## "It didn't work" checklist

| Symptom | Likely fix |
|---|---|
| `python` is not recognised | Re-install Python and tick **Add Python to PATH**. |
| `tesseract` MISSING | It is installed but not on PATH. See `docs/SETUP.md`. |
| `winget` not recognised | Update Windows or install the tools manually from their websites. |
| The batch file flashes and closes | Run it from PowerShell with `RUN-ME.bat` so you can read the error. |
| Output folder is empty | Check the PowerShell/Terminal output for red error text. |
| Page count does not match | The PDF may be unusual; see `docs/QUALITY.md`. |

---

## Next steps

- Read `docs/QUALITY.md` before quoting anything from a `.txt` file.
- Read `docs/WORKFLOW.md` for the full routine, including how to pull a page
  range for an assistant.
- Read `docs/USING-WITH-AI.md` for prompt advice and academic-integrity notes.
