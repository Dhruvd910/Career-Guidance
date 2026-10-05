"""Which language the student is using — English, Hindi or Hinglish — so MAYA answers in the
same one, and with the right voice.

Three signals, in order of trust:
- the script: Devanagari is Hindi (or Hinglish, if it carries enough English words);
- for Latin text, how many of its words are Hindi written in English letters ("mujhe samajh
  nahi aa raha") — the case a script check alone used to call English;
- what Whisper heard, and the student's recent language, for replies too short to judge
  ("ok", "haan").

The reply mirrors the current turn (spec §4): switching language mid-conversation just works.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

ENGLISH, HINDI, HINGLISH = "en", "hi", "hinglish"
LATIN, DEVANAGARI = "latn", "deva"

# Whisper's names for what it heard. Spoken Hindi and Urdu are near-identical, and Whisper
# often calls Hindi speech "urdu" — either way the student gets a Hindi reply.
_WHISPER_HINDI = {"hindi", "urdu", "hi", "ur"}

# Hindi written in English letters: common words that aren't also English words. Words that
# are both ("main" as in "JEE Main", "to", "me", "hi", "is", "the", "do", "par") are AMBIGUOUS
# and count for neither side.
ROMAN_HINDI = frozenset("""
mujhe mujhko mujhse mera meri mere hum humein hamein hamara hamari hamare tum tumhe tumhein
tumko tumse tumhara tumhari tumhare aap aapka aapki aapke aapko aapse woh wo vo voh yeh ye
unka unki unke unko usko uska uski uske inka inki apna apni apne kuch koi kisi kisko sab
sabko sabki sabke sabse sabhi khud yahan wahan idhar udhar kahin kahi
hai hain hoon hun hu tha thi thay ho hua hui hue hoga hogi honge hota hoti hote raha rahi rahe rha
rhi rhe karna karni karne karo karu karun karta karti karte kar kiya kiye kari krna krni
karunga karungi karenge chahiye chahta chahti chahte sakta sakti sakte skta sakun pata
samajh samjha samjhi samjho samjhao bata batao bataiye batana batado dekh dekho dekhte
dekhna padh padhai padhna padhta padhti padhte jaana jana jaun jau jata jati jaati jaate
gaya gayi gaye aana aata aati aate aa aaya aayi mil milega milegi milta milti lena lu loon
lo dena dedo dijiye lagta lagti lagte laga lagi rehna rehta soch sochta sochti socha
banna banu bano banta banti bante banega banegi banenge bol bolo bolna suno sunao pucho
puchna poochna
nahi nahin nhi na kya kyu kyun kyon kyunki kaise kaisa kaisi kaun kaunsa kaunsi kaunse
konsa konsi konse kab kahan kidhar kitna kitni kitne
ka ki ke ko se mein mai pe aur ya lekin magar toh phir fir agar jab abhi bhi sirf bas
bahut bohot bahot zyada jyada thoda accha acha achha acchi achhi theek thik sahi galat
bilkul haan ha ji yaar bhai didi matlab waise shayad zaroor jarur sach wala wali wale liye
saath baad pehle pahle aaj roz saal ghar dost logon naukri kaam paisa paise mehnat
darr dar mushkil asaan aasan pasand chalo chaliye koshish samay waqt kabhi hamesha humesha
jaise aisa aise aisi waisa kaafi kafi zaruri jaruri baat baatein cheez sawal jawab pareshan
pareshaan tayari taiyari dimag dimaag aas paas
maine mainne humne tumne aapne usne unhone isko isse usse tera teri tere poora pura poori puri
liya lia diya diye dia khatam chuka chuki chuke kal
""".split())
AMBIGUOUS = frozenset("main to me hi is us the do so he an in use par log mat tab din".split())

_LATIN_WORD = re.compile(r"[A-Za-z]+")
_DEVANAGARI_WORD = re.compile(r"[ऀ-ॿ]+")


@dataclass(frozen=True)
class LanguageTag:
    lang: str  # en | hi | hinglish
    script: str  # latn | deva
    confidence: float  # 0..1 — low for a word or two

    @property
    def voice(self) -> str:
        return voice_for(self.lang)


def voice_for(lang: str | None) -> str:
    """The TTS language for a reply in `lang`: Cartesia's Hindi voice reads Hindi and Hinglish
    in either script (spike S1); its English voice mangles Hindi words."""
    return HINDI if lang in (HINDI, HINGLISH) else ENGLISH


def has_devanagari(text: str) -> bool:
    return any("ऀ" <= ch <= "ॿ" for ch in text)


def language_of_text(text: str) -> str:
    """Hindi when at least a fifth of the letters are Devanagari: a Hindi sentence with
    "JEE" or "IIT Delhi" in it is still Hindi, an English one quoting a Hindi word is not.
    Only the script — use detect() for anything a student said."""
    letters = [ch for ch in text if ch.isalpha()]
    if not letters:
        return ENGLISH
    devanagari = sum(1 for ch in letters if "ऀ" <= ch <= "ॿ")
    return HINDI if devanagari / len(letters) >= 0.2 else ENGLISH


def language_from_whisper(name: str | None) -> str:
    return HINDI if (name or "").strip().lower() in _WHISPER_HINDI else ENGLISH


def detect(text: str, heard: str | None = None, previous: str | None = None) -> LanguageTag:
    """What the student is speaking. `heard` is Whisper's language for spoken input ("en"/"hi");
    `previous` is their recent language, used when the text is too short to tell."""
    if language_of_text(text) == HINDI:
        words = _DEVANAGARI_WORD.findall(text) + _LATIN_WORD.findall(text)
        # Lower-case English words are code-mixing ("engineering", "option"); capitalised ones
        # are mostly names ("IIT Delhi"), which a Hindi sentence carries anyway.
        mixed = [w for w in _LATIN_WORD.findall(text) if w.islower() and len(w) > 1]
        lang = HINGLISH if words and len(mixed) / len(words) >= 0.15 else HINDI
        return LanguageTag(lang, DEVANAGARI, 1.0)

    hindi = english = 0
    for word in _LATIN_WORD.findall(text):
        low = word.lower()
        if low in AMBIGUOUS or (word.isupper() and len(word) <= 5):  # JEE, NEET, PCM, AI
            continue
        if low in ROMAN_HINDI:
            hindi += 1
        else:
            english += 1
    counted = hindi + english
    if counted == 0:
        lang = previous or heard or ENGLISH
        return LanguageTag(lang, LATIN, 0.0)
    lang = HINGLISH if hindi / counted >= 0.3 else ENGLISH
    confidence = min(1.0, counted / 4)
    if confidence < 0.5 and previous and previous != lang:
        # "ok" from someone who has been speaking Hindi is still a Hindi conversation.
        return LanguageTag(previous, LATIN, confidence)
    return LanguageTag(lang, LATIN, confidence)


# How fast the running language mix follows the latest turns.
_HABIT_WEIGHT = 0.3


def usual_language(stats: dict | None) -> str | None:
    """The language a student mostly uses, if any clearly dominates."""
    if not stats:
        return None
    lang, weight = max(stats.items(), key=lambda kv: kv[1])
    return lang if weight >= 0.5 else None


def updated_stats(stats: dict | None, tag: LanguageTag) -> dict | None:
    """The running mix after this turn. A word or two says too little to count."""
    if tag.confidence < 0.5:
        return stats
    stats = dict(stats or {})
    for lang in (ENGLISH, HINDI, HINGLISH):
        stats[lang] = round((1 - _HABIT_WEIGHT) * stats.get(lang, 0.0) + _HABIT_WEIGHT * (lang == tag.lang), 3)
    return stats


_SPOKEN = "Your reply will be read aloud: keep it short, with no lists, tables or symbols."
# Hindi verbs carry gender. A name says nothing reliable about it, so the student is addressed in the
# plural forms that don't assume one — only their own words ("main karti hoon") can say otherwise.
_NEUTRAL = (" Talk to the student in plural verb forms that don't assume a gender (tum karte ho, kar sakte ho, "
            "aap chahenge) — never feminine or masculine singular ones (karti ho, sakti ho, chahengi, karta hai) "
            "unless they have used them about themselves. For yourself, feminine forms (main batati hoon).")

_HINDI_REGISTER = (
    "conversational Hindi the way Indian students actually talk — simple everyday words, not "
    "formal or bookish Hindi — keeping common English words in English (career, college, "
    "subject, option, exam names, JEE, NEET, IIT, cutoff, rank)"
)


def reply_instruction(tag: LanguageTag) -> str:
    """Added to the conversation just before the student's message, so it wins over the
    language of everything said earlier in the same chat."""
    if tag.lang == ENGLISH:
        return "The student is speaking English. Reply in English. " + _SPOKEN
    who = "Hinglish (Hindi mixed with English)" if tag.lang == HINGLISH else "Hindi"
    if tag.script == LATIN:
        return (f"The student is writing {who} in English letters. Reply the same way: "
                f"{_HINDI_REGISTER}, all written in English letters (Roman script), as they wrote. "
                + _SPOKEN + _NEUTRAL)
    return (f"The student is speaking {who}. Reply in {_HINDI_REGISTER}. Write Hindi words in "
            "Devanagari script — never Urdu script — and English words in English letters. " + _SPOKEN + _NEUTRAL)
