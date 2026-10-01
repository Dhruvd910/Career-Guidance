"""Cutting a reply into speakable sentences while it is still being generated.

Each sentence goes to the voice as soon as it is complete, so MAYA starts talking after the
first one instead of after the whole reply. A cut needs to see what follows a full stop —
"₹1.5 lakh", "B.Tech", "Dr. Rao" and "nta.ac.in" are not sentence ends — so the last few
characters of the stream wait for the next piece, and flush() releases them at the end.
"""

from __future__ import annotations

import re

ENDERS = ".?!।॥"
_CLOSERS = "\"')”’"
# Words that take a full stop without ending the sentence.
ABBREVIATIONS = {"dr", "mr", "mrs", "ms", "prof", "st", "sr", "jr", "vs", "no", "approx", "govt", "dept", "inst"}
SOFT_BREAKS = (", ", "; ", ": ", " — ", " – ")
MAX_CHARS = 220  # beyond this a sentence is cut at a comma: long ones delay the first audio

_MARKUP = re.compile(r"[*_`#]+")
_LIST_MARKER = re.compile(r"^\s*(?:[-•]|\d+[.)])\s+", re.MULTILINE)
_SPACES = re.compile(r"\s+")


def speakable(text: str) -> str:
    """Strips what a voice can't say: markdown emphasis, headings, list markers."""
    text = _LIST_MARKER.sub("", text)
    text = _MARKUP.sub("", text)
    return _SPACES.sub(" ", text).strip()


class SentenceSplitter:
    def __init__(self, max_chars: int = MAX_CHARS):
        self.max_chars = max_chars
        self.buffer = ""

    def feed(self, text: str) -> list[str]:
        """Adds a piece of the stream; returns the sentences it completed."""
        self.buffer += text
        sentences = []
        while (cut := self._find_cut()) is not None:
            piece, self.buffer = self.buffer[:cut], self.buffer[cut:]
            if sentence := _keep(piece):
                sentences.append(sentence)
        return sentences

    def flush(self) -> list[str]:
        """The end of the stream: whatever is left is the last sentence."""
        piece, self.buffer = self.buffer, ""
        sentence = _keep(piece)
        return [sentence] if sentence else []

    def _find_cut(self) -> int | None:
        b = self.buffer
        for i, ch in enumerate(b):
            if ch == "\n" and b[:i].strip():
                return i + 1  # a paragraph or list item ends here
            if ch not in ENDERS:
                continue
            end = i
            while end + 1 < len(b) and b[end + 1] in ENDERS + _CLOSERS:  # "?!", "...", '."'
                end += 1
            if end + 1 >= len(b):
                return None  # can't tell yet: "1." might become "1.5"
            if not b[end + 1].isspace():
                continue  # "B.Tech", "1.5", "nta.ac.in"
            if ch == "." and _abbreviation(b[:i]):
                continue
            return end + 1
        if len(b) > self.max_chars:
            soft = max(b.rfind(p, 0, self.max_chars) for p in SOFT_BREAKS)
            if soft > self.max_chars // 4:
                return soft + 1
            space = b.rfind(" ", 0, self.max_chars)
            if space > 0:
                return space + 1
        return None


def _abbreviation(before: str) -> bool:
    match = re.search(r"(\S+)$", before)
    if not match:
        return False
    word = match.group(1).lstrip("([\"'")
    line_start = before[: match.start()].rsplit("\n", 1)[-1].strip() == ""
    return (
        "." in word  # "B.Sc", "e.g", "i.e"
        or word.lower() in ABBREVIATIONS
        or (len(word) == 1 and word.isupper())  # an initial: "A. P. J. Abdul Kalam"
        or (word.isdigit() and line_start)  # "1." starting a list item
    )


def _keep(piece: str) -> str | None:
    sentence = speakable(piece)
    return sentence if any(ch.isalnum() for ch in sentence) else None
