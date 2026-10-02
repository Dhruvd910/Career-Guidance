"""The money guard (docs/design/15-phase6-plan.md, P6-11; spec §23: never fabricate fees).

Before a sentence of MAYA's is spoken or shown, every rupee amount in it must be one this
conversation has actually seen — in a tool's result or in the student's own words — or that
amount for another period (₹62,500 a semester is ₹1,25,000 a year), within 3% for rounding
("about ₹1.25 lakh"). A sentence with any other amount is replaced by an honest "I don't have a
verified figure for that". Text streams through it sentence by sentence, so the voice isn't held
up for more than a sentence.
"""

from __future__ import annotations

import logging
import re

log = logging.getLogger(__name__)

DEVANAGARI_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")
SCALE = {"lakh": 100_000, "lakhs": 100_000, "lac": 100_000, "lacs": 100_000, "लाख": 100_000,
         "crore": 10_000_000, "crores": 10_000_000, "cr": 10_000_000, "करोड़": 10_000_000, "करोड": 10_000_000,
         "thousand": 1_000, "hazaar": 1_000, "hazar": 1_000, "हज़ार": 1_000, "हजार": 1_000, "k": 1_000}
WORDS = {"one": 1, "ek": 1, "एक": 1, "two": 2, "do": 2, "दो": 2, "three": 3, "teen": 3, "तीन": 3, "four": 4, "char": 4,
         "chaar": 4, "चार": 4, "five": 5, "paanch": 5, "panch": 5, "पांच": 5, "पाँच": 5, "six": 6, "chhe": 6, "छह": 6,
         "seven": 7, "saat": 7, "सात": 7, "eight": 8, "aath": 8, "आठ": 8, "nine": 9, "nau": 9, "नौ": 9, "ten": 10, "das": 10,
         "दस": 10, "dedh": 1.5, "डेढ़": 1.5, "dhai": 2.5, "ढाई": 2.5, "half": 0.5}
NUM = r"\d[\d,]*(?:\.\d+)?"
SCALES = r"(lakhs?|lacs?|crores?|cr|thousand|hazaa?r|k|लाख|करोड़?|हज़ार|हजार)"
RUPEE = r"(?:₹|rs\.?|inr|rupees?|rupaye|rupay|रुपये|रुपए|रु\.?)"
PATTERNS = (
    re.compile(rf"{RUPEE}\s*({NUM})\s*{SCALES}?(?![\w])", re.I),  # ₹62,500 · Rs. 1.25 lakh
    re.compile(rf"(?<![\w.])({NUM})\s*{SCALES}(?![\w])\s*(?:{RUPEE})?", re.I),  # 1.25 lakh · 2 lakh rupaye
    re.compile(rf"(?<![\w.])({NUM})\s*{RUPEE}(?![\w])", re.I),  # 500 rupees
    re.compile(rf"(?<![\w])({'|'.join(sorted(WORDS, key=len, reverse=True))})\s+{SCALES}(?![\w])", re.I),  # do lakh
)
SENTENCE_END = re.compile(r"(?<=[.!?।])\s+|\n+")
ABBREVIATIONS = ("rs.", "no.", "dr.", "mr.", "mrs.", "st.", "approx.", "e.g.", "i.e.", "vs.", "रु.")
INSTEAD = {"en": "I don't have a verified figure for that.", "hi": "इसकी पक्की रकम मेरे पास नहीं है।",
           "hinglish": "Iski verified amount mere paas nahi hai."}


def _value(number: str) -> float:
    return float(WORDS.get(number.lower(), None) or number.replace(",", ""))


def amounts(text: str) -> list[int]:
    """The rupee amounts written in some text."""
    text = text.translate(DEVANAGARI_DIGITS)
    found, taken = [], []
    for pattern in PATTERNS:
        for m in pattern.finditer(text):
            if any(a < m.end() and m.start() < b for a, b in taken):
                continue
            number, scale = m.group(1), (m.group(2) if m.lastindex and m.lastindex >= 2 else None)
            try:
                value = _value(number) * SCALE.get((scale or "").lower(), 1)
            except ValueError:
                continue
            if value >= 1:
                found.append(int(round(value)))
                taken.append((m.start(), m.end()))
    return found


def numbers(text: str) -> set[int]:
    """Every number in a tool's result (its JSON has bare amounts: "amount": 62500), and its amounts."""
    text = text.translate(DEVANAGARI_DIGITS)
    plain = {int(round(float(n.replace(",", "")))) for n in re.findall(rf"(?<![\w.]){NUM}", text)
             if n.replace(",", "").replace(".", "", 1).isdigit()}
    return {n for n in plain if n >= 1} | set(amounts(text))


class Guard:
    def __init__(self, seen: list[str] | None = None, lang: str = "en"):
        self.allowed: set[int] = set()
        self.lang = lang if lang in INSTEAD else "en"
        self.buffer = ""
        self.replaced: list[str] = []
        for text in seen or []:
            self.allow(text)

    def allow(self, text: str) -> None:
        self.allowed |= numbers(text or "")

    def _known(self, amount: int) -> bool:
        for a in self.allowed:
            for candidate in (a, a * 2, a * 12, a / 2, a / 12):
                if candidate and abs(amount - candidate) <= 0.03 * candidate:
                    return True
        return False

    def check(self, sentence: str) -> str:
        unknown = [a for a in amounts(sentence) if not self._known(a)]
        if not unknown:
            return sentence
        self.replaced.append(sentence.strip())
        log.warning("money guard: replaced a sentence with unverified amounts %s", unknown)
        trailing = sentence[len(sentence.rstrip()):]
        return INSTEAD[self.lang] + (trailing or " ")

    def feed(self, piece: str) -> list[str]:
        """Text in; the complete sentences so far out, each checked."""
        self.buffer += piece
        out = []
        while True:
            m = next((m for m in SENTENCE_END.finditer(self.buffer)
                      if not self.buffer[:m.start()].lower().endswith(ABBREVIATIONS)), None)
            if m is None:
                return out
            sentence, self.buffer = self.buffer[:m.end()], self.buffer[m.end():]
            out.append(self.check(sentence))

    def flush(self) -> str:
        rest, self.buffer = self.buffer, ""
        return self.check(rest) if rest.strip() else rest
