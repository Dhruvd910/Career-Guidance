"""Career directions from a student's assessments (spec §10–11) — never one answer.

For every career in the library, from the latest attempt at each assessment:

- **components**:
  - `interest` is how much they enjoy what the career is made of: subjects plus the RIASEC
    traits in its careers.json profile.
  - `work_style` is how well its way of working and its demands fit what matters to them.
  - Then each measurable need in career_needs.json — `aptitude:logical`, `academic:maths`,
    `skill:programming` — is shown with the student's own result, or as "not measured yet".
- **band**, from rules anyone can check:

  | band | rule |
  |---|---|
  | strong | interest ≥ 0.65, no must-have below 0.35, no central need below 0.4 |
  | potential | interest ≥ 0.5, or ability ≥ 0.7 with interest ≥ 0.4 |
  | explore | the rest from interest ≥ 0.35; also anything with a low must-have, which becomes a question rather than a hidden penalty |
  | weak | interest < 0.35, shown last but never hidden |

- **why**, **strengths**, **development areas** (each with a next step), **questions to
  investigate** and **things to try**: each one built from a specific score, so it can be
  explained.

There is no overall score and no "best match": the student decides (spec §11). Every sentence
is written in English and Hindi.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.assessment.loader import instrument_files
from app.models.assessment import AssessmentAttempt, AssessmentInstrument, CareerAlignmentSnapshot
from app.models.career import CareerOption
from app.models.student import StudentProfile

ENGINE_VERSION = "1"
NEEDS_FILE = Path(__file__).parent / "career_needs.json"
BANDS = ("strong", "potential", "explore", "weak")
BAND_LABELS = {
    "strong": {"en": "Strong alignment", "hi": "मज़बूत मेल"},
    "potential": {"en": "Potential alignment", "hi": "संभावित मेल"},
    "explore": {"en": "Needs exploration", "hi": "और जानने की ज़रूरत"},
    "weak": {"en": "Less likely from your answers", "hi": "आपके जवाबों से कम मेल"},
}
STRONG_INTEREST, POTENTIAL_INTEREST, EXPLORE_INTEREST = 0.65, 0.5, 0.35
LOW_MUST, LOW_CENTRAL, STRENGTH, DEVELOP = 0.35, 0.4, 0.7, 0.55
INTEREST_GROUPS, STYLE_GROUPS = {"subject", "riasec"}, {"work_style", "values"}

# When the exact measure isn't there, what stands in for it (class 9–10 take "science", not physics).
FALLBACKS = {
    "skill:programming": ["check:programming", "skill:programming"],  # a measured check beats a self-rating
    "academic:physics": ["academic:physics", "academic:science"],
    "academic:chemistry": ["academic:chemistry", "academic:science"],
    "academic:biology": ["academic:biology", "academic:science"],
    "academic:economics": ["academic:economics", "academic:social_science"],
    "academic:history": ["academic:history", "academic:social_science"],
}
WHICH_ASSESSMENT = {"aptitude": "aptitude", "skill": "skills", "check": "coding_check", "academic": "academic"}

# How a liked dimension reads as a reason.
VALUES_PHRASES = {
    "blood_ok": {"en": "you're comfortable with hospitals and blood", "hi": "आप अस्पताल और खून से सहज हैं"},
    "long_study": {"en": "you're ready for a long study path", "hi": "आप लंबी पढ़ाई के लिए तैयार हैं"},
    "stability": {"en": "a secure job matters to you", "hi": "पक्की नौकरी आपके लिए मायने रखती है"},
    "money": {"en": "earning well matters to you", "hi": "अच्छी कमाई आपके लिए मायने रखती है"},
}
MUST_QUESTIONS = {
    "blood_ok": {"en": "This work means seeing blood and injuries every day. Could you spend a day at a clinic or hospital to see how it feels?",
                 "hi": "इस काम में रोज़ खून और चोटें देखनी पड़ती हैं। क्या आप किसी क्लिनिक या अस्पताल में एक दिन बिताकर देख सकते हैं कि कैसा लगता है?"},
    "long_study": {"en": "This path takes many years of study. Are you ready for that — and what would keep you going?",
                   "hi": "इस रास्ते में कई साल की पढ़ाई लगती है। क्या आप उसके लिए तैयार हैं — और आपको आगे बढ़ते रहने की ताक़त किससे मिलेगी?"},
}
NEXT_STEPS = {
    "aptitude:numerical": {"en": "Practise percentage, ratio and speed problems — ten a day for a month.",
                           "hi": "प्रतिशत, अनुपात और रफ़्तार वाले सवालों का अभ्यास कीजिए — एक महीने तक रोज़ दस।"},
    "aptitude:logical": {"en": "Solve a few logic puzzles or reasoning problems every day.",
                         "hi": "रोज़ कुछ तर्क वाली पहेलियाँ या रीज़निंग के सवाल हल कीजिए।"},
    "aptitude:verbal": {"en": "Read something you enjoy for 20 minutes a day and note down new words.",
                        "hi": "रोज़ 20 मिनट कुछ पसंद का पढ़िए और नए शब्द लिखते जाइए।"},
    "skill:programming": {"en": "Try a free beginner course such as CS50 or freeCodeCamp for four weeks.",
                          "hi": "चार हफ़्ते के लिए CS50 या freeCodeCamp जैसा कोई मुफ़्त शुरुआती कोर्स आज़माइए।"},
    "skill:speaking": {"en": "Volunteer to speak once a month — in class, at assembly or in a debate.",
                       "hi": "महीने में एक बार बोलने का मौक़ा लीजिए — क्लास, असेंबली या डिबेट में।"},
    "skill:writing": {"en": "Write one short piece a week — a story, a blog post or a letter — and ask someone to read it.",
                      "hi": "हफ़्ते में एक छोटा लेख लिखिए — कहानी, ब्लॉग या पत्र — और किसी से पढ़वाइए।"},
    "skill:design": {"en": "Keep a sketchbook, or redesign one poster or app screen a week.",
                     "hi": "एक स्केचबुक रखिए, या हर हफ़्ते एक पोस्टर या ऐप स्क्रीन को नए सिरे से डिज़ाइन कीजिए।"},
    "skill:hands_on": {"en": "Build something small — a model or a circuit kit — and finish it.",
                       "hi": "कुछ छोटा बनाइए — कोई मॉडल या सर्किट किट — और उसे पूरा कीजिए।"},
    "skill:leadership": {"en": "Take charge of one small group task or school event.",
                         "hi": "किसी एक छोटे ग्रुप टास्क या स्कूल इवेंट की ज़िम्मेदारी लीजिए।"},
    "skill:organising": {"en": "Keep a weekly timetable for a month and tick off what you did.",
                         "hi": "एक महीने तक हफ़्ते का टाइमटेबल रखिए और जो किया उस पर निशान लगाइए।"},
    "skill:english": {"en": "Speak English for ten minutes a day with a friend, or watch shows with English subtitles.",
                      "hi": "रोज़ दस मिनट किसी दोस्त के साथ अंग्रेज़ी बोलिए, या अंग्रेज़ी सबटाइटल के साथ शो देखिए।"},
}
# Enjoying something you haven't tried yet is a question worth answering by trying it.
TRY_IT = {"computer": "skill:programming", "arts": "skill:design", "realistic": "skill:hands_on",
          "language": "skill:writing", "communication": "skill:speaking", "enterprising": "skill:leadership"}


@lru_cache(maxsize=1)
def career_needs() -> dict:
    return json.loads(NEEDS_FILE.read_text())


def dimension_labels() -> dict[str, dict]:
    """{dimension: {"en", "hi", "group"}} across every current instrument."""
    labels = {}
    for spec, _ in instrument_files().values():
        for key, d in spec.dimensions.items():
            labels[key] = {"en": d.en, "hi": d.hi, "group": d.group}
    return labels


# ---------------- the student's results ----------------

def latest_attempts(db: Session, profile: StudentProfile) -> dict[str, AssessmentAttempt]:
    """The most recent completed attempt at each assessment."""
    attempts = db.execute(
        select(AssessmentAttempt).join(AssessmentInstrument)
        .where(AssessmentAttempt.student_profile_id == profile.id, AssessmentAttempt.status == "completed")
        .order_by(AssessmentAttempt.completed_at)).scalars().all()
    return {a.instrument.key: a for a in attempts}  # later ones overwrite earlier


def _results(attempts: dict[str, AssessmentAttempt]) -> dict[str, dict]:
    """{dimension: {score, n_items, detail, method, instrument, attempt_id, says}} from the latest attempts."""
    from app.assessment.service import _phrase

    out = {}
    for key, attempt in attempts.items():
        method = attempt.instrument.scoring_method
        for s in attempt.scores:
            out[s.dimension_key] = {
                "score": s.score, "n_items": s.n_items, "detail": s.detail, "method": method, "instrument": key,
                "attempt_id": attempt.id,
                "says": {"en": _phrase(s.dimension_key, s, method, "en"), "hi": _phrase(s.dimension_key, s, method, "hi")},
            }
    return out


def _measure(results: dict[str, dict], need: str) -> tuple[str, dict] | None:
    for candidate in FALLBACKS.get(need, [need]):
        if candidate in results:
            return candidate, results[candidate]
    return None


def _weighted(profile: dict[str, float], levels: dict[str, dict], groups: set[str], labels: dict) -> float | None:
    total = got = 0.0
    for dim, weight in profile.items():
        if labels.get(dim, {}).get("group") in groups and dim in levels:
            total += weight
            got += weight * levels[dim]["score"]
    return round(got / total, 3) if total else None


def _t(en: str, hi: str) -> dict:
    return {"en": en, "hi": hi}


def _join(parts: list[str], lang: str) -> str:
    if len(parts) <= 1:
        return "".join(parts)
    return ", ".join(parts[:-1]) + (" and " if lang == "en" else " और ") + parts[-1]


# ---------------- one career ----------------

def align(career: CareerOption, results: dict[str, dict], labels: dict) -> dict:
    needs_entry = career_needs()["careers"].get(career.key, {"needs": {}, "ask_yourself": []})
    profile, must = career.profile or {}, career.must or []
    interest = _weighted(profile, results, INTEREST_GROUPS, labels)
    style = _weighted(profile, results, STYLE_GROUPS, labels)

    components = {"interest": interest, "work_style": style}
    evidence, strengths, development, not_measured, questions = [], [], [], [], []
    measures = []  # each need, labelled, with the student's result — for showing "what it draws on"
    ability_total = ability_got = 0.0
    central_gap = False
    for need, weight in sorted(needs_entry["needs"].items(), key=lambda kv: -kv[1]):
        label = labels.get(need, {"en": need, "hi": need})
        found = _measure(results, need)
        if found is None:
            components[need] = None
            measures.append({"dimension": need, "label": {"en": label["en"], "hi": label["hi"]}, "weight": weight,
                             "score": None, "says": None})
            if weight >= 2:
                which = WHICH_ASSESSMENT.get(need.split(":")[0])
                not_measured.append({"dimension": need, "assessment": which,
                                     "text": _t(f"{label['en'][0].upper() + label['en'][1:]} isn't measured yet",
                                                f"{label['hi']} अभी मापा नहीं गया है")})
            continue
        measured_as, r = found
        components[need] = r["score"]
        shown_label = labels.get(measured_as, label)
        measures.append({"dimension": need, "label": {"en": shown_label["en"], "hi": shown_label["hi"]},
                         "weight": weight, "score": r["score"], "says": r["says"]})
        evidence.append({"dimension": need, "measured_as": measured_as, "instrument": r["instrument"],
                         "attempt_id": r["attempt_id"]})
        ability_total += weight
        ability_got += weight * r["score"]
        shown = labels.get(measured_as, label)
        if r["score"] >= STRENGTH:
            strengths.append(_t(f"{shown['en'][0].upper() + shown['en'][1:]}: {r['says']['en']}",
                                f"{shown['hi']}: {r['says']['hi']}"))
        elif r["score"] < DEVELOP and weight >= 2:
            step = NEXT_STEPS.get(measured_as) or NEXT_STEPS.get(need)
            if step is None and need.startswith("academic:"):
                step = _t(f"Find the {label['en'].replace(' marks', '')} chapters that cost you the most marks and practise those NCERT exercises first.",
                          f"{label['hi'].replace(' के अंक', '')} के वे अध्याय पहचानिए जिनमें सबसे ज़्यादा अंक कटे, और पहले उन्हीं के NCERT अभ्यास कीजिए।")
            development.append({"dimension": need,
                                 "text": _t(f"{shown['en'][0].upper() + shown['en'][1:]}: {r['says']['en']}",
                                            f"{shown['hi']}: {r['says']['hi']}"),
                                 "next_step": step})
            if weight == 3 and r["score"] < LOW_CENTRAL:
                central_gap = True
    ability = round(ability_got / ability_total, 3) if ability_total else None

    # Why it may fit: the liked parts of what the career is made of, strongest first.
    liked = sorted(((w * results[d]["score"], d) for d, w in profile.items()
                    if d in results and results[d]["score"] >= 0.66 and w >= 1), reverse=True)[:3]
    why_en = [VALUES_PHRASES[d]["en"] if d in VALUES_PHRASES else f"you enjoy {labels[d]['en']}" for _, d in liked if d in labels]
    why_hi = [VALUES_PHRASES[d]["hi"] if d in VALUES_PHRASES else f"आपको {labels[d]['hi']} पसंद है" for _, d in liked if d in labels]
    why = [_t(w_en[0].upper() + w_en[1:], w_hi) for w_en, w_hi in zip(why_en, why_hi)]

    low_musts = [d for d in must if d in results and results[d]["score"] < LOW_MUST]
    for d in low_musts:
        questions.append(MUST_QUESTIONS.get(d) or _t(
            f"This career leans on {labels[d]['en']}, which you rated low. Is that how it's taught, or something you really don't enjoy?",
            f"इस करियर में {labels[d]['hi']} की ज़रूरत है, जिसे आपने कम आँका। क्या यह पढ़ाने के तरीके की वजह से है, या आपको सच में पसंद नहीं?"))
    for liked_dim, skill in TRY_IT.items():
        if profile.get(liked_dim, 0) >= 2 and results.get(liked_dim, {}).get("score", 0) >= 0.66 \
                and skill in results and results[skill]["score"] <= 0.34:
            questions.append(_t(
                f"You enjoy {labels[liked_dim]['en']}, but haven't done much {labels[skill]['en']} yet — try it for a few weeks and see if you still enjoy it.",
                f"आपको {labels[liked_dim]['hi']} पसंद है, पर अभी {labels[skill]['hi']} ज़्यादा नहीं किया — कुछ हफ़्ते आज़माकर देखिए कि क्या तब भी पसंद आता है।"))
    for nm in not_measured:
        if nm["assessment"]:
            title = instrument_files()[nm["assessment"]][0].title
            questions.append(_t(f"{nm['text']['en']} — the '{title.en}' check would show it.",
                                f"{nm['text']['hi']} — '{title.hi}' से पता चलेगा।"))
    questions.extend(needs_entry["ask_yourself"])

    if interest is None or interest < EXPLORE_INTEREST:
        band = "weak" if interest is not None else "explore"
    elif low_musts:
        band = "explore"
    elif interest >= STRONG_INTEREST and not central_gap:
        band = "strong"
    elif interest >= POTENTIAL_INTEREST or (ability is not None and ability >= 0.7 and interest >= 0.4):
        band = "potential"
    else:
        band = "explore"

    return {
        "career_key": career.key, "name": career.name, "domain": career.category, "band": band,
        "band_label": BAND_LABELS[band], "components": components, "measures": measures, "why": why,
        "strengths": strengths,
        "development_areas": development, "questions": _unique(questions), "not_measured": not_measured,
        "things_to_try": list(career.explore_next or []), "education_path": career.education_path,
        "exams": list(career.typical_entrance_exam_codes or []), "evidence": evidence,
        "_order": (interest or 0) * 0.6 + (ability if ability is not None else (interest or 0)) * 0.4,
    }


def _unique(items: list[dict]) -> list[dict]:
    seen, out = set(), []
    for item in items:
        if item["en"] not in seen:
            seen.add(item["en"])
            out.append(item)
    return out


# ---------------- all careers ----------------

def compute(db: Session, profile: StudentProfile) -> dict:
    attempts = latest_attempts(db, profile)
    inputs = {key: a.id for key, a in attempts.items()}
    if "interests" not in attempts:
        return {"ready": False, "missing": ["interests"], "inputs": inputs, "domains": [], "summary": {}}
    results = _results(attempts)
    labels = dimension_labels()
    careers = [align(c, results, labels)
               for c in db.execute(select(CareerOption).where(CareerOption.key.is_not(None))).scalars()]
    domains_meta = career_needs()["domains"]
    by_domain: dict[str, list[dict]] = {}
    for c in sorted(careers, key=lambda c: (BANDS.index(c["band"]), -c["_order"], c["name"])):
        by_domain.setdefault(c["domain"], []).append(c)
    domains = []
    for name, members in by_domain.items():
        for c in members:
            c.pop("_order")
        domains.append({"domain": name, "label": domains_meta.get(name, {"en": name, "hi": name}),
                        "best_band": members[0]["band"], "careers": members})
    domains.sort(key=lambda d: (BANDS.index(d["best_band"]), d["label"]["en"]))
    summary = {band: [c["career_key"] for d in domains for c in d["careers"] if c["band"] == band] for band in BANDS}
    return {"ready": True, "missing": [k for k in ("aptitude", "skills", "academic") if k not in attempts],
            "inputs": inputs, "engine_version": ENGINE_VERSION, "domains": domains, "summary": summary}


def snapshot(db: Session, profile: StudentProfile) -> CareerAlignmentSnapshot | None:
    """Works out the directions now and keeps them — called when an attempt completes."""
    directions = compute(db, profile)
    if not directions["ready"]:
        return None
    snap = CareerAlignmentSnapshot(student_profile_id=profile.id, engine_version=ENGINE_VERSION,
                                   inputs=directions["inputs"], results=directions)
    db.add(snap)
    db.flush()
    return snap


def directions(db: Session, profile: StudentProfile) -> dict:
    """The current directions: the latest snapshot if it still matches the latest attempts,
    otherwise freshly worked out (and kept)."""
    current = {key: a.id for key, a in latest_attempts(db, profile).items()}
    last = db.execute(select(CareerAlignmentSnapshot)
                      .where(CareerAlignmentSnapshot.student_profile_id == profile.id)
                      .order_by(CareerAlignmentSnapshot.id.desc()).limit(1)).scalar_one_or_none()
    if last is not None and last.inputs == current and last.engine_version == ENGINE_VERSION:
        out = dict(last.results)
    else:
        snap = snapshot(db, profile)
        db.commit()
        out = dict(snap.results) if snap is not None else compute(db, profile)
        last = snap
    out["as_of"] = last.created_at.isoformat() if last is not None and last.created_at else None
    return out


def explain(db: Session, profile: StudentProfile, career_key: str) -> dict | None:
    for domain in directions(db, profile).get("domains", []):
        for career in domain["careers"]:
            if career["career_key"] == career_key:
                return career
    return None
