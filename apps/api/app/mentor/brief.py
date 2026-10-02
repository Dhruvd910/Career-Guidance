"""The brief: spec §37's eight questions, answered from the modules' own data (docs/design/16-phase7-plan.md,
P7-1). Each answer says where it comes from. What comes from memory (threads, summaries, goals,
interests, constraints) is there only with the long-term memory permission (P7-8).

    who · discussed · confused · decided · working_toward · progress · last_stopped · next
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.memory import consent
from app.models.memory import CounsellingThread, SessionSummary, StudentConstraint, StudentGoal, StudentInterest
from app.models.saved_item import SavedItem
from app.models.student import StudentProfile
from app.mentor import agenda as agenda_module

NO_MEMORY = "MAYA isn't keeping memories of your conversations (the permission is off)."


def _day(moment) -> str | None:
    return moment.strftime("%-d %b %Y") if moment else None


def brief(db: Session, profile: StudentProfile, now: datetime | None = None,
          session_started: datetime | None = None) -> dict:
    from app.memory.opening import counselling_state
    from app.roadmap import progress, service

    now = now or datetime.now(timezone.utc)
    remember = consent.allowed(db, profile, consent.LONG_TERM_MEMORY)
    pid = profile.id

    def rows(model, *where, order=None, limit=None):
        query = select(model).where(model.student_profile_id == pid, *where)
        if order is not None:
            query = query.order_by(order)
        if limit:
            query = query.limit(limit)
        return list(db.execute(query).scalars())

    who = {"name": profile.name, "class_level": profile.class_level,
           "education_stage": profile.education_stage, "stream": profile.stream, "board": profile.school_board,
           "town": ", ".join(x for x in (profile.city, profile.state) if x) or None,
           "exam": profile.target_exam_code, "source": "your details"}
    if remember:
        who["interests"] = [i.label for i in rows(StudentInterest, StudentInterest.status == "active",
                                                   order=StudentInterest.strength.desc(), limit=5)]
        who["constraints"] = [c.detail for c in rows(StudentConstraint, StudentConstraint.status == "active",
                                                     StudentConstraint.sensitivity != "sensitive")]

    summaries = rows(SessionSummary, order=SessionSummary.created_at.desc(), limit=3) if remember else []
    threads = rows(CounsellingThread, order=CounsellingThread.last_touched_at.desc()) if remember else []
    discussed = [{"when": _day(s.created_at), "summary": s.summary, "source": "session summary"} for s in summaries]
    confused = [{"topic": th.title, "question": q, "source": f"your session on {_day(th.last_touched_at)}"}
                for th in threads if th.status != "resolved" for q in th.open_questions or []]
    if summaries:
        confused += [{"topic": None, "question": q, "source": f"your session on {_day(summaries[0].created_at)}"}
                     for q in summaries[0].unresolved_questions or [] if isinstance(q, str)]

    decided = [{"what": th.title, "position": th.current_position, "when": _day(th.resolved_at or th.last_touched_at),
                "source": "counselling"} for th in threads if th.decision_status == "decided"]
    roadmap_row = service.get_roadmap(db, profile)
    view = service.view(db, profile) if roadmap_row is not None else None
    if view and view.get("focus"):
        decided.append({"what": f"Roadmap focus: {view['focus']['name']['en']}", "position": None, "when": None,
                        "source": "your roadmap"})

    working = {"goals": [g.title for g in rows(StudentGoal, StudentGoal.status == "active")] if remember else [],
               "focus": view["focus"]["name"] if view and view.get("focus") else None,
               "next_step": view["next_step"]["title"] if view and view.get("next_step") else None,
               "shortlist": len(rows(SavedItem, SavedItem.item_type == "college")),
               "source": "your goals and roadmap"}

    p = progress.summary(db, profile)
    moved = [{"skill": s["name"]["en"], "first": round(s["initial"] * 100), "now": round(s["current"] * 100),
              "change": s["change"]} for s in p["skills"] if len(s["points"]) > 1]
    progressed = {"skills": moved, "roadmap_percent": p["roadmap"]["completion"] if p.get("roadmap") else None,
                  "milestones_done": p["milestones"]["done"], "assessments": p["assessments"]["attempts"],
                  "source": "assessments, practice papers and your roadmap"}

    last = counselling_state(db, profile) if remember else None
    nxt = [i.as_dict() for i in agenda_module.agenda(db, profile, now, session_started)[:3]]
    return {"who": who, "discussed": discussed, "confused": confused, "decided": decided,
            "working_toward": working, "progress": progressed, "last_stopped": last, "next": nxt,
            "memory": remember, "note": None if remember else NO_MEMORY}
