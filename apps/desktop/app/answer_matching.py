"""Understanding a spoken answer to an assessment question, on the Pi, in English, Hindi or
Hinglish — before asking the server's slower interpreter (docs/design/12-phase3-plan.md, Step 5).

    match_answer("mujhe maths bahut pasand hai", item)  → {"option": "love"}
    match_answer("option B", item)                       → {"option": "b"}
    match_answer("दूसरा वाला", anchored_item)              → {"option": "l1"}
    match_answer("सत्तासी प्रतिशत", marks_item)              → {"value": 87.0}
    match_answer("chhodo", item)                         → {"skip": True}

Items are as the server sends them: options {key, label {en, hi}, keywords {en, hi, hinglish}}.
The longest matching phrase wins, so "nahi pasand" beats "pasand". Hindi is compared without
nuktas or the chandrabindu/anusvara difference (ज़/ज, हाँ/हां), which speech recognition and
people spell both ways.
"""

from __future__ import annotations

import re

from app.voice_parsing import is_meaningful

# ---------------- text ----------------

_KEEP = re.compile(r"[^0-9a-zऀ-ॿ\s'%.₹½]")


def normalize(text: str) -> str:
    text = (text or "").lower().replace("़", "").replace("ँ", "ं")  # nukta; chandrabindu → anusvara
    text = text.replace("।", " ").replace("-", " ")
    text = _KEEP.sub(" ", text)
    return " " + re.sub(r"\s+", " ", text).strip() + " "


def _has(text: str, phrase: str) -> bool:
    phrase = normalize(phrase).strip()
    return bool(phrase) and f" {phrase} " in text


# ---------------- skip / back ----------------

_SKIP = [
    "skip", "pass", "next question", "don't know", "dont know", "no idea", "not sure which",
    "chhodo", "chodo", "chhod do", "chod do", "chhodiye", "chodiye", "agla", "agla sawal", "pata nahi", "pata nahin",
    "छोड़ो", "छोड़ दो", "छोड़िए", "अगला", "अगला सवाल", "पता नहीं", "मालूम नहीं", "मुझे नहीं पता",
]
_BACK = [
    "back", "go back", "previous", "previous question", "peeche", "piche", "pichla", "pichhla", "wapas", "vapas",
    "पीछे", "पिछला", "पिछला सवाल", "वापस",
]


def wants_to_skip(transcript: str) -> bool:
    text = normalize(transcript)
    return any(_has(text, p) for p in _SKIP)


def wants_to_go_back(transcript: str) -> bool:
    """Only as the whole answer ("peeche", "go back please"): "I want to come back to Delhi" isn't."""
    text = normalize(transcript)
    for word in ("please", "plz", "karo", "kariye", "jao", "jaiye", "चलो", "करो", "जाओ", "जाइए", "चलिए", "the",
                 "question", "sawal", "सवाल"):
        text = text.replace(f" {normalize(word).strip()} ", " ")
    return text.strip() in {normalize(p).strip() for p in _BACK}


# ---------------- numbers ----------------

_EN_UNITS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven",
             "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
_EN_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fourty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
            "eighty": 80, "ninety": 90}

