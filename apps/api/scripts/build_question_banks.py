"""Builds the adaptive question banks: aptitude.v2 (numbers, logic, words), spatial.v2 and
coding_check.v2 — five levels each, from class 6 (level 1) to JEE/CAT-style problems (level 5).

Numbers, logic, spatial and code questions are generated from templates with the right answer
*computed* (the code ones by running the same program in Python), so every answer is right by
construction; the wrong options are the mistakes students actually make. The words questions are
written by hand, in English and Hindi. Deterministic (fixed seed): re-running gives the same files.

    python scripts/build_question_banks.py      # then: python -m app.assessment.loader --lock

An instrument already in use is never edited: change a template → bump the version here.
"""

from __future__ import annotations

import json
import math
import random
from datetime import date, timedelta
from fractions import Fraction
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "app" / "assessment" / "instruments"
LEVELS = 5
PER_LEVEL = 10  # questions in the bank per dimension and level
START = {"6": 1, "7": 1, "8": 2, "9": 2, "10": 3, "11": 3, "12": 3, "college": 3}
NAMES = ["Riya", "Aman", "Sara", "Kabir", "Meera", "Arjun", "Zoya", "Dev", "Anika", "Rohan", "Isha", "Vikram"]
DAYS = [("Monday", "सोमवार"), ("Tuesday", "मंगलवार"), ("Wednesday", "बुधवार"), ("Thursday", "गुरुवार"),
        ("Friday", "शुक्रवार"), ("Saturday", "शनिवार"), ("Sunday", "रविवार")]
MONTHS_HI = ["जनवरी", "फ़रवरी", "मार्च", "अप्रैल", "मई", "जून", "जुलाई", "अगस्त", "सितंबर", "अक्टूबर", "नवंबर", "दिसंबर"]


def hindi_date(d: date) -> str:
    return f"{d.day} {MONTHS_HI[d.month - 1]} {d.year}"


DIRS = [("north", "उत्तर"), ("east", "पूर्व"), ("south", "दक्षिण"), ("west", "पश्चिम")]
DIRS8 = [("north", "उत्तर"), ("north-east", "उत्तर-पूर्व"), ("east", "पूर्व"), ("south-east", "दक्षिण-पूर्व"),
         ("south", "दक्षिण"), ("south-west", "दक्षिण-पश्चिम"), ("west", "पश्चिम"), ("north-west", "उत्तर-पश्चिम")]


def T(en: str, hi: str | None = None) -> dict:
    return {"en": en, "hi": hi if hi is not None else en}


class Q:
    """One generated question: its words, the right answer and three wrong ones (all as labels)."""

    def __init__(self, prompt: dict, right, wrong: list, why: dict, fmt=str, code: str | None = None):
        self.prompt, self.right, self.wrong, self.why, self.fmt, self.code = prompt, right, wrong, why, fmt, code


_slot = [0]  # the right answer takes each position in turn: guessing one letter can't look like ability


def _options(rng: random.Random, q: Q) -> tuple[list[dict], str] | None:
    labels = [q.fmt(q.right)] + [q.fmt(w) for w in q.wrong]
    labels = [lab if isinstance(lab, dict) else T(str(lab)) for lab in labels]
    if len({lab["en"] for lab in labels}) != len(labels) or len(labels) != 4:
        return None  # two options read the same: not a fair question
    wrong = [1, 2, 3]
    rng.shuffle(wrong)
    position = _slot[0] % 4
    _slot[0] += 1
    order = wrong[:position] + [0] + wrong[position:]
    keys = "abcd"
    options = [{"key": keys[n], "label": labels[i]} for n, i in enumerate(order)]
    return options, keys[position]


def rupees(n) -> str:
    return f"₹{n:,}" if isinstance(n, int) else f"₹{n}"


def pct(n) -> str:
    return f"{n:g}%"


def frac(f: Fraction) -> dict:
    """Read aloud well in both languages: "5 in 36", "36 में 5" — never "5/36"."""
    if f.denominator == 1:
        return T(str(f.numerator))
    return T(f"{f.numerator} in {f.denominator}", f"{f.denominator} में {f.numerator}")


def kmh(v) -> dict:
    return T(f"{v} km per hour", f"{v} किमी प्रति घंटा")


def near(rng: random.Random, right: int, spread: list[int]) -> list[int]:
    out = []
    for d in spread:
        if right + d > 0 and right + d != right and right + d not in out:
            out.append(right + d)
    rng.shuffle(out)
    return out[:3]


# ---------------- numbers ----------------

