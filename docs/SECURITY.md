# Security, trust, and what you're actually installing

Read this before installing anything, especially on a work machine.

---

## Check your IT policy first

**On a government-furnished or organisation-managed machine, check your local IT
and cybersecurity policy before installing any of this.** Some of these packages
are unsigned open-source builds. On a managed system that is often a policy
matter regardless of whether the software is safe, and the consequences of
getting it wrong are administrative rather than technical.

If in doubt, ask your IT or cyber section, or run the toolkit on a personal
machine instead. Nothing here needs to touch a work system.

---

## What you're installing, and who made it

| Package | Publisher | Signed? |
|---|---|---|
| ImageMagick | ImageMagick Studio LLC | Yes, valid |
| Tesseract OCR | Universität Mannheim | Yes (chain may not fully validate) |
| Poppler (`pdftotext`) | Community maintainer (`oschwartz10612`) | **No** |
| Google Drive for Desktop | Google | Yes |
| `pypdf`, `trafilatura` | PyPI packages | n/a (Python source) |

**Poppler is the weak link and you should know why.** The Poppler project itself
is mature and widely used, but it publishes no official Windows binaries.
Everyone on Windows therefore uses a community build. The one winget installs is
the build the mainstream Python PDF ecosystem points to, so it has many users,
but it is one maintainer's compiled binaries and it is not code-signed.

That is normal for open-source Windows tooling — signing certificates cost money
and volunteer maintainers often skip them — but "normal" is not "verified", and
you should make that call knowingly rather than by default.

---

## Verify what landed on your machine

Check the signatures yourself:

```powershell
Get-ChildItem "C:\Program Files\Tesseract-OCR\tesseract.exe",
              (Get-Command pdftotext).Source,
              (Get-Command magick -ErrorAction SilentlyContinue).Source `
              -ErrorAction SilentlyContinue |
  ForEach-Object {
      $s = Get-AuthenticodeSignature $_.FullName
      "$($_.Name): $($s.Status) - $($s.SignerCertificate.Subject)"
  }
```

Expected output:

```
tesseract.exe: UnknownError - CN=Universität Mannheim, ...
pdftotext.exe: NotSigned -
magick.exe:    Valid - CN=ImageMagick Studio LLC, ...
```

How to read that:

- **`Valid`** — signed and the chain checks out.
- **`UnknownError` with the correct signer name** — signed by who you'd expect,
  but the certificate chain didn't fully validate (commonly an expired
  timestamp). Not evidence of tampering. Confirm the signer name matches.
- **`NotSigned`** — no signature. Expected for the Poppler build. Your trust
  rests on winget's hash verification instead (below).
- **`Valid` but an unexpected signer name, or `HashMismatch`** — stop. That is
  not what should be there.

Confirm your package sources are Microsoft's official ones:

```powershell
winget source list
```

You want only `msstore`, `winget`, and possibly `winget-font`, all pointing at
`microsoft.com` addresses. An unfamiliar source means packages could be coming
from somewhere you didn't intend.

---

## Why unsigned isn't the same as unverified

When winget installs a package it checks the downloaded installer against a
SHA256 hash pinned in the Microsoft-curated package manifest. You'll have seen
`Successfully verified installer hash` scroll past during installation.

That confirms the file you received is byte-identical to the one the package
manifest describes. It doesn't tell you the maintainer is trustworthy, but it
does rule out tampering in transit or a substituted download — which is the
attack the Windows "unknown publisher" warning is actually pointing at.

So the chain is: Microsoft's curated repository, over HTTPS, hash-verified on
arrival. Reasonable. Not the same as a signed binary from a known company.

---

## The scripts in this toolkit

`preprocess_pdf.py` and `fetch_readings.py` are plain Python text files. Nothing
compiled, nothing installed, no executables. You can read every line before
running them, and you should — that's the advantage of a script over a binary.

What they do to your system:

- **Read** your PDFs. They never modify or delete a source file.
- **Write** `.txt` and `.index` files to the output folder you specify.
- **Run** `pdftotext`, `pdftoppm`, `tesseract`, and `magick` as subprocesses.
- `fetch_readings.py` additionally makes outbound HTTPS requests to the URLs
  found in your syllabus.

They contain no AI model, send nothing anywhere except the article fetches
above, and require no credentials or account.

One deliberate safety measure worth knowing about: on Windows, `convert` is a
**built-in system command that converts NTFS filesystems**, unrelated to
ImageMagick. The script refuses to execute anything named `convert` from
System32 and looks for `magick` instead.

---

## If you'd rather not install anything

The extraction genuinely needs local tools; there's no way around that. But if
your machine is locked down, reasonable alternatives are:

- Run it on a personal laptop and move the resulting `.txt` files (they're small).
- Ask IT whether Poppler and Tesseract can be approved — both are extremely
  common, and Tesseract in particular is widely deployed in government contexts.
- For a handful of readings, your PDF reader's own "export as text" is clumsy
  but installs nothing.

---

## Reporting a problem

Found a bug, or a security concern with the scripts themselves?

- **General bugs:** open an issue at
  https://github.com/richarddeegan88/acsc-reading-toolkit/issues
- **Security-sensitive reports:** use GitHub's private vulnerability reporting
  (the **Security** tab -> *Report a vulnerability*) rather than a public issue,
  so it can be looked at before it's visible to everyone.

These are two short Python scripts with no network service and no stored
credentials, so the realistic attack surface is small — but reports are
welcome, and a note about the tool version and your OS helps.