# 1–100 in Hindi: Devanagari, then the Roman spellings people (and Whisper) use.
_HI_NUMBERS = """1 एक ek|2 दो do|3 तीन teen tin|4 चार char chaar|5 पांच पाँच paanch panch|6 छह छः छे chhah chhe che chah|
7 सात saat sat|8 आठ aath ath|9 नौ nau|10 दस das dus|11 ग्यारह gyarah gyaarah|12 बारह barah baarah|13 तेरह terah|
14 चौदह chaudah|15 पंद्रह पन्द्रह pandrah|16 सोलह solah|17 सत्रह satrah|18 अठारह atharah athaarah|19 उन्नीस unnis unnees|
20 बीस bees bis|21 इक्कीस ikkis ikkees|22 बाईस baees bais|23 तेईस teis teyis|24 चौबीस chaubees chaubis|
25 पच्चीस pachchees pachis pachees|26 छब्बीस chhabbees chabbis|27 सत्ताईस sattaees sattais|28 अट्ठाईस atthaees athais|
29 उनतीस untees untis|30 तीस tees tis|31 इकतीस iktees iktis|32 बत्तीस battees battis|33 तैंतीस taintees tetis|
34 चौंतीस chauntees chautis|35 पैंतीस paintees paintis|36 छत्तीस chhattees chattis|37 सैंतीस saintees saintis|
38 अड़तीस adtees artis|39 उनतालीस untaalees untalis|40 चालीस chaalees chalis|41 इकतालीस iktaalees iktalis|
42 बयालीस bayaalees bayalis|43 तैंतालीस taintaalees tentalis|44 चवालीस chavaalees chawalis|45 पैंतालीस paintaalees paintalis|
46 छियालीस chhiyaalees chiyalis|47 सैंतालीस saintaalees saintalis|48 अड़तालीस adtaalees artalis|49 उनचास unchaas unchas|
50 पचास pachaas pachas|51 इक्यावन ikyaavan ikyavan|52 बावन baavan bavan|53 तिरेपन tirepan|54 चौवन chauvan chauwan|
55 पचपन pachpan|56 छप्पन chhappan chappan|57 सत्तावन sattaavan sattavan|58 अट्ठावन atthaavan athavan|59 उनसठ unsath|
60 साठ saath sath|61 इकसठ iksath|62 बासठ baasath basath|63 तिरसठ tirsath|64 चौंसठ chaunsath|65 पैंसठ painsath|
66 छियासठ chhiyaasath chiyasath|67 सड़सठ sadsath|68 अड़सठ adsath|69 उनहत्तर unhattar|70 सत्तर sattar|71 इकहत्तर ikhattar|
72 बहत्तर bahattar|73 तिहत्तर tihattar|74 चौहत्तर chauhattar|75 पचहत्तर pachhattar pachattar|76 छिहत्तर chhihattar|
77 सतहत्तर sathattar|78 अठहत्तर athhattar athattar|79 उनासी unaasi unasi|80 अस्सी assi|81 इक्यासी ikyaasi ikyasi|
82 बयासी bayaasi bayasi|83 तिरासी tiraasi tirasi|84 चौरासी chauraasi chaurasi|85 पचासी pachaasi pachasi|
86 छियासी chhiyaasi chiyasi|87 सत्तासी sattaasi sattasi|88 अट्ठासी atthaasi athasi|89 नवासी navaasi navasi|90 नब्बे nabbe|
91 इक्यानवे ikyaanave ikyanve|92 बानवे baanave banve|93 तिरानवे tiraanave tiranve|94 चौरानवे chauraanave chauranve|
95 पंचानवे पचानवे pachaanave pachanve|96 छियानवे chhiyaanave chiyanve|97 सत्तानवे sattaanave sattanve|
98 अट्ठानवे atthaanave athanve|99 निन्यानवे ninyaanave ninyanve|100 सौ sau"""
HINDI_NUMBERS: dict[str, int] = {}
for _entry in _HI_NUMBERS.replace("\n", "").split("|"):
    _value, *_words = _entry.split()
    for _word in _words:
        HINDI_NUMBERS[normalize(_word).strip()] = int(_value)


def _english_number(words: list[str]) -> float | None:
    total, seen = 0, False
    for word in words:
        if word in _EN_UNITS:
            total, seen = total + _EN_UNITS.index(word), True
        elif word in _EN_TENS:
            total, seen = total + _EN_TENS[word], True
        elif word == "hundred":
            total, seen = (total or 1) * 100, True
        elif seen and word not in ("and", "percent", "per", "cent"):
            break
    return float(total) if seen else None


def parse_number(transcript: str) -> float | None:
    """'87', '87.5%', 'eighty seven', 'सत्तासी', 'sattasi percent', '45 out of 50' (→ 90)."""
    text = normalize(transcript)
    out_of = re.search(r"(\d+(?:\.\d+)?) out of (\d+(?:\.\d+)?)", text)
    if out_of and float(out_of.group(2)) > 0:
        return round(float(out_of.group(1)) / float(out_of.group(2)) * 100, 1)
    of_total = re.search(r"(\d+(?:\.\d+)?) (?:mein se|me se|में से) (\d+(?:\.\d+)?)", text)  # "50 mein se 45"
    if of_total and float(of_total.group(1)) > 0:
        return round(float(of_total.group(2)) / float(of_total.group(1)) * 100, 1)
    digits = re.search(r"(\d+(?:\.\d+)?)", text)
    if digits:
        return float(digits.group(1))
    for word in text.split():
        if word in HINDI_NUMBERS and word not in ("do",) or (word == "do" and len(text.split()) <= 2):
            return float(HINDI_NUMBERS[word])
    return _english_number(text.split())


# ---------------- which option ----------------

