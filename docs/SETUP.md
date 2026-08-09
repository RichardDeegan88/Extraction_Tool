# Setup

Fifteen minutes, once. The only step that reliably causes trouble is getting
tesseract onto PATH on Windows, covered below.

---

## Windows

### 1. Python

```powershell
python --version
```

If that reports a version, you're done. If it opens the Microsoft Store or
errors, install from https://python.org and **tick "Add Python to PATH"** during
installation.

### 2. The three tools

```powershell
winget install oschwartz10612.Poppler
winget install UB-Mannheim.TesseractOCR
winget install ImageMagick.ImageMagick
pip install -r requirements.txt
```

Accept any licence prompt (`Y`) or UAC dialog.

### 3. Close PowerShell and open a new one

PATH changes don't reach a window that was already open. This step is not
optional and skipping it produces confusing "missing tool" errors.

### 4. Verify

```powershell
python preprocess_pdf.py --check
```

Every line should read `[OK]`.

### 5. If tesseract shows MISSING

This is the common case. The UB Mannheim installer does not add itself to PATH.

Confirm where it landed:

```powershell
dir "C:\Program Files\Tesseract-OCR\tesseract.exe"
```

Add it permanently:

```powershell
[Environment]::SetEnvironmentVariable("Path",
  [Environment]::GetEnvironmentVariable("Path","User") +
  ";C:\Program Files\Tesseract-OCR", "User")
```

Then open a new PowerShell window and run `--check` again.

If the file wasn't at that path, find it:

```powershell
Get-ChildItem "C:\Program Files","C:\Program Files (x86)",$env:LOCALAPPDATA -Recurse -Filter "tesseract.exe" -ErrorAction SilentlyContinue | Select-Object FullName
```

and substitute its folder into the command above.

### A note on `convert`

On Windows, `convert` is a **built-in system command** that converts NTFS
filesystems. It has nothing to do with ImageMagick. The script deliberately
looks for `magick` instead and refuses to run anything from System32. You don't
need to do anything; just don't be alarmed if you see `convert` referenced in
older ImageMagick documentation.

---

## macOS

```bash
brew install poppler tesseract imagemagick
pip3 install -r requirements.txt
python3 preprocess_pdf.py --check
```

If you don't have Homebrew, get it from https://brew.sh first.

---

## Linux (Debian/Ubuntu)

```bash
sudo apt install poppler-utils tesseract-ocr imagemagick
pip install -r requirements.txt
python3 preprocess_pdf.py --check
```

---

## What each tool is for

| Tool | Required? | Used for |
|---|---|---|
| `pdftotext` | yes | Pulling text from PDFs that have a text layer |
| `pdftoppm` | yes | Rendering scanned pages to images for OCR |
| `pdfinfo` | no | Reading the PDF's own page count, used to verify nothing was lost |
| `tesseract` | yes | OCR on scanned pages |
| ImageMagick | no | Straightening and cleaning crooked scans before OCR |
| `pypdf` | no | Fallback extractor, plus reading embedded chapter outlines |
| `trafilatura` | no | Much cleaner article text in `fetch_readings.py` |

The "no" entries degrade gracefully. Without ImageMagick, crooked scans OCR
slightly worse. Without trafilatura, fetched articles include more navigation
clutter and the output header tells you so. Without pypdf, chapter indexes fall
back to pattern matching.

---

## Getting your PDFs onto the machine

**Google Drive for Desktop** is the least painful route. Install it, sign in,
and your whole Drive mounts as a drive letter. You can then point the script
straight at Drive and write the output straight back, with no downloading and
no uploading:

```powershell
winget install Google.GoogleDrive
```

After signing in, check which letter it took:

```powershell
Get-PSDrive -PSProvider FileSystem | Select-Object Name, Root
```

Find your readings folder:

```powershell
Get-ChildItem -Path "G:\" -Recurse -Directory -Filter "*Readings*" -ErrorAction SilentlyContinue | Select-Object FullName
```

**Without it**, open the folder in the browser, select all, and download. Google
gives you a zip. Extract it somewhere local and point the script at that.

One caution: Drive for Desktop streams files on demand, so the first read of a
large PDF pulls it over the network and can be slow. If a batch crawls,
right-click the folder in Explorer and choose **Offline access -> Available
offline** to cache it locally first.