def num(level: int, rng: random.Random) -> Q:
    kind = rng.choice({
        1: ["multiply", "percent", "fraction", "order", "change"],
        2: ["discount", "ratio", "average", "simple_interest", "speed"],
        3: ["profit", "work", "avg_speed", "successive", "proportion"],
        4: ["two_discounts", "train", "ages", "dice", "compound"],
        5: ["ci_si", "pipes", "remainder", "committee", "boat", "coins"],
    }[level])
    if kind == "multiply":
        p, n = rng.randint(12, 45), rng.randint(3, 9)
        return Q(T(f"A notebook costs ₹{p}. How much do {n} notebooks cost?", f"एक कॉपी ₹{p} की है। {n} कॉपियाँ कितने की होंगी?"),
                 p * n, [p * n + p, p * n - p, p + n * 10], T(f"{p} × {n} = {p * n}.", f"{p} × {n} = {p * n}।"), rupees)
    if kind == "percent":
        pc, x = rng.choice([10, 20, 25, 50]), rng.randrange(40, 401, 20)
        r = x * pc // 100
        return Q(T(f"What is {pc}% of {x}?", f"{x} का {pc}% कितना है?"), r, near(rng, r, [r, -r // 2, 10, x // 10 + 1]),
                 T(f"{pc}% of {x} = {x} × {pc} ÷ 100 = {r}.", f"{x} का {pc}% = {x} × {pc} ÷ 100 = {r}।"))
    if kind == "fraction":
        b = rng.choice([3, 4, 5, 6])
        a = rng.randint(1, b - 1)
        x = b * rng.randint(4, 15)
        r = x * a // b
        return Q(T(f"{x} sweets are split into {b} equal parts. How many sweets are in {a} of those parts?",
                   f"{x} मिठाइयाँ {b} बराबर हिस्सों में बाँटी गईं। ऐसे {a} हिस्सों में कितनी मिठाइयाँ होंगी?"),
                 r, near(rng, r, [x // b, -x // b, 2, x - r - r or 3]),
                 T(f"{x} ÷ {b} × {a} = {r}.", f"{x} ÷ {b} × {a} = {r}।"))
    if kind == "order":
        a, b, c = rng.randint(2, 20), rng.randint(2, 9), rng.randint(2, 9)
        r = a + b * c
        return Q(T(f"What is {a} + {b} × {c}?", f"{a} + {b} × {c} कितना है?"), r, near(rng, r, [(a + b) * c - r, 1, -2, b]),
                 T(f"Multiply first: {b} × {c} = {b * c}, then add {a}: {r}.", f"पहले गुणा: {b} × {c} = {b * c}, फिर {a} जोड़ें: {r}।"))
    if kind == "change":
        cost = rng.randint(120, 480)
        note = 500
        r = note - cost
        return Q(T(f"You buy things worth ₹{cost} and pay with a ₹500 note. How much change do you get?",
                   f"आप ₹{cost} का सामान ख़रीदते हैं और ₹500 का नोट देते हैं। कितने पैसे वापस मिलेंगे?"),
                 r, near(rng, r, [10, -10, 100]), T(f"500 − {cost} = {r}.", f"500 − {cost} = {r}।"), rupees)
    if kind == "discount":
        d, p = rng.choice([10, 15, 20, 30, 40]), rng.randrange(200, 2001, 100)
        r = p - p * d // 100
        return Q(T(f"A bag costs ₹{p}. In a sale it is {d}% off. What is the sale price?",
                   f"एक बैग ₹{p} का है। सेल में {d}% की छूट है। सेल में दाम क्या है?"),
                 r, near(rng, r, [p * d // 100 - r, d * 10, -p * d // 200 or -50]),
                 T(f"{d}% of {p} is {p * d // 100}; {p} − {p * d // 100} = {r}.", f"{p} का {d}% = {p * d // 100}; {p} − {p * d // 100} = {r}।"), rupees)
    if kind == "ratio":
        a, b = rng.choice([(2, 3), (3, 5), (1, 4), (4, 5), (3, 7), (2, 5)])
        total = (a + b) * rng.randint(20, 120)
        big = total * max(a, b) // (a + b)
        small = total - big
        return Q(T(f"₹{total} is shared between two friends in the ratio {a}:{b}. How much does the one with the bigger share get?",
                   f"₹{total} दो दोस्तों में {a}:{b} के अनुपात में बाँटे गए। ज़्यादा हिस्से वाले को कितने मिले?"),
                 big, [small, total // 2 if total // 2 not in (big, small) else total // 2 + 10, big + total // (a + b)],
                 T(f"{total} ÷ ({a}+{b}) = {total // (a + b)} per part; × {max(a, b)} = {big}.",
                   f"{total} ÷ ({a}+{b}) = {total // (a + b)} प्रति भाग; × {max(a, b)} = {big}।"), rupees)
    if kind == "average":
        avg = rng.randint(55, 85)
        devs = [rng.randint(-12, 12) for _ in range(4)]
        marks = [avg + d for d in devs] + [avg - sum(devs)]
        return Q(T(f"Five students scored {', '.join(map(str, marks))}. What is their average?",
                   f"पाँच छात्रों के अंक {', '.join(map(str, marks))} हैं। औसत क्या है?"),
                 avg, near(rng, avg, [2, -3, 5, -1]), T(f"Total {sum(marks)} ÷ 5 = {avg}.", f"कुल {sum(marks)} ÷ 5 = {avg}।"))
    if kind == "simple_interest":
        P, R, t = rng.randrange(1000, 10001, 500), rng.choice([4, 5, 6, 8, 10, 12]), rng.randint(2, 5)
        r = P * R * t // 100
        return Q(T(f"What is the simple interest on ₹{P} at {R}% a year for {t} years?",
                   f"₹{P} पर {R}% सालाना दर से {t} साल का साधारण ब्याज कितना होगा?"),
                 r, [P * R // 100, r + P * R // 100, P + r], T(f"{P} × {R} × {t} ÷ 100 = {r}.", f"{P} × {R} × {t} ÷ 100 = {r}।"), rupees)
    if kind == "speed":
        s, t = rng.choice([30, 40, 45, 50, 60, 72]), rng.randint(2, 6)
        return Q(T(f"A bus covers {s * t} km in {t} hours at a steady speed. What is its speed?",
                   f"एक बस {t} घंटे में {s * t} किमी चलती है। उसकी रफ़्तार क्या है?"),
                 s, near(rng, s, [5, -5, 10]), T(f"{s * t} ÷ {t} = {s} km/h.", f"{s * t} ÷ {t} = {s} किमी प्रति घंटा।"), kmh)
    if kind == "profit":
        cp, p = rng.randrange(200, 2001, 40), rng.choice([10, 12.5, 20, 25, 40])
        sp = int(cp * (1 + p / 100))
        if sp != cp * (1 + p / 100):
            cp, p, sp = 400, 25, 500
        return Q(T(f"A shopkeeper buys a toy for ₹{cp} and sells it for ₹{sp}. What is the profit percentage?",
                   f"दुकानदार एक खिलौना ₹{cp} में ख़रीदकर ₹{sp} में बेचता है। मुनाफ़ा कितने प्रतिशत है?"),
                 p, [round((sp - cp) / sp * 100, 1), p * 2, p + 5],
                 T(f"Profit {sp - cp} on cost {cp}: {sp - cp} ÷ {cp} × 100 = {p:g}%.", f"लागत {cp} पर मुनाफ़ा {sp - cp}: {sp - cp} ÷ {cp} × 100 = {p:g}%।"), pct)
    if kind == "work":
        a, b = rng.choice([(6, 12), (10, 15), (12, 24), (20, 30), (4, 12), (18, 9), (8, 24), (21, 42), (15, 10), (30, 20)])
        r = a * b // (a + b)
        return Q(T(f"{rng.choice(NAMES)} can finish a job in {a} days and a friend in {b} days. Working together, how many days will it take?",
                   f"एक व्यक्ति काम को {a} दिन में और उसका दोस्त {b} दिन में पूरा करता है। साथ में कितने दिन लगेंगे?"),
                 r, [(a + b) // 2, abs(a - b) or r + 3, r + 2], T(f"Together they do 1/{a} + 1/{b} = 1/{r} of the job a day.",
                                                                  f"साथ में रोज़ 1/{a} + 1/{b} = 1/{r} काम होता है।"), lambda v: f"{v} days")
    if kind == "avg_speed":
        v1, v2 = rng.choice([(30, 60), (40, 60), (20, 30), (60, 90), (30, 70), (40, 120), (45, 90), (50, 75)])
        r = 2 * v1 * v2 // (v1 + v2)
        return Q(T(f"A car goes to a town at {v1} km/h and comes back the same way at {v2} km/h. What is its average speed for the whole trip?",
                   f"एक कार {v1} किमी प्रति घंटा से शहर जाती है और उसी रास्ते {v2} किमी प्रति घंटा से लौटती है। पूरे सफ़र की औसत रफ़्तार कितनी है?"),
                 r, [(v1 + v2) // 2, r - 4, r + 6], T(f"Average speed = 2 × {v1} × {v2} ÷ ({v1} + {v2}) = {r} — not the plain average.",
                                                     f"औसत रफ़्तार = 2 × {v1} × {v2} ÷ ({v1} + {v2}) = {r} — सीधा औसत नहीं।"), kmh)
    if kind == "successive":
        x = rng.choice([10, 20, 30, 40, 50])
        r = x * x / 100
        return Q(T(f"A price goes up by {x}% and then down by {x}%. What is the overall change?",
                   f"एक दाम {x}% बढ़ता है और फिर {x}% घटता है। कुल बदलाव क्या है?"),
                 T(f"{r:g}% decrease", f"{r:g}% की कमी"),
                 [T("No change", "कोई बदलाव नहीं"), T(f"{r:g}% increase", f"{r:g}% की बढ़त"), T(f"{x / 2:g}% decrease", f"{x / 2:g}% की कमी")],
                 T(f"100 → {100 + x} → {100 + x} × {100 - x}/100 = {100 - r:g}: a {r:g}% fall.",
                   f"100 → {100 + x} → {100 + x} × {100 - x}/100 = {100 - r:g}: {r:g}% की कमी।"), lambda v: v)
    if kind == "proportion":
        w1, d1 = rng.choice([(6, 12), (8, 15), (10, 18), (12, 10), (5, 24), (9, 20)])
        w2 = rng.choice([d for d in (2, 3, 4, 5, 6, 8, 9, 10, 12, 15, 18, 20, 24, 30, 36, 40, 45) if (w1 * d1) % d == 0 and d != w1])
        r = w1 * d1 // w2
        return Q(T(f"{w1} workers build a wall in {d1} days. How many days would {w2} workers take, at the same pace?",
                   f"{w1} मज़दूर एक दीवार {d1} दिन में बनाते हैं। उसी रफ़्तार से {w2} मज़दूर कितने दिन लेंगे?"),
                 r, near(rng, r, [d1 * w2 // w1 - r if d1 * w2 // w1 != r else 3, 2, -2, 5]),
                 T(f"The job is {w1} × {d1} = {w1 * d1} worker-days; ÷ {w2} = {r}.", f"काम = {w1} × {d1} = {w1 * d1} मज़दूर-दिन; ÷ {w2} = {r}।"),
                 lambda v: f"{v} days")
    if kind == "two_discounts":
        a, b = rng.choice([(10, 20), (20, 25), (10, 10), (20, 20), (30, 20), (40, 10), (50, 20), (15, 20)])
        r = a + b - a * b / 100
        return Q(T(f"Two discounts, {a}% and then {b}%, equal one single discount of how much?",
                   f"पहले {a}% और फिर {b}% की छूट — यह एक बार की कितनी छूट के बराबर है?"),
                 r, [a + b, r + 2, abs(a - b) or 5], T(f"{a} + {b} − {a}×{b}/100 = {r:g}%.", f"{a} + {b} − {a}×{b}/100 = {r:g}%।"), pct)
    if kind == "train":
        ms, t = rng.choice([10, 15, 20, 25, 30]), rng.randint(6, 20)
        L, speed = ms * t, ms * 18 // 5
        return Q(T(f"A train {L} m long passes a pole in {t} seconds. What is its speed in km per hour?",
                   f"{L} मीटर लंबी ट्रेन एक खंभे को {t} सेकंड में पार करती है। उसकी रफ़्तार किमी प्रति घंटा में कितनी है?"),
                 speed, [ms, speed + 18, round(L / t * 3.6 / 2)], T(f"{L} ÷ {t} = {ms} m/s; × 18/5 = {speed} km/h.",
                                                                    f"{L} ÷ {t} = {ms} मीटर प्रति सेकंड; × 18/5 = {speed} किमी प्रति घंटा।"), kmh)
    if kind == "ages":
        k, m, n = rng.choice([(4, 3, 6), (3, 2, 10), (5, 3, 8), (4, 2, 10), (7, 4, 9)])
        s = n * (m - 1) // (k - m)
        return Q(T(f"A father is {k} times as old as his son. In {n} years he will be {m} times as old. How old is the son now?",
                   f"एक पिता अपने बेटे से {k} गुना बड़े हैं। {n} साल बाद वे {m} गुना बड़े होंगे। बेटे की उम्र अभी कितनी है?"),
                 s, near(rng, s, [n, -2, 4, k]), T(f"{k}S + {n} = {m}(S + {n}) gives S = {s}; the father is {k * s}.",
                                                   f"{k}S + {n} = {m}(S + {n}) से S = {s}; पिता {k * s} के हैं।"), lambda v: f"{v} years")
    if kind == "dice":
        total = rng.choice([4, 5, 6, 7, 8, 9, 10])
        ways = 6 - abs(total - 7)
        r = Fraction(ways, 36)
        return Q(T(f"Two dice are thrown. What is the probability that the numbers add up to {total}?",
                   f"दो पासे फेंके गए। अंकों का जोड़ {total} होने की प्रायिकता क्या है?"),
                 r, [Fraction(ways, 12) if Fraction(ways, 12) != r else Fraction(1, 2), Fraction(1, 6) if r != Fraction(1, 6) else Fraction(5, 36),
                     Fraction(ways + 1, 36)],
                 T(f"{ways} of the 36 equally likely pairs add to {total}: {frac(r)}.", f"36 में से {ways} जोड़ियों का जोड़ {total} है: {frac(r)}।"), frac)
    if kind == "compound":
        P, R = rng.randrange(4000, 20001, 4000), rng.choice([5, 10, 20])  # P × 0.1025 is whole only for multiples of 400
        r = P * ((100 + R) ** 2 - 10000) // 10000
        assert r * 10000 == P * ((100 + R) ** 2 - 10000)
        return Q(T(f"What is the compound interest on ₹{P} at {R}% a year for 2 years?",
                   f"₹{P} पर {R}% सालाना की दर से 2 साल का चक्रवृद्धि ब्याज कितना होगा?"),
                 r, [2 * P * R // 100, r + P * R // 100, P * R // 100],
                 T(f"{P} × (1.{R:02d})² − {P} = {r}." if R < 100 else "", f"{P} × (1 + {R}/100)² − {P} = {r}।"), rupees)
    if kind == "ci_si":
        P, R = rng.choice([(1000, 10), (5000, 10), (2000, 5), (10000, 4), (8000, 5), (4000, 10)])
        r = P * R * R // 10000
        return Q(T(f"On ₹{P} at {R}% a year for 2 years, how much more is compound interest than simple interest?",
                   f"₹{P} पर {R}% सालाना, 2 साल: चक्रवृद्धि ब्याज साधारण ब्याज से कितना ज़्यादा है?"),
                 r, [r * 2, P * R // 100, r + 5], T(f"The difference is P × (R/100)² = {P} × ({R}/100)² = {r}.",
                                                   f"अंतर = P × (R/100)² = {P} × ({R}/100)² = {r}।"), rupees)
    if kind == "pipes":
        a, b, c, r = rng.choice([(6, 12, 8, 8), (4, 6, 12, 3), (10, 15, 12, 12), (3, 6, 4, 4), (12, 18, 36, 9), (8, 12, 24, 6), (20, 30, 60, 15)])
        return Q(T(f"Pipe A fills a tank in {a} hours and pipe B in {b} hours; a leak empties it in {c} hours. With all three open, how long does it take to fill?",
                   f"पाइप A टंकी {a} घंटे में और पाइप B {b} घंटे में भरता है; एक रिसाव उसे {c} घंटे में खाली करता है। तीनों खुले हों तो टंकी कितने घंटे में भरेगी?"),
                 r, [a * b // (a + b) if a * b // (a + b) != r else r + 1, r + 2, r * 2],
                 T(f"Per hour: 1/{a} + 1/{b} − 1/{c} = 1/{r}.", f"हर घंटे: 1/{a} + 1/{b} − 1/{c} = 1/{r}।"), lambda v: f"{v} hours")
    if kind == "remainder":
        a, m = rng.choice([(2, 7), (3, 7), (2, 5), (3, 5), (4, 7), (7, 10), (3, 10), (2, 9)])
        n = rng.randint(20, 60)
        r = pow(a, n, m)
        others = [x for x in range(m) if x != r]
        rng.shuffle(others)
        return Q(T(f"What is the remainder when {a}^{n} is divided by {m}?", f"{a}^{n} को {m} से भाग देने पर शेषफल क्या है?"),
                 r, others[:3], T(f"The remainders of {a}, {a}², {a}³… repeat in a cycle; following it to the {n}th power gives {r}.",
                                  f"{a}, {a}², {a}³… के शेषफल एक चक्र में दोहराते हैं; {n}वीं घात तक चलने पर {r} आता है।"))
    if kind == "committee":
        n, k = rng.randint(6, 10), rng.randint(2, 4)
        r = math.comb(n, k)
        return Q(T(f"In how many ways can a team of {k} be chosen from {n} students?", f"{n} छात्रों में से {k} की टीम कितने तरीक़ों से चुनी जा सकती है?"),
                 r, near(rng, r, [math.perm(n, k) - r, math.comb(n, k - 1) - r if math.comb(n, k - 1) != r else 7, n * k - r if n * k != r else 4]),
                 T(f"Order doesn't matter: {n}C{k} = {r}.", f"क्रम मायने नहीं रखता: {n}C{k} = {r}।"))
    if kind == "boat":
        b, s, t1 = rng.choice([(10, 2, 2), (12, 3, 2), (15, 5, 3), (9, 3, 2), (20, 4, 3), (8, 2, 3)])
        d = (b + s) * t1
        t2 = Fraction(d, b - s)
        if t2.denominator != 1:
            b, s, t1, d, t2 = 10, 2, 2, 24, Fraction(3)
        return Q(T(f"A boat goes {d} km downstream in {t1} hours and the same distance upstream in {t2} hours. What is the speed of the stream?",
                   f"एक नाव धारा के साथ {d} किमी {t1} घंटे में और उतनी ही दूरी धारा के विरुद्ध {t2} घंटे में जाती है। धारा की रफ़्तार?"),
                 s, near(rng, s, [b - s, 1, 3, -1]), T(f"Down {d}/{t1} = {b + s}, up {d}/{t2} = {b - s}; stream = ({b + s} − {b - s}) ÷ 2 = {s}.",
                                                       f"साथ {b + s}, विरुद्ध {b - s}; धारा = ({b + s} − {b - s}) ÷ 2 = {s}।"), kmh)
    # coins
    n = rng.randint(3, 6)
    r = 1 - Fraction(1, 2 ** n)
    return Q(T(f"A coin is tossed {n} times. What is the probability of getting at least one head?",
               f"एक सिक्का {n} बार उछाला गया। कम से कम एक बार हेड आने की प्रायिकता क्या है?"),
             r, [Fraction(1, 2 ** n), Fraction(n, 2 ** n), Fraction(1, 2)], T(f"1 − (no heads at all) = 1 − 1/{2 ** n} = {frac(r)}.",
                                                                              f"1 − (एक भी हेड नहीं) = 1 − 1/{2 ** n} = {frac(r)}।"), frac)


# ---------------- logic ----------------

def series(level: int, rng: random.Random) -> tuple[list[int], int, dict]:
    if level == 1:
        a, d = rng.randint(1, 20), rng.randint(2, 9)
        s = [a + d * i for i in range(5)]
        return s[:4], s[4], T(f"Each number is {d} more than the last.", f"हर संख्या पिछली से {d} ज़्यादा है।")
    if level == 2:
        a, x, y = rng.randint(1, 15), rng.randint(2, 6), rng.randint(3, 9)
        s = [a]
        for i in range(5):
            s.append(s[-1] + (x if i % 2 == 0 else y))
        return s[:5], s[5], T(f"It adds {x}, then {y}, in turn.", f"बारी-बारी से {x} और {y} जुड़ते हैं।")
    if level == 3:
        if rng.random() < 0.5:
            n = rng.randint(2, 9)
            return [(n + i) ** 2 for i in range(4)], (n + 4) ** 2, T("They are squares of numbers in a row.", "ये लगातार संख्याओं के वर्ग हैं।")
        a, r = rng.randint(2, 6), rng.choice([2, 3])
        return [a * r ** i for i in range(4)], a * r ** 4, T(f"Each number is {r} times the last.", f"हर संख्या पिछली की {r} गुना है।")
    if level == 4:
        a, d, k = rng.randint(1, 10), rng.randint(1, 5), rng.randint(1, 3)
        s, step = [a], d
        for _ in range(5):
            s.append(s[-1] + step)
            step += k
        return s[:5], s[5], T(f"The gaps grow by {k} each time.", f"अंतर हर बार {k} से बढ़ता है।")
    kind = rng.choice(["double_plus", "fib", "factorial", "times_minus"])
    if kind == "double_plus":
        a, c = rng.randint(1, 5), rng.choice([1, 2, 3])
        s = [a]
        for _ in range(5):
            s.append(s[-1] * 2 + c)
        return s[:5], s[5], T(f"Each is double the last, plus {c}.", f"हर संख्या पिछली की दोगुनी जमा {c} है।")
    if kind == "fib":
        a, b = rng.randint(1, 6), rng.randint(2, 8)
        s = [a, b]
        for _ in range(4):
            s.append(s[-1] + s[-2])
        return s[:5], s[5], T("Each is the sum of the two before it.", "हर संख्या पिछली दो का जोड़ है।")
    if kind == "factorial":
        return [1, 2, 6, 24], 120, T("Multiply by 2, 3, 4, then 5.", "2, 3, 4, फिर 5 से गुणा।")
    a = rng.randint(2, 5)
    s = [a]
    for _ in range(5):
        s.append(s[-1] * 3 - 1)
    return s[:4], s[4], T("Each is three times the last, minus 1.", "हर संख्या पिछली की तीन गुना घटा 1 है।")


SYLLOGISMS = [  # (premises, the conclusion that must follow, three that needn't) — classic valid forms
    (("All {a} are {b}.", "All {b} are {c}."), "All {a} are {c}.", ["All {c} are {a}.", "No {a} are {c}.", "Some {c} are not {b}."]),
    (("No {a} are {b}.", "All {c} are {a}."), "No {c} are {b}.", ["All {b} are {c}.", "Some {c} are {b}.", "All {a} are {c}."]),
    (("Some {a} are {b}.", "All {b} are {c}."), "Some {a} are {c}.", ["All {a} are {c}.", "No {a} are {c}.", "All {c} are {b}."]),
    (("All {a} are {b}.", "No {b} are {c}."), "No {a} are {c}.", ["All {c} are {a}.", "Some {a} are {c}.", "All {b} are {a}."]),
    (("All {a} are {b}.", "Some {c} are {a}."), "Some {c} are {b}.", ["All {c} are {b}.", "No {c} are {b}.", "All {b} are {a}."]),
]
# (English plural, Hindi plural, Hindi singular): "No books are cups" is "कोई भी किताब कप नहीं है".
WORDS = [("pens", "कलम", "कलम"), ("books", "किताबें", "किताब"), ("cups", "कप", "कप"), ("chairs", "कुर्सियाँ", "कुर्सी"),
         ("lamps", "लैंप", "लैंप"), ("boxes", "डिब्बे", "डिब्बा"), ("phones", "फ़ोन", "फ़ोन"), ("kites", "पतंगें", "पतंग"),
         ("bells", "घंटियाँ", "घंटी"), ("rings", "अंगूठियाँ", "अंगूठी")]


def _syllogism_hi(text: str, names: dict) -> str:
    """Hindi for one statement, by its form. names: letter → (plural, singular)."""
    for en, hi, form in (("All {x} are {y}.", "सभी {x} {y} हैं।", 0), ("No {x} are {y}.", "कोई भी {x} {y} नहीं है।", 1),
                         ("Some {x} are not {y}.", "कुछ {x} {y} नहीं हैं।", 0), ("Some {x} are {y}.", "कुछ {x} {y} हैं।", 0)):
        for xa in "abc":
            for ya in "abc":
                if text == en.format(x="{" + xa + "}", y="{" + ya + "}"):
                    return hi.format(x=names[xa][form], y=names[ya][form])
    raise ValueError(text)


def logic(level: int, rng: random.Random) -> Q:
    kind = rng.choice({
        1: ["series", "taller", "odd_number", "turn"],
        2: ["series", "letters", "code_shift", "distance", "day_after"],
        3: ["series", "syllogism", "clock", "rank"],
        4: ["series", "calendar", "row_total", "word_sum", "syllogism"],
        5: ["series", "clock_hard", "leap", "directions_hard"],
    }[level])
    if kind == "series":
        shown, right, why = series(level, rng)
        return Q(T(f"What comes next: {', '.join(map(str, shown))}, ?", f"आगे क्या आएगा: {', '.join(map(str, shown))}, ?"),
                 right, near(rng, right, [1, -1, 2, shown[-1] - shown[-2] if shown[-1] - shown[-2] else 3]), why)
    if kind == "taller":
        a, b, c = rng.sample(NAMES, 3)
        tallest = rng.random() < 0.5
        return Q(T(f"{a} is taller than {b}. {b} is taller than {c}. Who is the {'tallest' if tallest else 'shortest'}?",
                   f"{a} की लंबाई {b} से ज़्यादा है। {b} की लंबाई {c} से ज़्यादा है। सबसे {'ज़्यादा' if tallest else 'कम'} लंबाई किसकी है?"),
                 a if tallest else c, [b, c if tallest else a, T("Can't tell", "पता नहीं चल सकता")],
                 T(f"{a} > {b} > {c}.", f"{a} > {b} > {c}।"), lambda v: v)
    if kind == "odd_number":
        k = rng.choice([3, 4, 5, 6, 7])
        parity = rng.choice([0, 1]) if k % 2 else 0  # all even, or all odd: so "the only odd number" can't also be an answer
        nums = rng.sample([k * i for i in range(2, 13) if (k * i) % 2 == parity], 3)
        odd = rng.choice([x for x in range(k * 2 + 1, k * 13) if x % k and x % 2 == parity and x not in nums])
        return Q(T(f"Which number is the odd one out: {', '.join(map(str, sorted(nums + [odd])))}?",
                   f"कौन सी संख्या अलग है: {', '.join(map(str, sorted(nums + [odd])))}?"),
                 odd, nums, T(f"All the others are multiples of {k}.", f"बाक़ी सब {k} के गुणज हैं।"))
    if kind == "turn":
        start, turns = rng.randrange(4), rng.choice([(1,), (-1,), (1, 1), (-1, -1), (1, 1, 1)])
        end = (start + sum(turns)) % 4
        said = " and then ".join("right" if t == 1 else "left" for t in turns)
        said_hi = ", फिर ".join("दाएँ" if t == 1 else "बाएँ" for t in turns)
        wrong = [i for i in range(4) if i != end]
        return Q(T(f"You face {DIRS[start][0]}. You turn {said}. Which way do you face now?",
                   f"आपका मुँह {DIRS[start][1]} की ओर है। आप {said_hi} मुड़ते हैं। अब आपका मुँह किस ओर है?"),
                 end, wrong, T(f"Each right turn is a quarter turn clockwise; you end facing {DIRS[end][0]}.",
                               f"हर दायाँ मोड़ घड़ी की दिशा में चौथाई घुमाव है; अंत में मुँह {DIRS[end][1]} की ओर।"),
                 lambda i: T(DIRS[i][0].capitalize(), DIRS[i][1]))
    if kind == "letters":
        step = rng.choice([2, 3, 4])
        start = rng.randint(0, 25 - step * 6 - 1)
        shown = [chr(65 + start + step * i) for i in range(4)]
        right = chr(65 + start + step * 4)
        wrong = [chr(65 + start + step * 4 + d) for d in (1, -1, step + 1)]
        return Q(T(f"What comes next: {', '.join(shown)}, ?", f"आगे क्या आएगा: {', '.join(shown)}, ?"),
                 right, wrong, T(f"Each letter is {step} places after the last.", f"हर अक्षर पिछले से {step} जगह आगे है।"))
    if kind == "code_shift":
        k = rng.choice([1, 2])
        a, b = rng.sample(["CAT", "DOG", "SUN", "PEN", "BOX", "CUP", "MAP", "BAG", "HAT", "JAM"], 2)
        shift = lambda w, n=k: "".join(chr((ord(c) - 65 + n) % 26 + 65) for c in w)
        right = shift(b)
        return Q(T(f"In a code, {a} is written as {shift(a)}. How is {b} written?", f"एक कोड में {a} को {shift(a)} लिखा जाता है। {b} कैसे लिखा जाएगा?"),
                 right, [shift(b, k + 1), shift(b, -k), b[::-1]], T(f"Each letter moves {k} place{'s' if k > 1 else ''} forward.",
                                                                     f"हर अक्षर {k} जगह आगे खिसकता है।"))
    if kind == "distance":
        a, b, c = rng.choice([(3, 4, 5), (6, 8, 10), (5, 12, 13), (9, 12, 15), (8, 15, 17), (12, 16, 20)])
        m = rng.choice([1, 10, 100])
        return Q(T(f"You walk {a * m} m north, then {b * m} m east. How far are you from where you started, in a straight line?",
                   f"आप {a * m} मी उत्तर, फिर {b * m} मी पूर्व चलते हैं। शुरुआत की जगह से सीधी दूरी कितनी है?"),
                 c * m, [(a + b) * m, (b - a) * m if b != a else m, (c + 1) * m], T(f"√({a * m}² + {b * m}²) = {c * m} m.", f"√({a * m}² + {b * m}²) = {c * m} मी।"),
                 lambda v: f"{v} m")
    if kind == "day_after":
        d, n = rng.randrange(7), rng.randint(10, 40)
        end = (d + n) % 7
        wrong = rng.sample([i for i in range(7) if i != end], 3)
        return Q(T(f"If today is {DAYS[d][0]}, what day will it be {n} days from now?", f"अगर आज {DAYS[d][1]} है, तो {n} दिन बाद कौन सा दिन होगा?"),
                 end, wrong, T(f"{n} = {n // 7} weeks and {n % 7} days: {n % 7} days after {DAYS[d][0]}.",
                               f"{n} = {n // 7} हफ़्ते और {n % 7} दिन: {DAYS[d][1]} के {n % 7} दिन बाद।"),
                 lambda i: T(DAYS[i][0], DAYS[i][1]))
    if kind == "syllogism":
        (p1, p2), right, wrong = rng.choice(SYLLOGISMS)
        a, b, c = rng.sample(WORDS, 3)
        en = {"a": a[0], "b": b[0], "c": c[0]}
        hi = {"a": a[1:], "b": b[1:], "c": c[1:]}
        state_en = " ".join(t.format(**en) for t in (p1, p2))
        state_hi = " ".join(_syllogism_hi(t, hi) for t in (p1, p2))
        return Q(T(f"If these are true: {state_en} Which of these must also be true?", f"अगर ये सही हैं: {state_hi} इनमें से क्या ज़रूर सही है?"),
                 T(right.format(**en), _syllogism_hi(right, hi)), [T(w.format(**en), _syllogism_hi(w, hi)) for w in wrong],
                 T("Only this one follows from both statements; the others might or might not be true.",
                   "सिर्फ़ यही दोनों बातों से निकलता है; बाक़ी सही भी हो सकते हैं और नहीं भी।"), lambda v: v)
    if kind in ("clock", "clock_hard"):
        h = rng.randint(1, 11)
        m = rng.choice([0, 15, 20, 30, 40, 45]) if kind == "clock" else rng.choice([10, 12, 16, 18, 24, 25, 35, 36, 38, 44, 50, 54])
        angle = abs(30 * h - 5.5 * m)
        angle = min(angle, 360 - angle)
        fmt = lambda v: f"{v:g}°"
        return Q(T(f"What is the smaller angle between the hour and minute hands of a clock at {h}:{m:02d}?",
                   f"{h}:{m:02d} बजे घड़ी की घंटे और मिनट की सुइयों के बीच छोटा कोण कितना है?"),
                 angle, [abs(30 * h - 6 * m) % 360 if abs(30 * h - 6 * m) % 360 != angle else angle + 10, angle + 15, abs(angle - 30) or 45],
                 T(f"Hour hand at {30 * h + 0.5 * m:g}°, minute hand at {6 * m}°: the gap is {angle:g}°.",
                   f"घंटे की सुई {30 * h + 0.5 * m:g}° पर, मिनट की {6 * m}° पर: अंतर {angle:g}°।"), fmt)
    if kind == "rank":
        n, k = rng.randint(20, 50), rng.randint(5, 18)
        r = n - k + 1
        return Q(T(f"In a row of {n} students, Meera is {k}th from the left. What is her position from the right?",
                   f"{n} छात्रों की एक पंक्ति में मीरा बाएँ से {k}वीं है। दाएँ से वह किस स्थान पर है?"),
                 r, near(rng, r, [-1, 1, n - k - r]), T(f"{n} − {k} + 1 = {r}.", f"{n} − {k} + 1 = {r}।"),
                 lambda v: T(f"{v}th", f"{v}वाँ"))
    if kind == "calendar":
        start = date(2026, 1, 1) + timedelta(days=rng.randint(0, 364))
        n = rng.randint(45, 200)
        end = start + timedelta(days=n)
        wd, we = start.weekday(), end.weekday()
        wrong = rng.sample([i for i in range(7) if i != we], 3)
        return Q(T(f"{start:%-d %B %Y} is a {DAYS[wd][0]}. What day of the week is {end:%-d %B %Y}?",
                   f"{hindi_date(start)} को {DAYS[wd][1]} है। {hindi_date(end)} को कौन सा दिन होगा?"),
                 we, wrong, T(f"It is {n} days later: {n // 7} weeks and {n % 7} days.", f"यह {n} दिन बाद है: {n // 7} हफ़्ते और {n % 7} दिन।"),
                 lambda i: T(DAYS[i][0], DAYS[i][1]))
    if kind == "row_total":
        a, b = rng.randint(8, 30), rng.randint(8, 30)
        r = a + b - 1
        return Q(T(f"In a queue, Kabir is {a}th from the front and {b}th from the back. How many people are in the queue?",
                   f"एक क़तार में कबीर आगे से {a}वाँ और पीछे से {b}वाँ है। क़तार में कितने लोग हैं?"),
                 r, near(rng, r, [1, 2, -1]), T(f"{a} + {b} − 1 = {r}: Kabir is counted twice otherwise.", f"{a} + {b} − 1 = {r}: नहीं तो कबीर दो बार गिना जाता।"))
    if kind == "word_sum":
        word = rng.choice(["CAT", "BOOK", "TREE", "MATH", "STAR", "CODE", "LEAF", "MOON", "GAME", "BEAD"])
        r = sum(ord(c) - 64 for c in word)
        return Q(T(f"If A = 1, B = 2, C = 3 … Z = 26, what do the letters of {word} add up to?",
                   f"अगर A = 1, B = 2, C = 3 … Z = 26 हो, तो {word} के अक्षरों का जोड़ कितना है?"),
                 r, near(rng, r, [1, -2, 3, 10]), T(" + ".join(str(ord(c) - 64) for c in word) + f" = {r}."))
    if kind == "leap":
        year = rng.choice([2023, 2024, 2027, 2028, 2031, 2032])
        first = date(year, 1, 1).weekday()
        nxt = date(year + 1, 1, 1).weekday()
        wrong = rng.sample([i for i in range(7) if i != nxt], 3)
        leap = (date(year + 1, 1, 1) - date(year, 1, 1)).days == 366
        return Q(T(f"1 January {year} was a {DAYS[first][0]}. What day was 1 January {year + 1}?",
                   f"1 जनवरी {year} को {DAYS[first][1]} था। 1 जनवरी {year + 1} को कौन सा दिन था?"),
                 nxt, wrong, T(f"{year} has {366 if leap else 365} days: that's 52 weeks and {2 if leap else 1} day{'s' if leap else ''}.",
                               f"{year} में {366 if leap else 365} दिन हैं: 52 हफ़्ते और {2 if leap else 1} दिन।"),
                 lambda i: T(DAYS[i][0], DAYS[i][1]))
    # directions_hard: several legs, the direction from the start
    legs = rng.choice([[(0, 3), (1, 4)], [(0, 5), (1, 5)], [(2, 4), (3, 4)], [(0, 6), (3, 2), (2, 6), (3, 6)],
                       [(1, 3), (0, 3), (3, 6)], [(0, 2), (1, 7), (2, 2)]])
    x = sum(dist * (1 if d == 1 else -1 if d == 3 else 0) for d, dist in legs)
    y = sum(dist * (1 if d == 0 else -1 if d == 2 else 0) for d, dist in legs)
    idx = round(math.degrees(math.atan2(x, y)) / 45) % 8 if (x or y) else 0
    walk_en = ", then ".join(f"{dist} km {DIRS[d][0]}" for d, dist in legs)
    walk_hi = ", फिर ".join(f"{dist} किमी {DIRS[d][1]}" for d, dist in legs)
    wrong = rng.sample([i for i in range(8) if i != idx], 3)
    return Q(T(f"Starting from home, Zoya walks {walk_en}. In which direction is she from home now?",
               f"घर से ज़ोया {walk_hi} चलती है। अब वह घर से किस दिशा में है?"),
             idx, wrong, T("Overall she is " + " and ".join(p for p in (f"{abs(x)} km {'east' if x > 0 else 'west'}" if x else "",
                                                                        f"{abs(y)} km {'north' if y > 0 else 'south'}" if y else "") if p) + " of home.",
                           "कुल मिलाकर वह घर से " + " और ".join(p for p in (f"{abs(x)} किमी {'पूर्व' if x > 0 else 'पश्चिम'}" if x else "",
                                                                          f"{abs(y)} किमी {'उत्तर' if y > 0 else 'दक्षिण'}" if y else "") if p) + " में है।"),
             lambda i: T(DIRS8[i][0].capitalize(), DIRS8[i][1]))


# ---------------- words (written by hand, both languages) ----------------
# (level, prompt en, prompt hi, [option en/hi pairs, the right one first], explanation en, explanation hi)
VERBAL = [
    (1, "Which word means the opposite of 'ancient'?", "'प्राचीन' का विलोम (उल्टा) क्या है?",
     [("modern", "आधुनिक"), ("old", "पुराना"), ("famous", "प्रसिद्ध"), ("broken", "टूटा हुआ")], "Ancient means very old; modern is new.", "प्राचीन यानी बहुत पुराना; आधुनिक यानी नया।"),
    (1, "Which word means the opposite of 'generous'?", "'उदार' का विलोम (उल्टा) क्या है?",
     [("stingy", "कंजूस"), ("kind", "दयालु"), ("rich", "अमीर"), ("brave", "बहादुर")], "Generous people give freely; stingy people don't.", "उदार व्यक्ति खुलकर देता है; कंजूस नहीं।"),
    (1, "Which is the odd one out: apple, mango, carrot, banana?", "इनमें से कौन अलग है: सेब, आम, गाजर, केला?",
     [("carrot", "गाजर"), ("apple", "सेब"), ("mango", "आम"), ("banana", "केला")], "The others are fruits; a carrot is a vegetable.", "बाक़ी फल हैं; गाजर सब्ज़ी है।"),
    (1, "Which is the odd one out: chair, table, sofa, spoon?", "इनमें से कौन अलग है: कुर्सी, मेज़, सोफ़ा, चम्मच?",
     [("spoon", "चम्मच"), ("chair", "कुर्सी"), ("table", "मेज़"), ("sofa", "सोफ़ा")], "The others are furniture.", "बाक़ी सब फ़र्नीचर हैं।"),
    (1, "Which word means the same as 'big'?", "'बड़ा' का समानार्थी शब्द कौन सा है?",
     [("large", "विशाल"), ("tiny", "नन्हा"), ("thin", "पतला"), ("short", "छोटा")], "Large and big mean the same.", "विशाल और बड़ा का अर्थ एक है।"),
    (1, "Bird is to sky as fish is to …?", "जैसे पक्षी का संबंध आकाश से है, वैसे ही मछली का संबंध किससे है?",
     [("water", "पानी"), ("tree", "पेड़"), ("sand", "रेत"), ("nest", "घोंसला")], "A bird moves in the sky; a fish in water.", "पक्षी आकाश में चलता है; मछली पानी में।"),
    (2, "Book is to reading as fork is to …?", "जैसे किताब का संबंध पढ़ने से है, वैसे ही काँटे (फ़ोर्क) का संबंध किससे है?",
     [("eating", "खाना"), ("drawing", "चित्र बनाना"), ("writing", "लिखना"), ("cooking", "पकाना")], "A book is used for reading; a fork for eating.", "किताब पढ़ने के काम आती है; काँटा खाने के।"),
    (2, "Doctor is to hospital as teacher is to …?", "जैसे डॉक्टर का संबंध अस्पताल से है, वैसे ही शिक्षक का संबंध किससे है?",
     [("school", "विद्यालय"), ("library", "पुस्तकालय"), ("office", "दफ़्तर"), ("market", "बाज़ार")], "Where each one works.", "जहाँ हर कोई काम करता है।"),
    (2, "Which word means the same as 'rapid'?", "'तीव्र' का समानार्थी शब्द कौन सा है?",
     [("fast", "तेज़"), ("slow", "धीमा"), ("calm", "शांत"), ("late", "देर से")], "Rapid means fast.", "तीव्र यानी तेज़।"),
    (2, "Which word means the opposite of 'expand'?", "'फैलना' का विलोम क्या है?",
     [("shrink", "सिकुड़ना"), ("grow", "बढ़ना"), ("open", "खुलना"), ("spread", "बिखरना")], "To expand is to grow larger; to shrink is to grow smaller.", "फैलना यानी बड़ा होना; सिकुड़ना यानी छोटा होना।"),
    (2, "Which is the odd one out: Mercury, Venus, Moon, Mars?", "इनमें से कौन अलग है: बुध, शुक्र, चंद्रमा, मंगल?",
     [("Moon", "चंद्रमा"), ("Mercury", "बुध"), ("Venus", "शुक्र"), ("Mars", "मंगल")], "The others are planets; the Moon is a satellite.", "बाक़ी ग्रह हैं; चंद्रमा उपग्रह है।"),
    (2, "Choose the word that fits: 'She was so ___ that she fell asleep in class.'", "सही शब्द चुनें: 'वह इतनी ___ थी कि कक्षा में ही सो गई।'",
     [("tired", "थकी"), ("excited", "उत्साहित"), ("hungry", "भूखी"), ("angry", "नाराज़")], "Being tired makes you fall asleep.", "थकान से नींद आती है।"),
    (3, "Which word is closest in meaning to 'reluctant'?", "'अनिच्छुक' के सबसे क़रीबी अर्थ वाला शब्द कौन सा है?",
     [("unwilling", "जिसका मन न हो"), ("eager", "उत्सुक"), ("careful", "सावधान"), ("angry", "ग़ुस्से में")], "Reluctant means not wanting to do something.", "अनिच्छुक यानी कुछ करने का मन न होना।"),
    (3, "Which word is closest in meaning to 'abundant'?", "'प्रचुर' का सबसे क़रीबी अर्थ क्या है?",
     [("plentiful", "भरपूर"), ("rare", "दुर्लभ"), ("empty", "ख़ाली"), ("costly", "महँगा")], "Abundant means more than enough.", "प्रचुर यानी ज़रूरत से ज़्यादा।"),
    (3, "'Although the test was difficult, most students finished it on time.' What does this tell us?",
     "'हालाँकि परीक्षा कठिन थी, फिर भी ज़्यादातर छात्रों ने उसे समय पर पूरा कर लिया।' इससे क्या पता चलता है?",
     [("Most finished even though it was hard", "कठिन होने पर भी ज़्यादातर ने पूरा किया"), ("The test was easy", "परीक्षा आसान थी"),
      ("Most students did not finish", "ज़्यादातर छात्रों ने पूरा नहीं किया"), ("The test had no time limit", "परीक्षा में समय की सीमा नहीं थी")],
     "'Although' sets the difficulty against the result.", "'हालाँकि' कठिनाई और नतीजे का विरोध दिखाता है।"),
    (3, "Pen is to writer as brush is to …?", "जैसे कलम का संबंध लेखक से है, वैसे ही ब्रश का संबंध किससे है?",
     [("painter", "चित्रकार"), ("singer", "गायक"), ("doctor", "डॉक्टर"), ("farmer", "किसान")], "Each is the tool of that worker.", "हर एक उस काम करने वाले का औज़ार है।"),
    (3, "Which word means the opposite of 'transparent'?", "'पारदर्शी' का विलोम क्या है?",
     [("opaque", "अपारदर्शी"), ("clear", "साफ़"), ("bright", "चमकीला"), ("thin", "पतला")], "Light passes through transparent things, not opaque ones.", "पारदर्शी चीज़ से रोशनी आर-पार जाती है, अपारदर्शी से नहीं।"),
    (3, "Choose the word that fits: 'The scientist's ___ was proved right by the experiment.'", "सही शब्द चुनें: 'प्रयोग ने वैज्ञानिक की ___ को सही साबित किया।'",
     [("hypothesis", "परिकल्पना"), ("holiday", "छुट्टी"), ("hobby", "शौक़"), ("hunger", "भूख")], "An experiment tests a hypothesis.", "प्रयोग से परिकल्पना जाँची जाती है।"),
    (4, "Which word is closest in meaning to 'meticulous'?", "'सूक्ष्मदर्शी (बारीकी से काम करने वाला)' के सबसे क़रीबी अर्थ वाला शब्द कौन सा है?",
     [("very careful", "बेहद सावधान"), ("careless", "लापरवाह"), ("quick", "जल्दबाज़"), ("noisy", "शोर करने वाला")], "Meticulous means paying great attention to detail.", "यानी हर छोटी बात पर ध्यान देना।"),
    (4, "Which word means the opposite of 'scarce'?", "'दुर्लभ' का विलोम क्या है?",
     [("plentiful", "प्रचुर"), ("rare", "विरल"), ("tiny", "नन्हा"), ("valuable", "क़ीमती")], "Scarce means there is little of it.", "दुर्लभ यानी जो कम मिले।"),
    (4, "Fire is to ash as tree is to …?", "जैसे आग का संबंध राख से है, वैसे ही पेड़ का संबंध किससे है?",
     [("wood", "लकड़ी"), ("leaf", "पत्ता"), ("forest", "जंगल"), ("root", "जड़")], "Ash is what fire leaves; wood is what a felled tree gives.", "आग से राख बचती है; कटा पेड़ लकड़ी देता है।"),
    (4, "'Not all who wander are lost.' Which statement means the same?", "'हर भटकने वाला खोया हुआ नहीं होता।' किस वाक्य का अर्थ यही है?",
     [("Some people who wander know where they are going", "कुछ भटकने वाले जानते हैं कि वे कहाँ जा रहे हैं"),
      ("Everyone who wanders is lost", "हर भटकने वाला खोया हुआ है"), ("Nobody ever wanders", "कोई कभी नहीं भटकता"),
      ("Lost people never wander", "खोए हुए लोग कभी नहीं भटकते")], "'Not all' means at least some are not.", "'हर… नहीं' यानी कम से कम कुछ नहीं।"),
    (4, "Which is the odd one out: novel, poem, essay, microscope?", "इनमें से कौन अलग है: उपन्यास, कविता, निबंध, सूक्ष्मदर्शी?",
     [("microscope", "सूक्ष्मदर्शी"), ("novel", "उपन्यास"), ("poem", "कविता"), ("essay", "निबंध")], "The others are kinds of writing.", "बाक़ी सब लेखन के प्रकार हैं।"),
    (4, "Choose the word that fits: 'The judge's decision was ___: it could not be changed.'", "सही शब्द चुनें: 'न्यायाधीश का फ़ैसला ___ था: उसे बदला नहीं जा सकता था।'",
     [("final", "अंतिम"), ("flexible", "लचीला"), ("funny", "मज़ेदार"), ("unclear", "अस्पष्ट")], "A decision that can't be changed is final.", "जो फ़ैसला न बदले, वह अंतिम है।"),
    (5, "Which word is closest in meaning to 'ephemeral'?", "'क्षणभंगुर' के सबसे क़रीबी अर्थ वाला शब्द कौन सा है?",
     [("short-lived", "थोड़े समय का"), ("eternal", "शाश्वत"), ("heavy", "भारी"), ("ancient", "प्राचीन")], "Ephemeral things last a very short time.", "क्षणभंगुर चीज़ें बहुत कम समय रहती हैं।"),
    (5, "Which word means the opposite of 'benevolent'?", "'परोपकारी' का विलोम क्या है?",
     [("malicious", "द्वेषी"), ("kind", "दयालु"), ("wealthy", "धनी"), ("cheerful", "प्रसन्न")], "Benevolent means wishing others well; malicious, wishing them harm.", "परोपकारी दूसरों का भला चाहता है; द्वेषी बुरा।"),
    (5, "Architect is to blueprint as composer is to …?", "जैसे वास्तुकार का संबंध नक़्शे से है, वैसे ही संगीतकार का संबंध किससे है?",
     [("score", "स्वरलिपि"), ("concert", "संगीत-सभा"), ("piano", "पियानो"), ("audience", "श्रोता")], "Each plans the work on paper first: a blueprint, a score.", "दोनों पहले काग़ज़ पर योजना बनाते हैं: नक़्शा, स्वरलिपि।"),
    (5, "'His argument was cogent.' What does 'cogent' mean here?", "'उसका तर्क अकाट्य था।' यहाँ 'अकाट्य' का क्या अर्थ है?",
     [("clear and convincing", "स्पष्ट और विश्वसनीय"), ("long and boring", "लंबा और उबाऊ"), ("angry", "ग़ुस्से भरा"), ("confused", "उलझा हुआ")],
     "A cogent argument persuades because it is clear and logical.", "अकाट्य तर्क स्पष्ट और तार्किक होने से मनवा लेता है।"),
    (5, "Choose the word that fits: 'Despite repeated warnings, he remained ___ and refused to change his plan.'",
     "सही शब्द चुनें: 'बार-बार चेतावनी के बावजूद वह ___ रहा और अपनी योजना नहीं बदली।'",
     [("obstinate", "ज़िद्दी"), ("obedient", "आज्ञाकारी"), ("anxious", "चिंतित"), ("absent", "अनुपस्थित")], "Refusing to change despite warnings is being obstinate.", "चेतावनी के बाद भी न बदलना ज़िद है।"),
    (5, "Which is the odd one out: perimeter, area, volume, velocity?", "इनमें से कौन अलग है: परिमाप, क्षेत्रफल, आयतन, वेग?",
     [("velocity", "वेग"), ("perimeter", "परिमाप"), ("area", "क्षेत्रफल"), ("volume", "आयतन")], "The others measure the size of shapes; velocity measures motion.", "बाक़ी आकृतियों का माप हैं; वेग गति का।"),
    # 2026-10-05: four more per level, so three takes in a row never repeat a question.
    (1, "Which word means the opposite of 'hot'?", "'गर्म' का विलोम क्या है?",
     [("cold", "ठंडा"), ("warm", "गुनगुना"), ("wet", "गीला"), ("soft", "मुलायम")], "Hot and cold are opposites.", "गर्म और ठंडा उल्टे हैं।"),
    (1, "Which is the odd one out: dog, cat, cow, eagle?", "इनमें से कौन अलग है: कुत्ता, बिल्ली, गाय, गरुड़?",
     [("eagle", "गरुड़"), ("dog", "कुत्ता"), ("cat", "बिल्ली"), ("cow", "गाय")], "The eagle is a bird; the others are four-legged animals.", "गरुड़ पक्षी है; बाक़ी चार पैरों वाले जानवर हैं।"),
    (1, "Which word means the same as 'happy'?", "'प्रसन्न' का समानार्थी शब्द कौन सा है?",
     [("glad", "ख़ुश"), ("sad", "दुखी"), ("tired", "थका हुआ"), ("angry", "नाराज़")], "Glad and happy mean the same.", "ख़ुश और प्रसन्न का अर्थ एक है।"),
    (1, "Pen is to ink as car is to …?", "जैसे कलम का संबंध स्याही से है, वैसे ही कार का संबंध किससे है?",
     [("petrol", "पेट्रोल"), ("road", "सड़क"), ("wheel", "पहिया"), ("driver", "चालक")], "A pen runs on ink; a car runs on petrol.", "कलम स्याही से चलती है; कार पेट्रोल से।"),
    (2, "Which word means the opposite of 'victory'?", "'जीत' का विलोम क्या है?",
     [("defeat", "हार"), ("prize", "इनाम"), ("game", "खेल"), ("team", "टीम")], "Victory and defeat are opposites.", "जीत और हार उल्टे हैं।"),
    (2, "Which word means the same as 'begin'?", "'आरंभ करना' का समानार्थी कौन सा है?",
     [("start", "शुरू करना"), ("finish", "ख़त्म करना"), ("stop", "रोकना"), ("wait", "रुकना")], "Begin and start mean the same.", "आरंभ करना और शुरू करना एक ही है।"),
    (2, "Which is the odd one out: triangle, square, circle, cube?", "इनमें से कौन अलग है: त्रिभुज, वर्ग, वृत्त, घन?",
     [("cube", "घन"), ("triangle", "त्रिभुज"), ("square", "वर्ग"), ("circle", "वृत्त")], "A cube is solid (3D); the others are flat shapes.", "घन ठोस (3D) है; बाक़ी समतल आकृतियाँ हैं।"),
    (2, "Choose the word that fits: 'It was raining, so we took an ___.'", "सही शब्द चुनें: 'बारिश हो रही थी, इसलिए हमने ___ लिया।'",
     [("umbrella", "छाता"), ("apple", "सेब"), ("orange", "संतरा"), ("eraser", "रबर")], "An umbrella keeps the rain off.", "छाता बारिश से बचाता है।"),
    (3, "Which word is closest in meaning to 'fragile'?", "'नाज़ुक' के सबसे क़रीबी अर्थ वाला शब्द कौन सा है?",
     [("easily broken", "आसानी से टूटने वाला"), ("very strong", "बहुत मज़बूत"), ("heavy", "भारी"), ("colourful", "रंगीन")],
     "Fragile things break easily.", "नाज़ुक चीज़ें आसानी से टूट जाती हैं।"),
    (3, "Which word means the opposite of 'permanent'?", "'स्थायी' का विलोम क्या है?",
     [("temporary", "अस्थायी"), ("lasting", "टिकाऊ"), ("fixed", "तय"), ("old", "पुराना")], "Permanent lasts; temporary doesn't.", "स्थायी टिकता है; अस्थायी नहीं।"),
    (3, "Teacher is to students as doctor is to …?", "जैसे शिक्षक का संबंध छात्रों से है, वैसे ही डॉक्टर का संबंध किससे है?",
     [("patients", "मरीज़"), ("medicines", "दवाइयाँ"), ("nurses", "नर्सें"), ("hospitals", "अस्पताल")], "The people each one looks after.", "जिन लोगों की देखभाल हर कोई करता है।"),
    (3, "'She did not just pass the exam; she topped it.' What does this tell us?", "'वह परीक्षा में सिर्फ़ पास नहीं हुई, बल्कि सबसे आगे रही।' इससे क्या पता चलता है?",
     [("She got the highest marks", "उसके सबसे ज़्यादा अंक आए"), ("She failed", "वह फ़ेल हो गई"), ("She barely passed", "वह मुश्किल से पास हुई"),
      ("She missed the exam", "उसने परीक्षा नहीं दी")], "'Not just… but' adds something bigger: she came first.", "'सिर्फ़… नहीं, बल्कि' कुछ बड़ा जोड़ता है: वह सबसे आगे रही।"),
    (4, "Which word is closest in meaning to 'diligent'?", "'परिश्रमी' के सबसे क़रीबी अर्थ वाला शब्द कौन सा है?",
     [("hard-working", "मेहनती"), ("lazy", "आलसी"), ("clever", "चालाक"), ("polite", "विनम्र")], "Diligent people work hard and carefully.", "परिश्रमी लोग लगन से मेहनत करते हैं।"),
    (4, "Which word means the opposite of 'artificial'?", "'कृत्रिम' का विलोम क्या है?",
     [("natural", "प्राकृतिक"), ("fake", "नक़ली"), ("modern", "आधुनिक"), ("useful", "उपयोगी")], "Artificial is made by people; natural is not.", "कृत्रिम इंसान बनाते हैं; प्राकृतिक नहीं।"),
    (4, "Seed is to tree as egg is to …?", "जैसे बीज का संबंध पेड़ से है, वैसे ही अंडे का संबंध किससे है?",
     [("bird", "पक्षी"), ("nest", "घोंसला"), ("shell", "छिलका"), ("food", "भोजन")], "What each one grows into.", "हर एक जिसमें बदलकर बड़ा होता है।"),
    (4, "Which is the odd one out: metre, kilometre, centimetre, kilogram?", "इनमें से कौन अलग है: मीटर, किलोमीटर, सेंटीमीटर, किलोग्राम?",
     [("kilogram", "किलोग्राम"), ("metre", "मीटर"), ("kilometre", "किलोमीटर"), ("centimetre", "सेंटीमीटर")], "The others measure length; a kilogram measures mass.", "बाक़ी लंबाई के माप हैं; किलोग्राम भार का।"),
    (5, "Which word is closest in meaning to 'ambiguous'?", "'द्वयर्थक' के सबसे क़रीबी अर्थ वाला शब्द कौन सा है?",
     [("having more than one meaning", "एक से ज़्यादा अर्थ वाला"), ("very clear", "बिल्कुल साफ़"), ("extremely large", "बहुत बड़ा"),
      ("done quickly", "जल्दी किया हुआ")], "An ambiguous sentence can be read in more than one way.", "द्वयर्थक वाक्य के एक से ज़्यादा अर्थ निकल सकते हैं।"),
    (5, "Which word means the opposite of 'frugal'?", "'मितव्ययी' का विलोम क्या है?",
     [("extravagant", "फ़िज़ूलख़र्च"), ("careful", "सावधान"), ("poor", "ग़रीब"), ("thrifty", "किफ़ायती")], "Frugal people spend little; extravagant people spend a lot.", "मितव्ययी कम ख़र्च करते हैं; फ़िज़ूलख़र्च बहुत।"),
    (5, "Drought is to water as famine is to …?", "जैसे सूखे का संबंध पानी की कमी से है, वैसे ही अकाल का संबंध किसकी कमी से है?",
     [("food", "भोजन"), ("rain", "बारिश"), ("money", "पैसा"), ("land", "ज़मीन")], "A drought is a lack of water; a famine, of food.", "सूखा पानी की कमी है; अकाल भोजन की।"),
    (5, "'The evidence was circumstantial.' What does this suggest?", "'सबूत परिस्थितिजन्य थे।' इससे क्या पता चलता है?",
     [("It pointed to the answer but did not prove it directly", "वे जवाब की ओर इशारा करते थे, पर सीधे साबित नहीं करते थे"),
      ("It proved everything beyond doubt", "उन्होंने बिना शक के सब साबित कर दिया"), ("It was completely made up", "वे पूरी तरह गढ़े गए थे"),
      ("There was no evidence", "कोई सबूत नहीं था")], "Circumstantial evidence suggests, without proving directly.", "परिस्थितिजन्य सबूत इशारा करते हैं, सीधे साबित नहीं करते।"),
]


def verbal_items() -> list[dict]:
    out, count = [], {}
    for level, en, hi, options, why_en, why_hi in VERBAL:
        count[level] = count.get(level, 0) + 1
        out.append({"key": f"verb_L{level}_{count[level]:02d}", "level": level, "prompt": T(en, hi),
                    "options": [T(o_en, o_hi) for o_en, o_hi in options], "why": T(why_en, why_hi)})
    return out


# ---------------- spatial ----------------

HALF_TURN = {"b": "q", "q": "b", "d": "p", "p": "d", "n": "u", "u": "n", "M": "W", "W": "M", "6": "9", "9": "6"}
MIRROR = {"b": "d", "d": "b", "p": "q", "q": "p"}


def spatial(level: int, rng: random.Random) -> Q:
    kind = rng.choice({
        1: ["turn", "half_turn", "fold"],
        2: ["turn", "mirror_letter", "fold", "dice"],
        3: ["cube", "clock_mirror", "cuts"],
        4: ["cube", "clock_mirror", "directions"],
        5: ["cube_any", "cube_big", "directions", "clock_mirror"],
    }[level])
    if kind == "turn":
        q = logic(1, rng)
        while "face" not in q.prompt["en"]:
            q = logic(1, rng)
        return q
    if kind == "half_turn":
        ch = rng.choice(list(HALF_TURN))
        right = HALF_TURN[ch]
        wrong = [c for c in rng.sample("bdpqnuMW69", 10) if c not in (right,)][:3]
        if ch in wrong:
            wrong = [c for c in "bdpqnuMW69" if c not in (right, ch)][:2] + [ch]
        return Q(T(f"Turn the character {ch} upside down — half a turn. What does it look like now?",
                   f"{ch} को आधा घुमाकर उल्टा कीजिए। अब वह कैसा दिखता है?"),
                 right, wrong[:3], T(f"Half a turn swaps top with bottom and left with right: {ch} becomes {right}.",
                                     f"आधा घुमाव ऊपर-नीचे और दाएँ-बाएँ बदल देता है: {ch} {right} बन जाता है।"))
    if kind == "mirror_letter":
        ch = rng.choice(list(MIRROR))
        right = MIRROR[ch]
        wrong = [c for c in "bdpq" if c != right][:3]
        return Q(T(f"You hold the small letter {ch} up to a mirror. Which letter do you see?", f"छोटे अक्षर {ch} को आईने के सामने रखें। आईने में कौन सा अक्षर दिखेगा?"),
                 right, wrong, T("A mirror swaps left and right, but not top and bottom.", "आईना दाएँ-बाएँ बदलता है, ऊपर-नीचे नहीं।"))
    if kind == "fold":
        n = rng.choice([1, 2, 3]) if level == 2 else rng.choice([1, 2])
        holes = rng.choice([1, 2])
        r = holes * 2 ** n
        words = {1: ("in half once", "एक बार आधा"), 2: ("in half, then in half again", "आधा, फिर दोबारा आधा"),
                 3: ("in half three times", "तीन बार आधा")}[n]
        return Q(T(f"A sheet of paper is folded {words[0]}. You punch {holes} hole{'s' if holes > 1 else ''} through all the layers. "
                   "How many holes are there when you open it?", f"एक कागज़ को {words[1]} मोड़ा गया। सारी परतों में {holes} छेद किए गए। खोलने पर कितने छेद होंगे?"),
                 r, near(rng, r, [-holes, holes, r]), T(f"{n} fold{'s' if n > 1 else ''} make {2 ** n} layers; {holes} × {2 ** n} = {r}.",
                                                        f"{n} बार मोड़ने से {2 ** n} परतें; {holes} × {2 ** n} = {r}।"))
    if kind == "dice":
        top = rng.randint(1, 6)
        return Q(T(f"On a normal die, opposite faces always add up to 7. If {top} is on top, what is on the bottom?",
                   f"एक साधारण पासे पर आमने-सामने के अंकों का जोड़ हमेशा 7 होता है। ऊपर {top} है, तो नीचे क्या होगा?"),
                 7 - top, [x for x in rng.sample(range(1, 7), 6) if x not in (7 - top, top)][:2] + [top],
                 T(f"7 − {top} = {7 - top}.", f"7 − {top} = {7 - top}।"))
    if kind == "cuts":
        k = rng.randint(2, 5)
        r = 2 * k
        return Q(T(f"A round cake is cut with {k} straight cuts, each through the centre. How many pieces are there?",
                   f"एक गोल केक को {k} सीधे कट से काटा गया, हर कट बीच से होकर। कितने टुकड़े बने?"),
                 r, near(rng, r, [-k, 1, -1, k * k - r]), T(f"Each cut through the centre adds two pieces: {k} × 2 = {r}.",
                                                           f"बीच से हर कट दो टुकड़े जोड़ता है: {k} × 2 = {r}।"))
    if kind in ("cube", "cube_any", "cube_big"):
        n = rng.choice([3, 4]) if kind == "cube" else rng.choice([4, 5])
        counts = {3: 8, 2: 12 * (n - 2), 1: 6 * (n - 2) ** 2, 0: (n - 2) ** 3}
        if kind == "cube_any":
            r = n ** 3 - (n - 2) ** 3
            return Q(T(f"A cube painted on every face is cut into {n ** 3} equal small cubes ({n} by {n} by {n}). How many small cubes have at least one painted face?",
                       f"हर सतह से रंगा एक घन {n ** 3} बराबर छोटे घनों ({n} × {n} × {n}) में काटा गया। कितने छोटे घनों पर कम से कम एक सतह रंगी है?"),
                     r, [(n - 2) ** 3, 6 * n * n, r - 8], T(f"All but the hidden inner {n - 2}×{n - 2}×{n - 2} = {(n - 2) ** 3}: {n ** 3} − {(n - 2) ** 3} = {r}.",
                                                            f"भीतर छिपे {(n - 2) ** 3} को छोड़कर: {n ** 3} − {(n - 2) ** 3} = {r}।"))
        faces = rng.choice([3, 2, 1, 0])
        r = counts[faces]
        ask = {3: ("exactly three painted faces", "ठीक तीन सतहें रंगी"), 2: ("exactly two painted faces", "ठीक दो सतहें रंगी"),
               1: ("exactly one painted face", "ठीक एक सतह रंगी"), 0: ("no paint at all", "कोई भी सतह रंगी नहीं")}[faces]
        why = {3: ("the 8 corners", "8 कोने"), 2: (f"the middles of the 12 edges: 12 × {n - 2}", f"12 किनारों के बीच वाले: 12 × {n - 2}"),
               1: (f"the middles of the 6 faces: 6 × {n - 2}²", f"6 सतहों के बीच वाले: 6 × {n - 2}²"),
               0: (f"the hidden inside: {n - 2}³", f"भीतर छिपे: {n - 2}³")}[faces]
        wrong = [v for v in dict.fromkeys([counts[f] for f in (3, 2, 1, 0) if f != faces] + [r + 4, r * 2 or 6]) if v != r][:3]
        return Q(T(f"A cube painted on every face is cut into {n ** 3} equal small cubes ({n} by {n} by {n}). How many small cubes have {ask[0]}?",
                   f"हर सतह से रंगा एक घन {n ** 3} बराबर छोटे घनों ({n} × {n} × {n}) में काटा गया। कितने छोटे घनों पर {ask[1]} है?"),
                 r, wrong, T(f"Those are {why[0]} = {r}.", f"ये हैं {why[1]} = {r}।"))
    if kind == "clock_mirror":
        h, m = rng.randint(1, 11), rng.choice([0, 10, 15, 20, 25, 35, 40, 50]) if level < 5 else rng.randint(1, 59)
        total = (720 - (h * 60 + m)) % 720 or 720
        mh, mm = divmod(total, 60)
        mh = mh or 12
        fmt = lambda v: f"{v[0]}:{v[1]:02d}"
        wrong = [((h + 6) % 12 or 12, m), (mh, (60 - mm) % 60) if (mh, (60 - mm) % 60) != (mh, mm) else (mh, (mm + 5) % 60), (h, m)]
        return Q(T(f"A clock shows {h}:{m:02d}. What time does it seem to show in a mirror?", f"घड़ी में {h}:{m:02d} बजे हैं। आईने में वह कितने बजे दिखेगी?"),
                 (mh, mm), wrong, T(f"Subtract from 11:60 (that is, 12:00): the mirror shows {mh}:{mm:02d}.",
                                    f"11:60 (यानी 12:00) में से घटाएँ: आईने में {mh}:{mm:02d}।"), fmt)
    # directions
    q = logic(5, rng)
    while "walks" not in q.prompt["en"]:
        q = logic(5, rng)
    return q


# ---------------- reading code ----------------

def code(level: int, rng: random.Random) -> Q:
    """Pseudo-code in the coding check's style; the answer comes from running the same steps."""
    if level == 1:
        a, b, c = rng.randint(2, 9), rng.randint(2, 9), rng.randint(2, 5)
        src = f"x = {a}\ny = {b}\nx = x + y\ny = x * {c}"
        x = a + b
        y = x * c
        ask, right = rng.choice([("x", x), ("y", y)])
        wrong = near(rng, right, [b * c - right if b * c != right else 1, a - right if a != right else 2, 3, -1])
        return Q(T(f"What is {ask} at the end?", f"आख़िर में {ask} क्या है?"), right, wrong,
                 T(f"x becomes {a} + {b} = {x}; then y = {x} × {c} = {y}.", f"x = {a} + {b} = {x}; फिर y = {x} × {c} = {y}।"), code=src)
    if level == 2:
        a, b, c = rng.randint(5, 30), rng.randint(5, 30), rng.randint(2, 9)
        src = f"x = {a}\nif x > {b}:\n    x = x - {c}\nelse:\n    x = x + {c}"
        right = a - c if a > b else a + c
        return Q(T("What is x at the end?", "आख़िर में x क्या है?"), right, [a, a + c if right != a + c else a - c, right + 1],
                 T(f"{a} {'>' if a > b else 'is not more than'} {b}, so x becomes {right}.",
                   f"{a} {'>' if a > b else 'बड़ा नहीं है'} {b}, इसलिए x = {right}।"), code=src)
    if level == 3:
        n, k = rng.randint(4, 8), rng.choice([1, 2, 3])
        src = f"total = 0\nrepeat for i = 1 to {n}:\n    total = total + i * {k}"
        right = k * n * (n + 1) // 2
        return Q(T("What is total at the end?", "आख़िर में total क्या है?"), right,
                 [n * k, k * (n - 1) * n // 2, right + k], T(f"{k} × (1 + 2 + … + {n}) = {right}.", f"{k} × (1 + 2 + … + {n}) = {right}।"), code=src)
    if level == 4:
        if rng.random() < 0.5:
            n, d = rng.randint(15, 40), rng.choice([3, 4, 5, 6, 7])
            src = f"count = 0\nrepeat for i = 1 to {n}:\n    if i % {d} == 0:\n        count = count + 1"
            right = n // d
            return Q(T("What is count at the end? (% gives the remainder)", "आख़िर में count क्या है? (% शेषफल देता है)"), right,
                     near(rng, right, [1, -1, n % d or 2]), T(f"Multiples of {d} up to {n}: {right}.", f"{n} तक {d} के गुणज: {right}।"), code=src)
        a, b, c = rng.randint(30, 90), rng.randint(5, 20), rng.randint(3, 9)
        src = f"x = {a}\nwhile x > {b}:\n    x = x - {c}"
        x = a
        while x > b:
            x -= c
        return Q(T("What is x at the end?", "आख़िर में x क्या है?"), x, near(rng, x, [c, -c, 1, b - x if b != x else 2]),
                 T(f"Take away {c} until x is no longer more than {b}: {x}.", f"x के {b} से बड़ा न रहने तक {c} घटाते रहें: {x}।"), code=src)
    kind = rng.choice(["nested", "list", "recursion"])
    if kind == "nested":
        a, b = rng.randint(2, 4), rng.randint(2, 4)
        src = f"s = 0\nrepeat for i = 1 to {a}:\n    repeat for j = 1 to {b}:\n        s = s + i * j"
        right = sum(i * j for i in range(1, a + 1) for j in range(1, b + 1))
        return Q(T("What is s at the end?", "आख़िर में s क्या है?"), right, near(rng, right, [a * b - right, a + b, -a]),
                 T(f"(1 + … + {a}) × (1 + … + {b}) = {right}.", f"(1 + … + {a}) × (1 + … + {b}) = {right}।"), code=src)
    if kind == "list":
        nums = rng.sample(range(1, 30), 6)
        k = sorted(nums)[2]
        src = f"nums = {nums}\ntotal = 0\nfor each x in nums:\n    if x > {k}:\n        total = total + x"
        right = sum(x for x in nums if x > k)
        return Q(T("What is total at the end?", "आख़िर में total क्या है?"), right,
                 near(rng, right, [k, sum(x for x in nums if x >= k) - right or 3, -min(nums)]),
                 T(f"Only the numbers bigger than {k} are added: {right}.", f"सिर्फ़ {k} से बड़ी संख्याएँ जुड़ती हैं: {right}।"), code=src)
    n = rng.randint(3, 6)
    src = "function f(n):\n    if n == 0:\n        return 0\n    return n + f(n - 1)\n\n" + f"answer = f({n})"
    right = n * (n + 1) // 2
    return Q(T("What is answer at the end?", "आख़िर में answer क्या है?"), right, near(rng, right, [n - right, -1, n]),
             T(f"f({n}) = {n} + {n - 1} + … + 1 + 0 = {right}.", f"f({n}) = {n} + {n - 1} + … + 1 + 0 = {right}।"), code=src)


# ---------------- building the files ----------------

SECTIONS = {"aptitude:numerical": T("Numbers", "संख्याएँ"), "aptitude:logical": T("Logic", "तर्क"),
            "aptitude:verbal": T("Words", "शब्द"), "aptitude:spatial": T("Space and shape", "जगह और आकार"),
            "check:programming": T("Code", "कोड")}


def bank(dimension: str, make, rng: random.Random, prefix: str) -> list[dict]:
    items = []
    for level in range(1, LEVELS + 1):
        seen, tries = set(), 0
        while sum(1 for i in items if i["difficulty"] == level) < PER_LEVEL and tries < 500:
            tries += 1
            q = make(level, rng)
            built = _options(rng, q)
            key = (q.prompt["en"], q.code)
            if built is None or key in seen:
                continue
            seen.add(key)
            options, answer = built
            n = sum(1 for i in items if i["difficulty"] == level) + 1
            item = {"key": f"{prefix}_L{level}_{n:02d}", "type": "problem", "form": None, "dimension": dimension,
                    "difficulty": level, "section": SECTIONS[dimension], "prompt": q.prompt, "options": options,
                    "answer": answer, "explanation": q.why}
            if q.code:
                item["code"] = q.code
                item["speak"] = T("Look at the code on the screen. " + q.prompt["en"], "स्क्रीन पर कोड देखिए। " + q.prompt["hi"])
            items.append(item)
        assert sum(1 for i in items if i["difficulty"] == level) >= PER_LEVEL, f"{dimension} L{level}: too few distinct questions"
    return items


def verbal_bank(rng: random.Random) -> list[dict]:
    items = []
    for v in verbal_items():
        right, wrong = v["options"][0], v["options"][1:]
        q = Q(v["prompt"], right, wrong, v["why"], lambda o: o)
        options, answer = _options(rng, q)
        items.append({"key": v["key"], "type": "problem", "form": None, "dimension": "aptitude:verbal", "difficulty": v["level"],
                      "section": SECTIONS["aptitude:verbal"], "prompt": v["prompt"], "options": options, "answer": answer,
                      "explanation": v["why"]})
    return items


def main() -> None:
    rng = random.Random(20261005)
    common = {"scoring_method": "adaptive_correct", "forms": []}
    aptitude = {
        "key": "aptitude", "version": 2, "category": "aptitude",
        "title": T("Thinking skills", "सोचने की क्षमता"),
        "about": T("15 problems with numbers, logic and words that get harder or easier with your answers — and are "
                   "different each time. It shows how you did today, nothing more.",
                   "संख्याओं, तर्क और शब्दों के 15 सवाल, जो आपके जवाबों के साथ कठिन या आसान होते हैं — और हर बार अलग। "
                   "यह बस बताता है कि आज आपने कैसा किया।"),
        "intro": T("Fifteen problems — numbers, logic and words. A right answer makes the next one harder, a wrong one "
                   "makes it easier, so don't worry if they get tough. If you're not sure, have a go or say skip.",
                   "पंद्रह सवाल — संख्याएँ, तर्क और शब्द। सही जवाब पर अगला सवाल कठिन होगा, ग़लत पर आसान, इसलिए "
                   "कठिन लगें तो घबराइए मत। पक्का न हो तो अंदाज़ा लगाइए या 'छोड़ो' कहिए।"),
        "est_minutes": 12, **common,
        "adaptive": {"per_dimension": 5, "levels": LEVELS, "start": START},
        "dimensions": {"aptitude:numerical": {"en": "working with numbers", "hi": "संख्याओं के साथ काम", "group": "aptitude"},
                       "aptitude:logical": {"en": "logical reasoning", "hi": "तार्किक सोच", "group": "aptitude"},
                       "aptitude:verbal": {"en": "understanding words", "hi": "शब्दों की समझ", "group": "aptitude"}},
        "items": bank("aptitude:numerical", num, rng, "num") + bank("aptitude:logical", logic, rng, "log") + verbal_bank(rng),
    }
    spatial_test = {
        "key": "spatial", "version": 2, "category": "aptitude",
        "title": T("Space and shape", "जगह और आकार"),
        "about": T("8 puzzles about directions, folding, mirrors and shapes — all in your head. They get harder or "
                   "easier with your answers, and change every time.",
                   "दिशाओं, मोड़ने, आईने और आकारों पर 8 पहेलियाँ — सब मन में। आपके जवाबों से कठिन या आसान होती हैं, और हर बार बदलती हैं।"),
        "intro": T("Eight puzzles about space and shape — picture each one in your head. If you're not sure, have a go or say skip.",
                   "जगह और आकार की आठ पहेलियाँ — हर एक को मन में सोचिए। पक्का न हो तो अंदाज़ा लगाइए या 'छोड़ो' कहिए।"),
        "est_minutes": 6, **common,
        "adaptive": {"per_dimension": 8, "levels": LEVELS, "start": START},
        "dimensions": {"aptitude:spatial": {"en": "thinking in space and shape", "hi": "जगह और आकार में सोचना", "group": "aptitude"}},
        "items": bank("aptitude:spatial", spatial, rng, "spa"),
    }
    coding = {
        "key": "coding_check", "version": 2, "category": "skill",
        "title": T("Coding check", "कोडिंग जाँच"),
        "about": T("8 short pieces of code to read — no programming language needed. They get harder as you get them "
                   "right, and change every time. Best done on the screen.",
                   "पढ़ने के लिए कोड के 8 छोटे टुकड़े — कोई प्रोग्रामिंग भाषा आना ज़रूरी नहीं। सही जवाबों के साथ कठिन होते जाते हैं, "
                   "और हर बार बदलते हैं। स्क्रीन पर करना सबसे अच्छा है।"),
        "intro": T("Eight short pieces of code. You don't need to know any programming language — just follow what each "
                   "line does. It's easiest on the screen.",
                   "कोड के आठ छोटे टुकड़े। कोई प्रोग्रामिंग भाषा आना ज़रूरी नहीं — बस देखिए कि हर लाइन क्या करती है। स्क्रीन पर करना सबसे आसान है।"),
        "est_minutes": 7, **common,
        "adaptive": {"per_dimension": 8, "levels": LEVELS, "start": {**START, "6": 1, "7": 1, "8": 1, "9": 1, "10": 2}},
        "dimensions": {"check:programming": {"en": "reading code", "hi": "कोड पढ़ना", "group": "skill"}},
        "items": bank("check:programming", code, rng, "code"),
    }
    for inst in (aptitude, spatial_test, coding):
        path = OUT / f"{inst['key']}.v{inst['version']}.json"
        path.write_text(json.dumps(inst, ensure_ascii=False, indent=1) + "\n")
        print(f"{path.name}: {len(inst['items'])} questions")


if __name__ == "__main__":
    main()