_POSITIONS = [
    ["1", "one", "first", "ek", "pehla", "pehle", "pahla", "एक", "पहला", "पहले", "पहली"],
    ["2", "two", "second", "do", "doosra", "dusra", "doosre", "दो", "दूसरा", "दूसरे", "दूसरी"],
    ["3", "three", "third", "teen", "teesra", "tisra", "तीन", "तीसरा", "तीसरे", "तीसरी"],
    ["4", "four", "fourth", "char", "chaar", "chautha", "चार", "चौथा", "चौथे", "चौथी"],
    ["5", "five", "fifth", "paanch", "panch", "panchva", "पांच", "पांचवां", "पांचवा"],
    ["6", "six", "sixth", "chhah", "chhe", "chhatha", "छह", "छठा"],
]
_LETTERS = {"a": 0, "b": 1, "c": 2, "d": 3, "e": 4, "f": 5,
            "ए": 0, "बी": 1, "सी": 2, "डी": 3, "ई": 4, "एफ": 5,
            "bee": 1, "be": 1, "see": 2, "sea": 2, "dee": 3}
_FILLER = {"option", "number", "choice", "the", "one", "wala", "waala", "vala", "vaala", "is", "it's", "its", "answer",
           "my", "hai", "है", "वाला", "वाली", "ऑप्शन", "विकल्प", "जवाब", "मेरा", "नंबर", "i", "think", "say", "says", "to",
           "mera", "jawab", "javab", "level", "line", "स्तर", "लाइन"}


def _phrases(option: dict) -> list[str]:
    label = option.get("label") or {}
    keywords = option.get("keywords") or {}
    out = [label.get("en", ""), label.get("hi", "")]
    for lang in ("en", "hi", "hinglish"):
        out += keywords.get(lang, [])
    return [p for p in out if p]


def _by_phrase(text: str, options: list[dict]) -> str | None:
    best: tuple[int, str] | None = None
    for option in options:
        for phrase in _phrases(option):
            norm = normalize(phrase).strip()
            if norm and f" {norm} " in text and (best is None or len(norm) > best[0]):
                best = (len(norm), option["key"])
    return best[1] if best else None


def _core(text: str) -> list[str]:
    """The answer without the wrapping: "option B hai" → ["b"]."""
    return [w for w in text.split() if w not in _FILLER]


def _by_letter(text: str, options: list[dict]) -> str | None:
    words = _core(text)
    if len(words) == 1 and words[0].strip(".") in _LETTERS:
        index = _LETTERS[words[0].strip(".")]
        return options[index]["key"] if index < len(options) else None
    return None


def _by_position(text: str, options: list[dict]) -> str | None:
    words = _core(text)
    if len(words) != 1:
        return None
    for index, names in enumerate(_POSITIONS):
        if words[0] in {normalize(n).strip() for n in names}:
            return options[index]["key"] if index < len(options) else None
    return None


def _number_in(label: str) -> float | None:
    found = re.search(r"(\d+(?:[.,]\d+)?)(½)?", label.replace(",", ""))
    if not found:
        return None
    return float(found.group(1)) + (0.5 if found.group(2) else 0)


def _by_value(transcript: str, options: list[dict]) -> str | None:
    """For problems whose answers are numbers: "sixty" / "60 rupees" picks "₹60"."""
    said = parse_number(transcript)
    if said is None:
        return None
    if re.search(r"(saadhe|sadhe|साढ़े|साढे|and a half|point five)", normalize(transcript)):
        said += 0.5
    hits = [o["key"] for o in options if _number_in(o["label"]["en"]) == said]
    return hits[0] if len(hits) == 1 else None


def _spelled(text: str, options: list[dict]) -> str | None:
    """"E P H" → the option labelled EPH."""
    joined = "".join(w for w in text.split() if len(w) == 1)
    if len(joined) < 2:
        return None
    hits = [o["key"] for o in options if (o.get("label") or {}).get("en", "").lower() == joined]
    return hits[0] if len(hits) == 1 else None


def match_answer(transcript: str, item: dict) -> dict | None:
    """{"option": key} | {"value": n} | {"skip": True} | {"back": True} | None (not understood)."""
    if not is_meaningful(transcript):
        return None
    text = normalize(transcript)
    if wants_to_go_back(transcript):
        return {"back": True}
    options = item.get("options") or []
    if item.get("type") == "marks":
        value = parse_number(transcript)
        if value is not None and 0 <= value <= 100:
            return {"value": value}
        return {"skip": True} if wants_to_skip(transcript) else None
    if item.get("type") == "problem":
        # Numbers first: in a maths problem "8" means the answer 8, not the eighth option.
        key = _by_value(transcript, options) or _by_letter(text, options) or _spelled(text, options) \
            or _by_phrase(text, options)
    else:
        key = _by_phrase(text, options) or _by_position(text, options) or _by_letter(text, options)
    if key is not None:
        return {"option": key}
    return {"skip": True} if wants_to_skip(transcript) else None
