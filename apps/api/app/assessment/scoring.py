"""Turning one attempt's answers into scores per dimension — four methods, all simple enough to
explain to the student who took it:

- weighted_options (interests): each answer adds points to dimensions; a dimension's score is
  the points earned over the most the asked questions could give (MAYA's original method — a
  follow-up only asked because you like a subject doesn't count against anything).
- correct_answers (aptitude, coding check): right answers over questions shown, per dimension.
  A skipped question counts as shown and not right — "7 of 10 right, 1 skipped".
- adaptive_correct (aptitude, spatial, coding check since v2): the questions get harder after a right
  answer and easier after a wrong one, so the count of right answers alone says little. Each question
  is worth its level if right and one less if not (a hard question missed still says more than an easy
  one missed); the score is those points over the most possible (level 5 every time). Shown as the
  highest level answered right and the count: "level 4 of 5 · 3 of 5 right".
- anchored_levels (skills): the level picked, 0–3, as 0–1.
- marks: the percentage, as 0–1.

A dimension nothing touched gets no score at all, rather than a made-up neutral one.

Changes between two attempts only count when they're bigger than that method's noise: with five
questions on a dimension, one more right answer is a coin toss, not progress.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Score:
    dimension: str
    score: float  # 0–1
    n_items: int
    detail: dict = field(default_factory=dict)


@dataclass
class Shown:
    """One item the student saw, and what they did with it."""

    item: dict  # the item as written (AssessmentItem.content)
    answer: dict | None  # {"option": key} | {"value": n}; None when skipped
    skipped: bool = False


def weighted_options(shown: list[Shown]) -> list[Score]:
    earned: dict[str, float] = {}
    possible: dict[str, float] = {}
    counted: dict[str, int] = {}
    for s in shown:
        if s.skipped or s.answer is None:
            continue  # says nothing either way
        options = {o["key"]: o for o in s.item["options"]}
        chosen = options.get(s.answer.get("option"))
        if chosen is None:
            continue
        best: dict[str, float] = {}
        for option in options.values():
            for dim, w in option.get("weights", {}).items():
                best[dim] = max(best.get(dim, 0.0), w)
        for dim, top in best.items():
            if top <= 0:
                continue
            possible[dim] = possible.get(dim, 0.0) + top
            earned[dim] = earned.get(dim, 0.0) + chosen.get("weights", {}).get(dim, 0.0)
            counted[dim] = counted.get(dim, 0) + 1
    return [Score(dim, round(earned[dim] / possible[dim], 4), counted[dim],
                  {"earned": round(earned[dim], 2), "possible": round(possible[dim], 2)})
            for dim in sorted(possible)]


def correct_answers(shown: list[Shown]) -> list[Score]:
    tally: dict[str, dict] = {}
    for s in shown:
        t = tally.setdefault(s.item["dimension"], {"correct": 0, "asked": 0, "skipped": 0})
        t["asked"] += 1
        if s.skipped or s.answer is None:
            t["skipped"] += 1
        elif s.answer.get("option") == s.item["answer"]:
            t["correct"] += 1
    return [Score(dim, round(t["correct"] / t["asked"], 4), t["asked"], t) for dim, t in sorted(tally.items())]


LEVELS = 5


def adaptive_correct(shown: list[Shown]) -> list[Score]:
    tally: dict[str, dict] = {}
    for s in shown:
        level = s.item.get("difficulty") or 1
        t = tally.setdefault(s.item["dimension"], {"correct": 0, "asked": 0, "skipped": 0, "points": 0,
                                                   "levels": [], "level_reached": 0, "levels_max": LEVELS})
        t["asked"] += 1
        t["levels"].append(level)
        right = not s.skipped and s.answer is not None and s.answer.get("option") == s.item["answer"]
        if right:
            t["correct"] += 1
            t["level_reached"] = max(t["level_reached"], level)
        elif s.skipped or s.answer is None:
            t["skipped"] += 1
        t["points"] += level if right else level - 1
    return [Score(dim, round(t["points"] / (t["asked"] * LEVELS), 4), t["asked"], t) for dim, t in sorted(tally.items())]


def anchored_levels(shown: list[Shown]) -> list[Score]:
    scores = []
    for s in shown:
        if s.skipped or s.answer is None:
            continue
        levels = {o["key"]: o["level"] for o in s.item["options"]}
        level = levels.get(s.answer.get("option"))
        if level is None:
            continue
        top = max(levels.values())
        scores.append(Score(s.item["dimension"], round(level / top, 4), 1, {"level": level, "of": top}))
    return scores


def marks(shown: list[Shown]) -> list[Score]:
    return [Score(s.item["dimension"], round(float(s.answer["value"]) / 100, 4), 1, {"percent": s.answer["value"]})
            for s in shown if not s.skipped and s.answer is not None and s.item["type"] == "marks"]


METHODS = {
    "weighted_options": weighted_options,
    "correct_answers": correct_answers,
    "adaptive_correct": adaptive_correct,
    "anchored_levels": anchored_levels,
    "marks": marks,
}


def score(method: str, shown: list[Shown]) -> list[Score]:
    return METHODS[method](shown)


# ---------------- comparing two attempts ----------------

def changed(method: str, before: dict, after: dict) -> int:
    """+1 better, -1 worse, 0 within the noise. `before`/`after`: {"score", "n_items", "detail"}."""
    delta = after["score"] - before["score"]
    if method == "correct_answers":
        n = min(before["n_items"], after["n_items"]) or 1
        enough = abs(delta) * n >= 2 - 1e-9  # at least two more (or fewer) right answers' worth
    elif method == "anchored_levels":
        enough = abs(after["detail"].get("level", 0) - before["detail"].get("level", 0)) >= 1
    elif method == "marks":
        enough = abs(delta) >= 0.05 - 1e-9  # five percentage points
    elif method == "adaptive_correct":
        enough = abs(delta) >= 0.15 - 1e-9  # about a level, on average, over the questions
    else:
        enough = abs(delta) >= 0.25 - 1e-9
    return 0 if not enough else (1 if delta > 0 else -1)
