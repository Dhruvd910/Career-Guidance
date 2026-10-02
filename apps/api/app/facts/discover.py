"""College discovery (spec §17; docs/design/15-phase6-plan.md, Step 8): career → degree → colleges
offering it → filters → plain attributes to compare. No "best college" score: the student
chooses what to sort by, and every attribute shows where it came from and how fresh it is.

A filter on something that isn't known for a college (no location yet, no fee on record) leaves
that college out *and says how many were left out for that reason*, rather than guessing.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import geo
from app.facts import describe, store
from app.ingest.read import PER_YEAR
from app.models.college import College, CollegeCourse
from app.models.exam import Exam

GROUPS = {
    "Academic": ("academic.", "ranking.", "placement."),
    "Financial": ("fee.",),
    "Campus": ("facility.",),
    "Location": ("location.", "near."),
    "Admissions": ("admission.",),
}
SORTS = ("name", "distance", "fee", "nirf")


def grouped(views: dict[str, dict]) -> dict[str, dict[str, dict]]:
    out = {group: {} for group in GROUPS}
    for attribute, view in sorted(views.items()):
        group = next((g for g, prefixes in GROUPS.items() if attribute.startswith(prefixes)), "Academic")
        out[group][attribute] = view
    return out


def brief(attribute: str, view: dict | None) -> dict | None:
    """One attribute for a list or a comparison cell: its value in words, freshness and source."""
    if view is None:
        return None
    return {"what": describe.name(attribute), "value": describe.value_text(attribute, view["value"]),
            "status": view["status"], "label": view["label"], "academic_year": view["academic_year"],
            "source": view["source"]["name"], "official": view["source"]["official"], "url": view["source"]["url"],
            "conflict": [describe.value_text(attribute, c["value"]) + f" ({c['source']['name']})" for c in view["conflict"]]
            if view["conflict"] else None}


def yearly_fee(view: dict | None) -> int | None:
    value = (view or {}).get("value") or {}
    if "amount" not in value:
        return None
    return int(value["amount"] * PER_YEAR.get(value.get("per", "year"), 1))


def _nirf(views: dict) -> int | None:
    ranks = [v["value"]["rank"] for a, v in views.items() if a.startswith("ranking.nirf") and (v["value"] or {}).get("rank")]
    return min(ranks) if ranks else None


def has_facility(view: dict | None) -> bool | None:
    """Whether a facility exists, from its fact: None when nothing is known."""
    if view is None:
        return None
    if view["status"] == "not_available":
        return False if view["source"]["official"] else None
    value = view["value"]
    if isinstance(value, bool):
        return value
    text = str((value or {}).get("text", "")).lower()
    return not any(w in text for w in ("no hostel", "not available", "no medical", "none"))


def discover(db: Session, *, career: str | None = None, degree: str | None = None, state: str | None = None,
             exam: str | None = None, home: str | None = None, home_state: str | None = None,
             radius_km: float | None = None, budget_max: int | None = None, hostel: bool = False,
             medical: bool = False, sort: str = "name", limit: int = 50) -> dict:
    left_out: dict[str, int] = {}
    if career or degree:
        from app.knowledge.graph_store import graph

        key = f"career:{career}" if career and not career.startswith("career:") else (career or
              (degree if degree.startswith("degree:") else f"degree:{degree}"))
        offered = graph(db).colleges_for(key, state=state, limit=10_000)
        ids = [c["college_id"] for c in offered["colleges"] if c.get("college_id")]
        colleges = list(db.execute(select(College).where(College.id.in_(ids))).scalars())
    else:
        query = select(College)
        if state:
            query = query.where(College.state == state)
        colleges = list(db.execute(query).scalars())
    if exam:
        with_exam = {cid for (cid,) in db.execute(select(CollegeCourse.college_id).join(Exam, Exam.id == CollegeCourse.exam_id)
                                                  .where(Exam.code == exam.upper()).distinct())}
        colleges = [c for c in colleges if c.id in with_exam]
    origin = geo.find(home, home_state) if home else None
    known = store.current_many(db, "college", [c.id for c in colleges])
    rows = []
    for c in colleges:
        views = known.get(c.id, {})
        distance = round(geo.km(origin.lat, origin.lng, c.latitude, c.longitude), 1) \
            if origin and c.latitude is not None else None
        fee = yearly_fee(views.get("fee.tuition.annual"))
        has_hostel, has_medical = has_facility(views.get("facility.hostel")), has_facility(views.get("facility.medical"))
        if radius_km is not None and origin:
            if distance is None:
                left_out["no known location"] = left_out.get("no known location", 0) + 1
                continue
            if distance > radius_km:
                continue
        if budget_max is not None:
            if fee is None:
                left_out["no tuition fee on record"] = left_out.get("no tuition fee on record", 0) + 1
                continue
            if fee > budget_max:
                continue
        if hostel and not has_hostel:
            if has_hostel is None:
                left_out["hostel not known"] = left_out.get("hostel not known", 0) + 1
            continue
        if medical and not has_medical:
            if has_medical is None:
                left_out["medical facility not known"] = left_out.get("medical facility not known", 0) + 1
            continue
        rows.append({
            "id": c.id, "name": c.canonical_name, "city": c.city, "state": c.state, "type": c.college_type,
            "distance_km": distance, "tuition_per_year": fee, "nirf_rank": _nirf(views),
            "tuition": brief("fee.tuition.annual", views.get("fee.tuition.annual")),
            "hostel": brief("facility.hostel", views.get("facility.hostel")),
            "medical": brief("facility.medical", views.get("facility.medical")),
            "station": brief("near.railway_station", views.get("near.railway_station")),
            "route": brief("admission.route", views.get("admission.route")),
            "website": ((views.get("location.website") or {}).get("value") or {}).get("url"),
        })
    sort = sort if sort in SORTS else "name"
    missing_last = 10 ** 9
    keys = {"name": lambda r: r["name"].lower(),
            "distance": lambda r: (r["distance_km"] if r["distance_km"] is not None else missing_last, r["name"]),
            "fee": lambda r: (r["tuition_per_year"] if r["tuition_per_year"] is not None else missing_last, r["name"]),
            "nirf": lambda r: (r["nirf_rank"] or missing_last, r["name"])}
    rows.sort(key=keys[sort])
    return {"total": len(rows), "colleges": rows[:limit], "sorted_by": sort, "left_out": left_out,
            "home": {"town": origin.name, "state": origin.state} if origin else None,
            "note": ("No overall score: compare the attributes that matter to you. Distances are straight-line, "
                     "from OpenStreetMap; every value shows its source and when it was checked.")}
