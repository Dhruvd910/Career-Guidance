"""Turn short spoken answers into form values.

Whisper transcribes naturally — "My name is Dhruv.", "Myself Priya", "I'm in eleventh",
"plus two" — so these strip the conversational wrapper and map number words. They stay
deliberately simple because MAYA only ever asks one narrow question at a time.
"""

from __future__ import annotations

import re

# Whisper's well-known outputs for silence, breathing, or room noise — never a real answer.
_HALLUCINATIONS = {
    "", "you", "thank you", "thanks", "thank you so much", "thanks for watching",
    "thank you for watching", "bye", "okay", "ok", "hmm", "um", "uh",
    "subtitles by the amaraorg community",
}


def _normalize(text: str) -> str:
    return re.sub(r"[^\w\s]", "", text or "").strip().lower()


def is_meaningful(transcript: str | None) -> bool:
    return _normalize(transcript or "") not in _HALLUCINATIONS


def clean_dictation(transcript: str) -> str:
    """For inserting dictated text into a single-line field: Whisper ends most utterances
    with a period, which nobody wants typed into a 'State' box."""
    return re.sub(r"[.!?]+$", "", (transcript or "").strip()).strip()


# ---------------- names ----------------

# Longest first, so "my good name is" wins over "my name is" and "i'm called" over "i'm".
_NAME_LEAD_INS = [
    "you can call me", "they call me", "my good name is", "my name is", "my name's",
    "the name is", "name is", "i am called", "i'm called", "call me", "this is", "it is",
    "it's", "i am", "i'm", "myself",
]
# Greetings/fillers people say *before* their name. Stripped from the front before splitting
# into clauses, otherwise "Hello, my name is Dhruv" would stop at "Hello".
_LEADING_FILLER = re.compile(r"^(hello|hi|hey|okay|ok|so|um+|uh+|yeah|yes|well|maya)\b[\s,.!]*", re.IGNORECASE)
# Not included: "maya" — a student can be named Maya.
_INNER_FILLERS = {"um", "uh", "yeah", "okay", "ok", "hello", "hi", "hey"}
_TRAILING = [" this side", " here", " only", " speaking"]


def extract_name(transcript: str) -> str | None:
    if not is_meaningful(transcript):
        return None

    text = transcript.strip()
    while True:
        stripped = _LEADING_FILLER.sub("", text, count=1)
        if stripped == text:
            break
        text = stripped

    # Only the first clause: "My name is Dhruv and I'm in class 11." -> "My name is Dhruv"
    lowered = re.split(r"[,.;!?]| and | but ", text, maxsplit=1)[0].strip().lower()

    for lead in _NAME_LEAD_INS:
        if lowered == lead:
            return None
        if lowered.startswith(lead + " "):
            lowered = lowered[len(lead) + 1:]
            break

    for tail in _TRAILING:
        if lowered.endswith(tail):
            lowered = lowered[: -len(tail)]

    name_words = [w for w in re.sub(r"[^a-z\s'-]", " ", lowered).split() if w not in _INNER_FILLERS]
    if not name_words:
        return None
    return " ".join(w.capitalize() for w in name_words[:3])


# ---------------- class level ----------------

_CLASS_WORDS = {
    "eight": 8, "eighth": 8, "nine": 9, "ninth": 9, "ten": 10, "tenth": 10,
    "eleven": 11, "eleventh": 11, "twelve": 12, "twelfth": 12,
}
# Regional names for classes 11/12: Kerala/TN "plus one/two", Karnataka PUC, AP/Telangana "inter".
_CLASS_PHRASES = [
    (r"\bplus\s*(one|1)\b|\+\s*1\b", 11),
    (r"\bplus\s*(two|2)\b|\+\s*2\b", 12),
    (r"\b(first|1st)\s+(year\s+)?(puc|pu)\b|\binter(mediate)?\s+(first|1st)\s+year\b", 11),
    (r"\b(second|2nd)\s+(year\s+)?(puc|pu)\b|\binter(mediate)?\s+(second|2nd)\s+year\b", 12),
]


