"""When a student says something that suggests they may be unsafe — thinking of ending their life,
hurting themselves, being abused — career counselling stops and care comes first.

This check runs on every message, synchronously, before the reply is written: it has to change
*this* reply, so it can't wait for an LLM's opinion. It errs towards triggering — an unneeded
caring reply costs little, a missed one could cost a great deal — and it never diagnoses, scores
or stores anything. The main prompt carries the same rule, so the model can also respond to
phrasings this list doesn't know.
"""

from __future__ import annotations

import re

HELPLINE = "Tele-MANAS, 14416 (free, 24x7, in Indian languages)"

# Phrases, not single words: "kill" is in "skill", "die" in "studied" and "die-hard".
_SELF_HARM = [
    # English
    "kill myself", "end my life", "end it all", "suicide", "suicidal", "want to die", "wanna die",
    "don't want to live", "dont want to live", "no reason to live", "better off dead", "hurt myself",
    "harm myself", "self harm", "self-harm", "cut myself", "not worth living",
    # Hinglish
    "mar jaana chahta", "mar jaana chahti", "mar jana chahta", "mar jana chahti", "marna chahta",
    "marna chahti", "mar jaunga", "mar jaungi", "jeena nahi chahta", "jeena nahi chahti",
    "zindagi khatam", "zindagi se thak", "khud ko khatam", "khudkushi", "aatmhatya", "atmahatya",
    "suicide kar",
    # Hindi
    "आत्महत्या", "ख़ुदकुशी", "खुदकुशी", "मर जाना चाहता", "मर जाना चाहती", "मरना चाहता", "मरना चाहती",
    "जीना नहीं चाहता", "जीना नहीं चाहती", "ज़िंदगी खत्म", "जिंदगी खत्म", "खुद को खत्म", "ख़ुद को ख़त्म",
]
_ABUSE = [
    # English
    "abuses me", "abused me", "being abused", "beats me", "hits me", "touches me", "touched me",
    "molest", "harasses me", "harassed me",
    # Hinglish
    "mujhe maarte", "mujhe marte", "mujhe peet", "mujhe pit", "galat tarike se chhu", "galat tareeke se chhu",
    # Hindi
    "मुझे मारते", "मुझे पीटते", "गलत तरीके से छू", "ग़लत तरीके से छू",
]

_SPACES = re.compile(r"\s+")


def concern(text: str) -> str | None:
    """'self_harm', 'abuse', or None."""
    t = _SPACES.sub(" ", text.lower())
    if any(p in t for p in _SELF_HARM):
        return "self_harm"
    if any(p in t for p in _ABUSE):
        return "abuse"
    return None


INSTRUCTION = {
    "self_harm": (
        "IMPORTANT: The student's message may mean they are thinking about ending their life or hurting "
        "themselves. Put career topics aside. Respond with warmth and without judgement: say you're glad they "
        "told you and that they don't have to face this alone. Gently encourage them to talk right now to a "
        f"trusted adult — a parent, a teacher, a school counsellor — and give them {HELPLINE}. If they are in "
        "immediate danger, they should call 112. Don't diagnose, don't lecture, don't promise secrecy, and never "
        "tell them how they should or shouldn't feel. Keep it short and kind, and ask if they are safe right now."
    ),
    "abuse": (
        "IMPORTANT: The student's message may mean someone is hurting or abusing them. Put career topics aside. "
        "Respond with care: thank them for telling you, say it is not their fault, and encourage them to tell a "
        "trusted adult — a teacher, a school counsellor, a relative. Give Childline 1098 (free, 24x7, for "
        f"children) and {HELPLINE}; if they are in immediate danger, 112. Don't ask for details, don't diagnose, "
        "don't promise secrecy, never tell them how they should feel. Ask if they are safe right now."
    ),
}
