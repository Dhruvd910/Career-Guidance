"""English or Hindi: which one the student is speaking, so MAYA answers in the same one.

Only these two. Whisper names the language it heard; for typed text (and for picking the
voice to read a reply with) the script decides — Devanagari is Hindi, anything else English.
"""

ENGLISH, HINDI = "en", "hi"

# Whisper's names for what it heard. Spoken Hindi and Urdu are near-identical, and Whisper
# often calls Hindi speech "urdu" — either way the student gets a Hindi reply.
_WHISPER_HINDI = {"hindi", "urdu", "hi", "ur"}


def has_devanagari(text: str) -> bool:
    return any("ऀ" <= ch <= "ॿ" for ch in text)


def language_of_text(text: str) -> str:
    """Hindi when at least a fifth of the letters are Devanagari: a Hindi sentence with
    "JEE" or "IIT Delhi" in it is still Hindi, an English one quoting a Hindi word is not."""
    letters = [ch for ch in text if ch.isalpha()]
    if not letters:
        return ENGLISH
    devanagari = sum(1 for ch in letters if "ऀ" <= ch <= "ॿ")
    return HINDI if devanagari / len(letters) >= 0.2 else ENGLISH


def language_from_whisper(name: str | None) -> str:
    return HINDI if (name or "").strip().lower() in _WHISPER_HINDI else ENGLISH


# Added to the conversation just before the student's message, so it wins over the language
# of everything said earlier in the same chat.
REPLY_INSTRUCTIONS = {
    HINDI: (
        "The student is speaking Hindi. Reply in simple, natural spoken Hindi written in Devanagari "
        "script — never Urdu script and never Hindi in English letters. Keep names of exams, "
        "colleges and technical terms (JEE, NEET, IIT, cutoff, rank) as they are usually said. "
        "Your reply will be read aloud, so avoid tables and long lists."
    ),
    ENGLISH: "The student is speaking English. Reply in English.",
}