def parse_class(transcript: str) -> int | None:
    if not is_meaningful(transcript):
        return None
    text = transcript.lower()
    for pattern, level in _CLASS_PHRASES:
        if re.search(pattern, text):
            return level
    digit = re.search(r"\b(8|9|10|11|12)(st|nd|rd|th)?\b", text)
    if digit:
        return int(digit.group(1))
    for word in re.findall(r"[a-z]+", text):
        if word in _CLASS_WORDS:
            return _CLASS_WORDS[word]
    return None


# ---------------- yes / no ----------------

_NO_PATTERNS = [
    r"\bnot sure\b", r"\bdon'?t know\b", r"\bdo not know\b", r"\bno idea\b", r"\bnot yet\b",
    r"\bconfused\b", r"\bnope\b", r"\bnah\b", r"\bnahi+n?\b", r"\bno\b",
]
_YES_PATTERNS = [
    r"\byes\b", r"\byeah\b", r"\byep\b", r"\byup\b", r"\bsure\b", r"\bdefinitely\b",
    r"\bof course\b", r"\bi do\b", r"\bi know\b", r"\bcorrect\b", r"\bhaa?n?\b",
]


_UNSURE_PATTERNS = [r"\bnot sure\b", r"\bdon'?t know\b", r"\bdo not know\b", r"\bno idea\b", r"\bdunno\b", r"\bconfused\b"]


def is_unsure(transcript: str) -> bool:
    """"I don't know" is a fine answer to "do you know what you want to do?" — parse_yes_no
    reads it as no. For a factual question ("is this your domicile state?") it isn't an
    answer at all, and those callers check this first."""
    if not is_meaningful(transcript):
        return False
    return any(re.search(p, transcript.lower()) for p in _UNSURE_PATTERNS)


def parse_yes_no(transcript: str) -> bool | None:
    if not is_meaningful(transcript):
        return None
    text = transcript.lower()
    # Negations first: "not sure" contains "sure", "don't know" contains "know".
    if any(re.search(p, text) for p in _NO_PATTERNS):
        return False
    if any(re.search(p, text) for p in _YES_PATTERNS):
        return True
    return None


# ---------------- exam choice ----------------

def parse_exam_choice(transcript: str) -> str | None:
    """Returns 'jee', 'neet', or 'careers' (something else)."""
    if not is_meaningful(transcript):
        return None
    text = transcript.lower()
    if re.search(r"\b(something else|other|neither|none|law|design|commerce|arts?|not sure)\b", text):
        return "careers"
    # Whisper commonly hears NEET as "neat" and JEE as "gee"/"g".
    if re.search(r"\b(neet|neat|medical|medicine|doctor|mbbs|bds|dental)\b", text):
        return "neet"
    if re.search(r"\b(jee|j\.?e\.?e|gee|engineering|engineer|iit|nit|b\.?\s?tech)\b", text):
        return "jee"
    return None


# ---------------- numbers (ranks, marks) ----------------

_MULTIPLIERS = {"lakh": 100_000, "lakhs": 100_000, "lac": 100_000, "thousand": 1_000, "k": 1_000}


def parse_number(transcript: str) -> float | None:
    """'45,000' -> 45000; '1.5 lakh' -> 150000; '45 thousand' -> 45000; '98.6' -> 98.6."""
    if not is_meaningful(transcript):
        return None
    text = transcript.lower().replace(",", "")
    match = re.search(r"(\d+(?:\.\d+)?)\s*(lakhs?|lac|thousand|k)?\b", text)
    if not match:
        return None
    value = float(match.group(1))
    if match.group(2):
        value *= _MULTIPLIERS[match.group(2)]
    return value


# ---------------- acronyms ----------------

