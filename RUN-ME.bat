@echo off
setlocal enabledelayedexpansion
title ACSC Reading Toolkit

REM ===================================================================
REM  Double-click this file, or drag a folder of PDFs onto it.
REM  No command-line knowledge needed.
REM ===================================================================

cd /d "%~dp0"

echo.
echo  ==========================================================
echo   ACSC Reading Toolkit
echo   Turns PDF books into complete, searchable text files
echo  ==========================================================
echo.

REM ---------- Check Python is available and is version 3.9+ ----------
REM  'where python' also matches the Microsoft Store alias stub, which is not a
REM  real Python. Actually run it, and confirm the version, to be sure.
python -c "import sys; sys.exit(0 if sys.version_info >= (3,9) else 1)" >nul 2>&1
if errorlevel 1 (
    echo  [X] Python 3.9 or newer was not found.
    echo      ^(The 'python' command may be the Microsoft Store stub.^)
    echo.
    echo      Install it from https://python.org
    echo      During install, TICK "Add Python to PATH".
    echo.
    pause
    exit /b 1
)

REM ---------- Check the script is next to this file ----------
if not exist "preprocess_pdf.py" (
    echo  [X] preprocess_pdf.py was not found in this folder.
    echo.
    echo      Put RUN-ME.bat in the same folder as the scripts.
    echo      This folder is: %CD%
    echo.
    pause
    exit /b 1
)

REM ---------- Check required tools ----------
echo  Checking required tools...
echo.
python preprocess_pdf.py --check
echo.

python preprocess_pdf.py --check 2>&1 | find "Some required tools are missing" >nul
if not errorlevel 1 (
    echo  ----------------------------------------------------------
    echo   Some required tools are missing. See docs\SETUP.md.
    echo   Most common fix: Tesseract is installed but not on PATH.
    echo  ----------------------------------------------------------
    echo.
    choice /c YN /m "  Continue anyway"
    if errorlevel 2 exit /b 1
    echo.
)

REM ---------- Work out which folder to process ----------
set "TARGET=%~1"

if "%TARGET%"=="" (
    echo  Which folder holds your PDFs?
    echo.
    echo    Tip: in File Explorer, hold Shift, right-click the folder,
    echo         and choose "Copy as path", then right-click here to paste.
    echo.
    set /p "TARGET=  Folder path: "
)

REM Strip surrounding quotes if present. Guard with `if defined`: on an
REM undefined TARGET (empty prompt input) the substitution would otherwise
REM leave the literal text `"=` behind and defeat the empty-check below.
if defined TARGET set "TARGET=!TARGET:"=!"

REM Strip a trailing backslash (a typed/pasted "C:\books\" makes the closing
REM quote an escaped quote on the python command line), but never collapse a
REM drive root like C:\ into C:.
if defined TARGET if "!TARGET:~-1!"=="\" if not "!TARGET:~-2!"==":\" set "TARGET=!TARGET:~0,-1!"

if "!TARGET!"=="" (
    echo.
    echo  [X] No folder given. Nothing to do.
    echo.
    pause
    exit /b 1
)

if not exist "!TARGET!" (
    echo.
    echo  [X] That path does not exist:
    echo      !TARGET!
    echo.
    pause
    exit /b 1
)

REM ---------- If a single PDF was given, use its parent folder ----------
REM  Test the resolved TARGET (works for both drag-drop and typed paths),
REM  not %~x1, which is empty when the path was typed at the prompt.
set "TARGET_EXT="
for %%F in ("!TARGET!") do set "TARGET_EXT=%%~xF"
if /i "!TARGET_EXT!"==".pdf" if not exist "!TARGET!\" (
    for %%F in ("!TARGET!") do set "TARGET=%%~dpF"
    if "!TARGET:~-1!"=="\" if not "!TARGET:~-2!"==":\" set "TARGET=!TARGET:~0,-1!"
    echo  A single PDF was given. Processing its whole folder instead:
    echo    !TARGET!
    echo.
)

set "OUTDIR=!TARGET!\extracted"

echo.
echo  ----------------------------------------------------------
echo   Source:  !TARGET!
echo   Output:  !OUTDIR!
echo  ----------------------------------------------------------
echo.
echo   Already-processed files are skipped, so this is safe to re-run.
echo   Large scanned books take a few minutes each (OCR is the slow part).
echo.
pause
echo.

python preprocess_pdf.py "!TARGET!" --out-dir "!OUTDIR!"
set "STATUS=!errorlevel!"

echo.
echo  ==========================================================
if "!STATUS!"=="0" (
    echo   Done.
) else (
    echo   Finished with errors ^(exit code !STATUS!^). See output above.
)
echo.
echo   Your text files are in:
echo     !OUTDIR!
echo.
echo   NEXT: open a .txt file and read the QUALITY REPORT at the
echo   top before quoting anything from it. See docs\QUALITY.md.
echo  ==========================================================
echo.

choice /c YN /m "  Open the output folder now"
if not errorlevel 2 start "" "!OUTDIR!"

echo.
pause
exit /b !STATUS!
