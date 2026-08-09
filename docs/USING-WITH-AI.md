# Using extracted text with an AI assistant

The extraction solves one problem: the assistant can now see the whole book.
It does not solve the harder one, which is that an assistant asked to summarise
something it only partly read will produce a confident summary of the part it
read.

This doc is about not getting fooled by your own tooling.

---

## First: check your institution's policy

Air University and most PME institutions have a generative AI policy governing
what tools may be used, what must be disclosed, and what counts as academic
integrity. **Read it before using any of this on graded work.** Nothing here
overrides it, and "the tool made it easy" is not a defence.

The safe general position: an assistant helping you *read and understand*
assigned material is usually fine. An assistant *writing your submitted prose*
usually is not. Know where your institution draws the line.

---

## The core technique: feed ranges, not books

Do not paste a whole book. Two reasons: it truncates, and even when it doesn't,
attention spreads thin across 300,000 words and detail gets lost.

Instead, pull the assigned range and paste that:

```bash
grep -n "^--- PAGE 227 " Clausewitz.txt     # find the line number
sed -n '8371,8900p' Clausewitz.txt          # print the range
```

A few thousand words fits comfortably and gets read properly.

---

## Prompts that work

**Reading an assigned range.** Give it the range, then ask for structure rather
than a summary:

> Here is Clausewitz, On War, Book Three chapters 16-18 (pp. 227-241, Howard/Paret).
> For each chapter give me: the central claim in one sentence, the supporting
> propositions in the order he builds them, any qualification he attaches to a
> claim, and the specific examples he uses. Quote only where his exact wording
> carries weight a paraphrase would lose. Where you are inferring rather than
> reporting what he says, mark it.

**Comparing authors.** Paste both ranges, then:

> These are Clausewitz on the culminating point and Jomini on lines of operation.
> Where do they actually disagree, as opposed to using different vocabulary for
> the same idea? Where does one qualify something the other states flatly?

**Testing yourself.** After you've read it:

> Ask me six questions on this range: two comprehension, two comparison, two
> application. Don't give me the answers until I've attempted each one.

---

## Prompts that produce confident nonsense

**"Summarise this book."** Against a whole book it truncates. Against a range
it's vague. Ask for structure, not summary.

**"What does Clausewitz say about X?"** with no text supplied. The assistant
answers from training data, which mixes translations and editions. Your course
cites a specific one. Supply the text.

**"Find the quote about friction."** It will produce a plausible quotation.
Plausible is not the same as present in your edition. Search the text yourself:

```bash
grep -n -i "friction" Clausewitz.txt
```

Then paste the surrounding lines and ask about *those*.

---

## The verification habit

Three rules, in order of how much trouble they save:

**1. Every quotation gets checked against the text file.** Not against the
assistant's memory. Search for a distinctive phrase; if it isn't there, it isn't
in your edition.

```bash
grep -n "act of force to compel" Clausewitz.txt
```

**2. Every page reference gets checked against a page marker.** Confirm the
claim is actually on the page cited, not merely nearby.

**3. Quotations from `[OCR]` pages get checked against the PDF.** OCR
misreads characters. See `QUALITY.md`.

---

## The failure this whole toolkit exists to prevent

An assistant reading a truncated book produces a summary that is fluent,
well-organised, plausible, and covers roughly the first seven percent of the
argument. Nothing about it looks wrong. You find out in seminar.

Extraction removes the truncation. It does not remove the related failure of
*sampling*: asking for a whole-book summary from a few scattered pages produces
a summary capped at the depth of the sample, however much prose gets written
around it.

The fix is the same in both cases: **read in ranges, verify against the text,
and be suspicious of fluency**. A summary that reads well tells you nothing
about whether the source was read well.

---

## A reasonable division of labour

| Do yourself | Delegate |
|---|---|
| Deciding what the argument means | Locating passages on a topic |
| Judging which reading is stronger | Restructuring your notes |
| Anything submitted for a grade | Generating practice questions |
| Verifying every quotation | Drafting a comparison table you'll check |

The extracted text makes the second column fast. The first column is the course.