def _merge_spelled_letters(text: str) -> list[str]:
    """Whisper writes spoken acronyms every which way — "CBSE", "C.B.S.E.", "C B S E" —
    so runs of single letters are joined back into one word."""
    words = re.findall(r"[a-z]+", text.lower().replace("&", ""))  # "J&K" -> "jk"
    merged: list[str] = []
    run: list[str] = []
    for word in words + [""]:
        if len(word) == 1:
            run.append(word)
            continue
        # A lone "I" or "a" is just a word; two or more single letters in a row are an acronym.
        if run:
            merged.append("".join(run) if len(run) > 1 else run[0])
            run = []
        if word:
            merged.append(word)
    return merged


# ---------------- going back / skipping ----------------

def wants_to_go_back(transcript: str) -> bool:
    return bool(re.fullmatch(r"(please\s+)?(go\s+)?(back|previous)(\s+please)?", _normalize(transcript)))


def wants_to_skip(transcript: str) -> bool:
    text = _normalize(transcript)
    return bool(re.search(
        r"\b(skip|pass|prefer not|rather not|don'?t want to (say|tell|share)|not (say|telling|share))\b", text
    ))


# ---------------- school board ----------------

BOARDS = ["CBSE", "ICSE", "State Board", "Other"]


def parse_board(transcript: str) -> str | None:
    if not is_meaningful(transcript):
        return None
    words = _merge_spelled_letters(transcript)
    text = " ".join(words)
    # "CBSC"/"ICSC": Whisper's usual spelling when someone says the E quickly.
    if any(w in ("cbse", "cbsc", "cbsi") for w in words) or re.search(r"\bcentral board\b", text):
        return "CBSE"
    if any(w in ("icse", "icsc", "isc", "cisce") for w in words) or re.search(r"\bindian certificate\b", text):
        return "ICSE"
    if re.search(r"\b(ib|igcse|cambridge|nios|open school|international)\b", text):
        return "Other"
    if re.search(r"\b(state|ssc|hsc|matric|matriculation|samacheer|pseb|bseb|mp board|up board|rbse|gseb|kseeb|puc)\b", text) \
            or re.search(r"\bboard of (secondary|higher)\b", text):
        return "State Board"
    if parse_state(transcript):  # "Maharashtra board", "Kerala syllabus"
        return "State Board"
    if re.search(r"\b(other|something else|different)\b", text):
        return "Other"
    return None


# ---------------- state ----------------

STATES = [
    "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh", "Goa", "Gujarat",
    "Haryana", "Himachal Pradesh", "Jharkhand", "Karnataka", "Kerala", "Madhya Pradesh",
    "Maharashtra", "Manipur", "Meghalaya", "Mizoram", "Nagaland", "Odisha", "Punjab", "Rajasthan",
    "Sikkim", "Tamil Nadu", "Telangana", "Tripura", "Uttar Pradesh", "Uttarakhand", "West Bengal",
    # Union territories
    "Andaman and Nicobar Islands", "Chandigarh", "Dadra and Nagar Haveli and Daman and Diu",
    "Delhi", "Jammu and Kashmir", "Ladakh", "Lakshadweep", "Puducherry",
]

