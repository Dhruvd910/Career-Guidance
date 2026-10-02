"""What's worth raising with a student now (docs/design/16-phase7-plan.md, P7-2, P7-3).

Every module contributes its own items, each with a reason, where it comes from, and the screen
it opens; nothing here is decided by a model. Ranked by priority:

| Kind | When | Priority |
|---|---|---|
| dates | an application window or exam for their exam within 7 days | 90 |
| dates | the same within 30 days, or the next cycle's dates announced | 75 / 70 |
| topic | a counselling topic still undecided | 65 |
| roadmap | the next step is overdue | 60 |
| decision | a decision about a career or stream that isn't in the roadmap yet (a proposal) | 58 |
| college | a shortlisted college's facts changed since the last session | 55 |
| reassessment | moved up a class since an assessment / 6 months since it | 55 / 50 |
| roadmap | the next step, not yet started | 35 |
| goal | an active goal not talked about for 45 days | 25 |

Never nag: an item marked done, or "not now" (snoozed for 14 days), stays off; one already raised
in this session isn't raised again.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.facts import describe, store
from app.memory import consent
from app.models.chat import Conversation
from app.models.college import College
from app.models.exam import Exam
from app.models.facts import Fact
from app.models.memory import CounsellingThread, SessionSummary, StudentGoal
from app.models.mentor import AgendaMark
from app.models.saved_item import SavedItem
from app.models.student import StudentProfile

SNOOZE = timedelta(days=14)
REASSESS_AFTER = timedelta(days=182)
QUIET_GOAL = timedelta(days=45)
STREAMS = {"pcm": "PCM", "pcb": "PCB", "pcmb": "PCMB", "commerce": "Commerce", "humanities": "Humanities", "arts": "Humanities"}


def t(en: str, hi: str) -> dict:
    return {"en": en, "hi": hi}


@dataclass
class Item:
    key: str
    kind: str
    title: dict
    why: dict
    source: str
    priority: int
    screen: dict = field(default_factory=dict)  # {"page": "roadmap", "args": {...}} for the Pi
    raised: bool = False  # already raised in this session

    def as_dict(self) -> dict:
        return asdict(self)


def _aware(moment: datetime | None) -> datetime | None:
    if moment is not None and moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment


def _day(moment: datetime | date | None) -> str:
    if moment is None:
        return ""
    return moment.strftime("%-d %b %Y")


def last_session_end(db: Session, profile: StudentProfile) -> datetime | None:
    ended = db.execute(select(Conversation.ended_at).where(Conversation.student_profile_id == profile.id,
                                                           Conversation.ended_at.isnot(None))
                       .order_by(Conversation.ended_at.desc()).limit(1)).scalar()
    return _aware(ended)


# ---------------- collectors ----------------

def topics(db: Session, profile: StudentProfile, now: datetime) -> list[Item]:
    if not consent.allowed(db, profile, consent.LONG_TERM_MEMORY):
        return []
    out = []
    for th in db.execute(select(CounsellingThread).where(
            CounsellingThread.student_profile_id == profile.id,
            CounsellingThread.status.in_(("open", "reopened", "parked")),
            CounsellingThread.decision_status.in_(("undecided", "leaning", "reopened")))).scalars():
        question = (th.open_questions or [None])[0]
        why = t(f"Not decided yet (since {_day(th.last_touched_at)})" + (f" — still open: {question}" if question else ""),
                f"अभी तय नहीं ({_day(th.last_touched_at)} से)" + (f" — अभी खुला सवाल: {question}" if question else ""))
        out.append(Item(f"thread:{th.id}", "topic", t(th.title, th.title), why,
                        f"your session on {_day(th.last_touched_at)}", 65, {"page": "maya", "args": {}}))
    return out


def roadmap(db: Session, profile: StudentProfile, now: datetime) -> list[Item]:
    from app.roadmap import service

    if service.get_roadmap(db, profile) is None:
        return []
    step = service.view(db, profile).get("next_step")
    if not step:
        return []
    title = step["title"]
    if step.get("overdue"):
        return [Item(f"roadmap:overdue:{step['node_key']}", "roadmap", title,
                     t("This step's months have passed on your roadmap", "रोडमैप पर इस कदम का समय निकल गया"),
                     "your roadmap", 60, {"page": "roadmap_node", "args": {"node_key": step["node_key"]}})]
    if step.get("status") == "not_started":
        return [Item(f"roadmap:next:{step['node_key']}", "roadmap", title,
                     t("Your roadmap's next step", "आपके रोडमैप का अगला कदम"), "your roadmap", 35,
                     {"page": "roadmap_node", "args": {"node_key": step["node_key"]}})]
    return []


def reassessments(db: Session, profile: StudentProfile, now: datetime) -> list[Item]:
    from app.assessment.alignment import latest_attempts
    from app.models.roadmap import Roadmap, RoadmapVersion

    out = []
    versions = []
    roadmap_row = db.execute(select(Roadmap).where(Roadmap.student_profile_id == profile.id)).scalar_one_or_none()
    if roadmap_row is not None:
        versions = list(db.execute(select(RoadmapVersion).where(RoadmapVersion.roadmap_id == roadmap_row.id)
                                   .order_by(RoadmapVersion.created_at)).scalars())
    for key, attempt in latest_attempts(db, profile).items():
        done = _aware(attempt.completed_at)
        if done is None:
            continue
        before = [v for v in versions if _aware(v.created_at) <= done]
        then = (before[-1].inputs_snapshot or {}).get("class_level") if before else None
        title = t(f"Retake “{attempt.instrument.title['en']}”", f"“{attempt.instrument.title.get('hi', attempt.instrument.title['en'])}” फिर से दें")
        if then is not None and profile.class_level and then != profile.class_level:
            out.append(Item(f"reassess:{key}", "reassessment", title,
                            t(f"You took it in class {then}; you're in class {profile.class_level} now",
                              f"आपने यह कक्षा {then} में दिया था; अब आप कक्षा {profile.class_level} में हैं"),
                            f"your assessment on {_day(done)}", 55, {"page": "assessment_run", "args": {"key": key}}))
        elif now - done >= REASSESS_AFTER:
            months = (now - done).days // 30
            out.append(Item(f"reassess:{key}", "reassessment", title,
                            t(f"It's {months} months since you took it — see how you've grown",
                              f"इसे दिए {months} महीने हो गए — देखिए आप कितना आगे बढ़े"),
                            f"your assessment on {_day(done)}", 50, {"page": "assessment_run", "args": {"key": key}}))
    return out


def dates(db: Session, profile: StudentProfile, now: datetime) -> list[Item]:
    code = profile.target_exam_code
    if not code:
        return []
    exam = db.execute(select(Exam).where(Exam.code == code)).scalar_one_or_none()
    if exam is None:
        return []
    today = now.date()
    cycle = today.year + 1 if today.month >= 7 else today.year
    next_year = f"{cycle}-{str(cycle + 1)[2:]}"
    out, announced = [], False
    for attribute, view in store.current(db, "exam", exam.id, prefix="admission.").items():
        value = view["value"] or {}
        if view["academic_year"] == next_year and view["value"] is not None:
            announced = True
        try:
            start = date.fromisoformat(value.get("from", ""))
            end = date.fromisoformat(value["to"]) if value.get("to") else start
        except (TypeError, ValueError):
            continue
        if end < today or (start - today).days > 30:
            continue
        soon = (start - today).days <= 7 or start <= today <= end
        label = describe.value_text(attribute, value)
        out.append(Item(f"dates:{code}:{attribute}:{value.get('from')}", "dates", t(f"{exam.name}: {label}", f"{exam.name}: {label}"),
                        t("Open now" if start <= today else f"In {(start - today).days} days",
                          "अभी खुला है" if start <= today else f"{(start - today).days} दिन में"),
                        view["source"]["document"], 90 if soon else 75, {"page": "exam", "args": {"code": code}}))
    if announced:
        out.append(Item(f"dates:{code}:announced:{next_year}", "dates",
                        t(f"{exam.name} {cycle}: the dates are out", f"{exam.name} {cycle}: तारीख़ें आ गईं"),
                        t("The official bulletin for the next cycle has been published", "अगले साल का आधिकारिक बुलेटिन आ गया है"),
                        "the official bulletin", 70, {"page": "exam", "args": {"code": code}}))
    return out


def colleges(db: Session, profile: StudentProfile, now: datetime) -> list[Item]:
    since = last_session_end(db, profile)
    if since is None:
        return []
    out = []
    saved = [s.item_id for s in db.execute(select(SavedItem).where(SavedItem.student_profile_id == profile.id,
                                                                  SavedItem.item_type == "college")).scalars()]
    for college_id in saved:
        college = db.get(College, college_id)
        if college is None:
            continue
        changed = db.execute(select(Fact.attribute).where(
            Fact.entity_type == "college", Fact.entity_id == college_id, Fact.superseded_by.is_(None),
            Fact.status.in_(("verified", "unverified")), Fact.created_at > since,
            or_(*(Fact.attribute.startswith(p) for p in ("fee.", "facility.", "admission."))))).scalars().all()
        if changed:
            what = ", ".join(sorted({describe.name(a) for a in changed})[:3])
            out.append(Item(f"college:{college_id}:{_day(now)}", "college", t(college.canonical_name, college.canonical_name),
                            t(f"New since your last session: {what}", f"पिछले सत्र के बाद नया: {what}"),
                            "its official sources", 55, {"page": "college_detail", "args": {"college_id": college_id}}))
    return out


def decisions(db: Session, profile: StudentProfile, now: datetime) -> list[Item]:
    """A decision about a career or stream not yet in the roadmap or profile — a proposal (P7-5)."""
    if not consent.allowed(db, profile, consent.LONG_TERM_MEMORY):
        return []
    from app.knowledge.graph_store import graph
    from app.knowledge.linking import _aliases, _lexical
    from app.roadmap import service

    # What was decided — never the topic's title, which names every option ("PCM vs PCB").
    said = [th.current_position or "" for th in db.execute(select(CounsellingThread).where(
        CounsellingThread.student_profile_id == profile.id, CounsellingThread.decision_status == "decided")).scalars()]
    for summary in db.execute(select(SessionSummary).where(SessionSummary.student_profile_id == profile.id)
                              .order_by(SessionSummary.created_at.desc()).limit(5)).scalars():
        said += [d if isinstance(d, str) else str(d.get("decision") or d) for d in summary.decisions or []]
    roadmap_row = service.get_roadmap(db, profile)
    focus = roadmap_row.focus_career if roadmap_row else None
    out, store_ = [], graph(db)
    careers = store_.of_type("career")
    aliases = _aliases(store_, [c["key"] for c in careers])
    candidates = [(c["key"], [c["name"]["en"], c["name"]["hi"], *aliases[c["key"]]]) for c in careers]
    for text in said:
        low = text.lower()
        streams = {stream for word, stream in STREAMS.items() if re.search(rf"\b{word}\b", low)}
        if len(streams) == 1:  # one stream named: that's the decision; two would be a guess
            stream = streams.pop()
            if (profile.stream or "").lower() != stream.lower():
                out.append(Item(f"decision:stream:{stream}", "decision", t(f"Set your stream to {stream}?", f"अपनी स्ट्रीम {stream} रखें?"),
                                t(f"You decided on {stream}; your details still say {profile.stream or 'nothing'}",
                                  f"आपने {stream} तय किया; आपकी जानकारी में अभी {profile.stream or 'कुछ नहीं'} है"),
                                "your decision", 58, {"page": "profile", "args": {}}))
        found = _lexical(text, candidates)
        if len(found) == 1 and found[0].removeprefix("career:") != focus:
            career = found[0]
            node = store_.node(career) or {}
            name = node.get("name", {"en": career, "hi": career})
            out.append(Item(f"decision:focus:{career}", "decision",
                            t(f"Make {name['en']} your roadmap's focus?", f"{name['hi']} को अपने रोडमैप का लक्ष्य बनाएँ?"),
                            t("You decided on it; your roadmap is built around something else",
                              "आपने यह तय किया; आपका रोडमैप किसी और पर बना है"),
                            "your decision", 58, {"page": "career_detail", "args": {"key": career.removeprefix('career:')}}))
    return list({i.key: i for i in out}.values())


def goals(db: Session, profile: StudentProfile, now: datetime) -> list[Item]:
    if not consent.allowed(db, profile, consent.LONG_TERM_MEMORY):
        return []
    out = []
    for g in db.execute(select(StudentGoal).where(StudentGoal.student_profile_id == profile.id,
                                                  StudentGoal.status == "active")).scalars():
        touched = _aware(g.updated_at or g.created_at)
        if touched and now - touched >= QUIET_GOAL:
            out.append(Item(f"goal:{g.id}", "goal", t(g.title, g.title),
                            t(f"Not talked about since {_day(touched)} — still working toward it?",
                              f"{_day(touched)} के बाद बात नहीं हुई — अब भी इस पर काम कर रहे हैं?"),
                            "your goals", 25, {"page": "memory", "args": {}}))
    return out


COLLECTORS = (topics, roadmap, reassessments, dates, colleges, decisions, goals)


# ---------------- the agenda ----------------

def _marks(db: Session, profile: StudentProfile) -> dict[str, AgendaMark]:
    return {m.key: m for m in db.execute(select(AgendaMark).where(AgendaMark.student_profile_id == profile.id)).scalars()}


def agenda(db: Session, profile: StudentProfile, now: datetime | None = None,
           session_started: datetime | None = None) -> list[Item]:
    """Everything worth raising, best first — without what's done, snoozed or (for this session)
    already raised being raised again."""
    now = now or datetime.now(timezone.utc)
    marks = _marks(db, profile)
    items: list[Item] = []
    for collect in COLLECTORS:
        for item in collect(db, profile, now):
            mark = marks.get(item.key)
            if mark is not None:
                if mark.status == "done":
                    continue
                snoozed = _aware(mark.snoozed_until)
                if snoozed is not None and snoozed > now:
                    continue
                raised = _aware(mark.last_raised_at)
                item.raised = bool(session_started and raised and raised >= _aware(session_started))
            items.append(item)
    return sorted(items, key=lambda i: (-i.priority, i.key))


def to_raise(db: Session, profile: StudentProfile, now: datetime | None = None,
             session_started: datetime | None = None, limit: int = 2) -> list[Item]:
    """At most two, not yet raised this session (P7-3)."""
    return [i for i in agenda(db, profile, now, session_started) if not i.raised][:limit]


def mark(db: Session, profile: StudentProfile, key: str, what: str, now: datetime | None = None) -> AgendaMark:
    """raised · done · not_now (snoozed for 14 days)."""
    now = now or datetime.now(timezone.utc)
    row = _marks(db, profile).get(key)
    if row is None:
        row = AgendaMark(student_profile_id=profile.id, key=key, times_raised=0, status="open")
        db.add(row)
    if what == "raised":
        row.first_raised_at = row.first_raised_at or now
        row.last_raised_at, row.times_raised = now, (row.times_raised or 0) + 1
    elif what == "done":
        row.status = "done"
    elif what == "not_now":
        row.status, row.snoozed_until = "dismissed", now + SNOOZE
    else:
        raise ValueError("what must be raised, done or not_now")
    db.flush()
    return row
