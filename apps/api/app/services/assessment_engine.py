"""MAYA's career assessment: a conversation instead of sliders, and a ranking that says
plainly which careers fit best and which don't.

How it scores, in full (nothing is hidden, so every result can be explained):

1. Every answer adds points to dimensions — "I love maths" adds 3 to maths; "I'd rather stay
   away from hospitals" adds 0 to blood_ok. The student's level on a dimension is their
   points divided by the most they could have scored on the questions actually asked
   (follow-up questions only appear for subjects they like, so this keeps it fair).
   A dimension no question touched counts as neutral (0.5).
2. Each career says how much it draws on each dimension (0-3, in careers.json). Its fit is
   the weighted average of the student's levels on those dimensions.
3. Careers list a few dimensions they genuinely can't do without (a doctor has to be
   comfortable in hospitals). A very low level on one of those costs 25% of the fit.
4. Careers are ranked by fit. Labels come from the score, and the top one is called out.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

BANK = Path(__file__).resolve().parent.parent / "seed" / "assessment_questions.json"
NEUTRAL = 0.5
MUST_THRESHOLD = 0.35
MUST_PENALTY = 0.75

LABELS = [  # (minimum score, label) — checked top down
    (72, "Strong fit"),
    (58, "Good fit"),
    (45, "Worth exploring"),
    (30, "Less likely"),
    (0, "Not a natural fit"),
]

# How each dimension reads in a sentence, for the "why" and "watch out" lines.
LIKES = {
    "maths": "you enjoy maths", "physics": "you like physics", "chemistry": "you like chemistry",
    "biology": "you like biology", "computer": "you enjoy computers and coding",
    "commerce": "business and money interest you", "arts": "you enjoy drawing and design",
    "language": "you enjoy reading, writing and speaking", "society": "history and how the country runs interest you",
    "realistic": "you like hands-on building and fixing", "investigative": "you love figuring out how things work",
    "artistic": "you're creative", "social": "you care about helping people",
    "enterprising": "you like leading and persuading", "conventional": "you're organised and careful",
    "communication": "you're comfortable talking with people", "outdoor": "you'd enjoy active, on-site work",
    "blood_ok": "hospitals don't bother you", "long_study": "you're ready for a long study path",
    "stability": "you value a secure job", "money": "earning well matters to you", "tech": "you're into technology",
    "clinical": "you want to diagnose and treat patients",
    "caregiving": "you want to care for patients day to day",
}
NEEDS = {
    "maths": "a lot of maths", "physics": "a lot of physics", "chemistry": "a lot of chemistry",
    "biology": "a lot of biology", "computer": "a lot of coding", "commerce": "working with money and business",
    "arts": "drawing and visual design", "language": "a lot of reading and writing", "society": "keen interest in society and current affairs",
    "realistic": "hands-on practical work", "investigative": "deep analytical work", "artistic": "constant creativity",
    "social": "caring for people every day", "enterprising": "leading and persuading others",
    "conventional": "careful, detailed work", "communication": "talking to people all day",
    "outdoor": "active or on-site work", "blood_ok": "being comfortable with blood and hospitals",
    "long_study": "many years of study", "stability": "patience for a slow, steady path",
    "money": "a focus on earnings", "tech": "comfort with technology",
    "clinical": "diagnosing and treating patients",
    "caregiving": "caring for patients day to day",
}


@lru_cache(maxsize=1)
def load_bank() -> dict:
    return json.loads(BANK.read_text())


def questions_asked(answers: dict[str, str]) -> list[dict]:
    """The questions this conversation actually included: every unconditional question,
    plus follow-ups whose condition was met by the answers given."""
    asked = []
    for q in load_bank()["questions"]:
        requires = q.get("requires")
        if requires and not all(answers.get(qid) in options for qid, options in requires.items()):
            continue
        asked.append(q)
    return asked


def dimension_levels(answers: dict[str, str]) -> dict[str, float]:
    """Each dimension as 0..1: points earned over the most that was possible."""
    earned: dict[str, float] = {}
    possible: dict[str, float] = {}
    for q in questions_asked(answers):
        best: dict[str, float] = {}
        for option in q["options"]:
            for dim, w in option["weights"].items():
                best[dim] = max(best.get(dim, 0.0), w)
        chosen = next((o for o in q["options"] if o["id"] == answers.get(q["id"])), None)
        if chosen is None:
            continue  # skipped: says nothing either way, so it doesn't count against anything
        for dim, top in best.items():
            possible[dim] = possible.get(dim, 0.0) + top
            earned[dim] = earned.get(dim, 0.0) + chosen["weights"].get(dim, 0.0)
    levels = {}
    for dim in load_bank()["dimensions"]:
        levels[dim] = earned.get(dim, 0.0) / possible[dim] if possible.get(dim) else NEUTRAL
    return levels


def label_for(score: float) -> str:
    return next(label for minimum, label in LABELS if score >= minimum)


def score_career(profile: dict[str, float], must: list[str], levels: dict[str, float]) -> dict:
    total_weight = sum(profile.values()) or 1.0
    fit = sum(w * levels.get(dim, NEUTRAL) for dim, w in profile.items()) / total_weight
    missing = [dim for dim in must if levels.get(dim, NEUTRAL) < MUST_THRESHOLD]
    if missing:
        fit *= MUST_PENALTY
    contributions = sorted(
        ((w * levels.get(dim, NEUTRAL), dim) for dim, w in profile.items() if levels.get(dim, NEUTRAL) >= 0.6),
        reverse=True,
    )
    reasons = [LIKES[dim] for _c, dim in contributions[:3]]
    gaps = [
        dim for dim, w in sorted(profile.items(), key=lambda kv: -kv[1])
        if w >= 2 and levels.get(dim, NEUTRAL) < 0.4
    ]
    watch_outs = [f"it needs {NEEDS[dim]}, which you rated low" for dim in (missing + [g for g in gaps if g not in missing])[:3]]
    score = round(fit * 100, 1)
    return {"score": score, "reasons": reasons, "watch_outs": watch_outs}


def rank_careers(careers: list, answers: dict[str, str]) -> list[dict]:
    """Every career, best fit first."""
    levels = dimension_levels(answers)
    ranked = []
    for career in careers:
        result = score_career(career.profile or {}, career.must or [], levels)
        ranked.append({"career": career, **result})
    ranked.sort(key=lambda r: -r["score"])
    for position, r in enumerate(ranked):
        r["rank"] = position + 1
        r["label"] = label_for(r["score"])
    if ranked:
        ranked[0]["label"] = "Best match" if ranked[0]["score"] >= 45 else "Closest match"
    return ranked


def top_dimensions(answers: dict[str, str], n: int = 4) -> list[str]:
    """What stood out about the student, for the summary line."""
    levels = dimension_levels(answers)
    touched = {dim for q in questions_asked(answers) for o in q["options"] for dim in o["weights"]}
    strongest = sorted((lvl, dim) for dim, lvl in levels.items() if dim in touched and lvl >= 0.66)
    return [LIKES[dim] for _lvl, dim in reversed(strongest[-n:])]