# Old names, short forms, spellings Whisper produces, and big cities people name instead
# ("I live in Pune"). Matched as whole words, longest first.
_STATE_ALIASES = {
    "andhra": "Andhra Pradesh", "arunachal": "Arunachal Pradesh", "chattisgarh": "Chhattisgarh",
    "chhatisgarh": "Chhattisgarh", "chattisgad": "Chhattisgarh", "himachal": "Himachal Pradesh",
    "madhya": "Madhya Pradesh", "orissa": "Odisha", "odissa": "Odisha", "tamilnadu": "Tamil Nadu",
    "tamil": "Tamil Nadu", "telengana": "Telangana", "telangana state": "Telangana", "uttaranchal": "Uttarakhand",
    "uttarkhand": "Uttarakhand", "bengal": "West Bengal", "new delhi": "Delhi", "ncr": "Delhi",
    "jammu": "Jammu and Kashmir", "kashmir": "Jammu and Kashmir", "pondicherry": "Puducherry",
    "pondy": "Puducherry", "andaman": "Andaman and Nicobar Islands", "daman": "Dadra and Nagar Haveli and Daman and Diu",
    "dadra": "Dadra and Nagar Haveli and Daman and Diu",
    "up": "Uttar Pradesh", "mp": "Madhya Pradesh", "ap": "Andhra Pradesh", "hp": "Himachal Pradesh",
    "tn": "Tamil Nadu", "wb": "West Bengal", "jk": "Jammu and Kashmir", "uk": "Uttarakhand",
    "mumbai": "Maharashtra", "bombay": "Maharashtra", "pune": "Maharashtra", "nagpur": "Maharashtra",
    "nashik": "Maharashtra", "thane": "Maharashtra", "aurangabad": "Maharashtra",
    "bangalore": "Karnataka", "bengaluru": "Karnataka", "mysore": "Karnataka", "mysuru": "Karnataka",
    "mangalore": "Karnataka", "chennai": "Tamil Nadu", "madras": "Tamil Nadu", "coimbatore": "Tamil Nadu",
    "madurai": "Tamil Nadu", "kolkata": "West Bengal", "calcutta": "West Bengal", "hyderabad": "Telangana",
    "secunderabad": "Telangana", "warangal": "Telangana", "vijayawada": "Andhra Pradesh",
    "visakhapatnam": "Andhra Pradesh", "vizag": "Andhra Pradesh", "guntur": "Andhra Pradesh",
    "ahmedabad": "Gujarat", "surat": "Gujarat", "vadodara": "Gujarat", "baroda": "Gujarat", "rajkot": "Gujarat",
    "jaipur": "Rajasthan", "jodhpur": "Rajasthan", "udaipur": "Rajasthan", "kota": "Rajasthan",
    "lucknow": "Uttar Pradesh", "kanpur": "Uttar Pradesh", "noida": "Uttar Pradesh", "ghaziabad": "Uttar Pradesh",
    "varanasi": "Uttar Pradesh", "agra": "Uttar Pradesh", "prayagraj": "Uttar Pradesh", "allahabad": "Uttar Pradesh",
    "gurgaon": "Haryana", "gurugram": "Haryana", "faridabad": "Haryana", "patna": "Bihar", "gaya": "Bihar",
    "bhopal": "Madhya Pradesh", "indore": "Madhya Pradesh", "gwalior": "Madhya Pradesh", "jabalpur": "Madhya Pradesh",
    "raipur": "Chhattisgarh", "ranchi": "Jharkhand", "jamshedpur": "Jharkhand", "dhanbad": "Jharkhand",
    "bhubaneswar": "Odisha", "cuttack": "Odisha", "guwahati": "Assam", "dehradun": "Uttarakhand",
    "shimla": "Himachal Pradesh", "ludhiana": "Punjab", "amritsar": "Punjab", "jalandhar": "Punjab",
    "srinagar": "Jammu and Kashmir", "kochi": "Kerala", "cochin": "Kerala", "trivandrum": "Kerala",
    "thiruvananthapuram": "Kerala", "kozhikode": "Kerala", "calicut": "Kerala", "panaji": "Goa",
    "imphal": "Manipur", "shillong": "Meghalaya", "aizawl": "Mizoram", "kohima": "Nagaland",
    "agartala": "Tripura", "gangtok": "Sikkim", "leh": "Ladakh",
}
_STATE_NAMES = sorted(
    [(s.lower(), s) for s in STATES] + list(_STATE_ALIASES.items()), key=lambda pair: -len(pair[0])
)


