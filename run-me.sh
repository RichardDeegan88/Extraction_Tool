#!/usr/bin/env bash
# ===================================================================
#  ACSC Reading Toolkit - launcher for macOS and Linux
#
#  Usage:
#     ./run-me.sh                     prompts for a folder
#     ./run-me.sh /path/to/pdfs       processes that folder
#
#  First time only, make it executable:
#     chmod +x run-me.sh
# ===================================================================

set -uo pipefail

cd "$(dirname "$0")" || exit 1

echo
echo "  =========================================================="
echo "   ACSC Reading Toolkit"
echo "   Turns PDF books into complete, searchable text files"
echo "  =========================================================="
echo

# ---------- Find a usable Python ----------
PY=""
for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
        if "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3,9) else 1)' 2>/dev/null; then
            PY="$candidate"
            break
        fi
    fi
done

if [ -z "$PY" ]; then
    echo "  [X] Python 3.9 or newer was not found."
    echo
    echo "      macOS:  brew install python"
    echo "      Linux:  sudo apt install python3"
    echo
    exit 1
fi

# ---------- Check the script is beside this launcher ----------
if [ ! -f "preprocess_pdf.py" ]; then
    echo "  [X] preprocess_pdf.py was not found in this folder."
    echo
    echo "      Keep run-me.sh in the same folder as the scripts."
    echo "      This folder is: $(pwd)"
    echo
    exit 1
fi

# ---------- Dependency check ----------
echo "  Checking required tools..."
echo
CHECK_OUTPUT="$("$PY" preprocess_pdf.py --check 2>&1)"
echo "$CHECK_OUTPUT"
echo

# Match on the string directly rather than piping into `grep -q`: under
# `set -o pipefail`, grep closing the pipe early can make the pipeline return
# 141 (SIGPIPE) and swallow the warning exactly when it matched.
case "$CHECK_OUTPUT" in
    *"Some required tools are missing"*)
        echo "  ----------------------------------------------------------"
        echo "   Some required tools are missing. See docs/SETUP.md."
        echo "   macOS:  brew install poppler tesseract imagemagick"
        echo "   Linux:  sudo apt install poppler-utils tesseract-ocr imagemagick"
        echo "  ----------------------------------------------------------"
        echo
        printf "  Continue anyway? [y/N] "
        read -r reply
        case "$reply" in
            [Yy]*) echo ;;
            *) exit 1 ;;
        esac
        ;;
esac

# ---------- Work out which folder to process ----------
TARGET="${1:-}"

if [ -z "$TARGET" ]; then
    echo "  Which folder holds your PDFs?"
    echo
    echo "    Tip: you can drag a folder from Finder into this window"
    echo "         to paste its path."
    echo
    printf "  Folder path: "
    read -r TARGET
fi

# Strip surrounding quotes that drag-and-drop or copy-paste may add
TARGET="${TARGET%\"}"; TARGET="${TARGET#\"}"
TARGET="${TARGET%\'}"; TARGET="${TARGET#\'}"
# macOS Terminal escapes spaces in a dragged path as "\ "; unescape them, and
# trim any trailing whitespace a drag leaves behind — otherwise the advertised
# "drag a folder from Finder" tip fails for any path containing a space.
TARGET="${TARGET//\\ / }"
TARGET="${TARGET%"${TARGET##*[![:space:]]}"}"
# Expand a leading ~
case "$TARGET" in "~"*) TARGET="${HOME}${TARGET#\~}";; esac

if [ -z "$TARGET" ]; then
    echo
    echo "  [X] No folder given. Nothing to do."
    exit 1
fi

# If a single PDF was given, use its parent folder
case "$TARGET" in
    *.pdf|*.PDF)
        if [ -f "$TARGET" ]; then
            TARGET="$(dirname "$TARGET")"
            echo
            echo "  A single PDF was given. Processing its whole folder instead:"
            echo "    $TARGET"
        fi
        ;;
esac

if [ ! -d "$TARGET" ]; then
    echo
    echo "  [X] That folder does not exist:"
    echo "      $TARGET"
    exit 1
fi

OUTDIR="$TARGET/extracted"

echo
echo "  ----------------------------------------------------------"
echo "   Source:  $TARGET"
echo "   Output:  $OUTDIR"
echo "  ----------------------------------------------------------"
echo
echo "   Already-processed files are skipped, so this is safe to re-run."
echo "   Large scanned books take a few minutes each (OCR is the slow part)."
echo
printf "  Press Enter to start, or Ctrl+C to cancel... "
read -r _
echo

"$PY" preprocess_pdf.py "$TARGET" --out-dir "$OUTDIR"
STATUS=$?

echo
echo "  =========================================================="
if [ $STATUS -eq 0 ]; then
    echo "   Done."
else
    echo "   Finished with errors (exit code $STATUS). See output above."
fi
echo
echo "   Your text files are in:"
echo "     $OUTDIR"
echo
echo "   NEXT: open a .txt file and read the QUALITY REPORT at the"
echo "   top before quoting anything from it. See docs/QUALITY.md."
echo "  =========================================================="
echo

# ---------- Offer to open the output folder ----------
if [ -d "$OUTDIR" ]; then
    printf "  Open the output folder now? [y/N] "
    read -r openreply
    case "$openreply" in
        [Yy]*)
            if command -v open >/dev/null 2>&1; then
                open "$OUTDIR"            # macOS
            elif command -v xdg-open >/dev/null 2>&1; then
                xdg-open "$OUTDIR"        # Linux
            else
                echo "  (Could not detect a file manager. Path is above.)"
            fi
            ;;
    esac
fi

exit $STATUS
