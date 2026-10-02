"""The student's college shortlist (docs/design/16-phase7-plan.md, P7-7): saved colleges with the
facts that matter most when choosing, each with its source and freshness. Adding or removing one
updates the roadmap's college step evidence; on the timeline only with the memory permission."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.facts import discover, store
from app.models.college import College
from app.models.saved_item import SavedItem
from app.models.student import StudentProfile

KEY_FACTS = ("fee.tuition.annual", "fee.hostel.annual", "facility.hostel", "facility.medical", "near.railway_station",
             "ranking.nirf.engineering", "ranking.nirf.medical")


class ShortlistError(ValueError):
    pass


def _saved(db: Session, profile: StudentProfile) -> list[SavedItem]:
    return list(db.execute(select(SavedItem).where(SavedItem.student_profile_id == profile.id,
                                                   SavedItem.item_type == "college").order_by(SavedItem.id)).scalars())


def items(db: Session, profile: StudentProfile) -> list[dict]:
    saved = _saved(db, profile)
    known = store.current_many(db, "college", [s.item_id for s in saved])
    out = []
    for s in saved:
        college = db.get(College, s.item_id)
        if college is None:
            continue
        views = known.get(college.id, {})
        out.append({"id": college.id, "name": college.canonical_name, "city": college.city, "state": college.state,
                    "type": college.college_type,
                    "facts": {a: discover.brief(a, views.get(a)) for a in KEY_FACTS if views.get(a)}})
    return out


def _after(db: Session, profile: StudentProfile, event: str, college: College) -> None:
    from app.roadmap import service

    if service.get_roadmap(db, profile) is not None:
        service.rebuild(db, profile, {"kind": "shortlist", "detail": college.canonical_name})
    service._event(db, profile, event, {"college_id": college.id, "college": college.canonical_name})


def add(db: Session, profile: StudentProfile, college_id: int) -> dict:
    college = db.get(College, college_id)
    if college is None:
        raise ShortlistError("No such college.")
    if not any(s.item_id == college_id for s in _saved(db, profile)):
        db.add(SavedItem(student_profile_id=profile.id, item_type="college", item_id=college_id))
        db.flush()
        _after(db, profile, "COLLEGE_SHORTLISTED", college)
    db.commit()
    return {"added": college.canonical_name, "shortlist": len(_saved(db, profile))}


def remove(db: Session, profile: StudentProfile, college_id: int) -> dict:
    college = db.get(College, college_id)
    gone = [s for s in _saved(db, profile) if s.item_id == college_id]
    for s in gone:
        db.delete(s)
    db.flush()
    if gone and college is not None:
        _after(db, profile, "COLLEGE_UNSHORTLISTED", college)
    db.commit()
    return {"removed": college.canonical_name if college else None, "shortlist": len(_saved(db, profile))}