def parse_state(transcript: str) -> str | None:
    if not is_meaningful(transcript):
        return None
    words = _merge_spelled_letters(transcript)
    text = " ".join(words)
    for name, state in _STATE_NAMES:
        if len(name) == 2:
            # Two-letter short forms only as a whole answer ("UP") or after "in" ("I live in UP") —
            # otherwise "up"/"uk" in ordinary speech would count.
            if text == name or re.search(rf"\b(in|from)\s+{name}$", text):
                return state
            continue
        if re.search(rf"\b{re.escape(name)}\b", text):
            return state
    return None


def matching_states(prefix: str, limit: int = 4) -> list[str]:
    """Suggestions while typing: states starting with what's typed, then ones containing it."""
    typed = prefix.strip().lower()
    if len(typed) < 2:
        return []
    exact = parse_state(prefix)
    starts = [s for s in STATES if s.lower().startswith(typed)]
    contains = [s for s in STATES if typed in s.lower() and s not in starts]
    suggestions = ([exact] if exact else []) + starts + contains
    return list(dict.fromkeys(suggestions))[:limit]


# ---------------- category ----------------

CATEGORIES = ["General", "EWS", "OBC", "SC", "ST"]


def parse_category(transcript: str) -> str | None:
    if not is_meaningful(transcript):
        return None
    words = _merge_spelled_letters(transcript)
    text = " ".join(words)
    if "ews" in words or re.search(r"\beconomically weaker\b", text):
        return "EWS"
    if any(w in ("obc", "obcncl", "ncl") for w in words) or re.search(r"\bother backward\b", text):
        return "OBC"
    if "st" in words or re.search(r"\bscheduled tribes?\b|\btribal\b", text):
        return "ST"
    if "sc" in words or re.search(r"\bscheduled castes?\b", text):
        return "SC"
    if re.search(r"\b(general|gen|open|unreserved|ur|gn)\b", text):
        return "General"
    return None


# ---------------- multiple choice ----------------

_ORDINALS = {
    "first": 0, "one": 0, "1": 0, "a": 0,
    "second": 1, "two": 1, "2": 1, "b": 1,
    "third": 2, "three": 2, "3": 2, "c": 2,
    "fourth": 3, "four": 3, "4": 3, "d": 3,
    "fifth": 4, "five": 4, "5": 4, "e": 4,
    "sixth": 5, "six": 5, "6": 5, "f": 5,
    "last": -1,
}


def match_option(transcript: str, options: list[dict]) -> str | None:
    """Which option did they mean? Options are {"id", "label", "keywords"}.

    The longest matching phrase wins, so "I don't like it" picks the option listing "don't
    like" rather than the one listing "like". "The second one" / "option B" work too.
    """
    if not is_meaningful(transcript) or not options:
        return None
    text = " " + re.sub(r"[^\w\s']", " ", transcript.lower()) + " "
    text = re.sub(r"\s+", " ", text)

    best: tuple[int, str] | None = None
    for option in options:
        phrases = list(option.get("keywords", [])) + [option.get("label", "")]
        for phrase in phrases:
            phrase = re.sub(r"[^\w\s']", " ", phrase.lower()).strip()
            phrase = re.sub(r"\s+", " ", phrase)
            if phrase and f" {phrase} " in text and (best is None or len(phrase) > best[0]):
                best = (len(phrase), option["id"])
    if best is not None:
        return best[1]

    # "the second one", "option b", "number 3"
    ordinal = re.search(r"\b(?:option|number|choice|the)?\s*(first|second|third|fourth|fifth|sixth|last|one|two|three|four|five|six|[1-6])\b(?:\s+one)?",
                        transcript.lower())
    letter = re.fullmatch(r"\s*(?:option\s+)?([a-f])\.?\s*", transcript.lower())
    key = letter.group(1) if letter else (ordinal.group(1) if ordinal else None)
    if key in _ORDINALS:
        index = _ORDINALS[key]
        if -len(options) <= index < len(options):
            return options[index]["id"]
    return None
