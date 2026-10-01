"""Loads MAYA's career library (app/seed/careers.json) into career_options.

Careers are matched by their stable `key`, so re-running updates them in place. Careers from
the old demo seed (no key) are replaced — their names, subjects and links are all covered by
the library.

Run on its own with:  python -m app.seed.careers
"""

import json
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.db import Base, SessionLocal, engine
from app.models.career import CareerOption

LIBRARY = Path(__file__).parent / "careers.json"
FIELDS = [
    "name", "category", "description", "required_subjects", "typical_entrance_exam_codes",
    "education_path", "skills_required", "timeline", "possible_challenges", "explore_next",
    "profile", "must", "details",
]
DEFAULTS = {
    "required_subjects": [], "typical_entrance_exam_codes": [], "skills_required": [],
    "possible_challenges": [], "explore_next": [], "profile": {}, "must": [], "details": {},
}


def load_library() -> list[dict]:
    return json.loads(LIBRARY.read_text())["careers"]


def _validate(entries: list[dict], dimensions: set[str] | None) -> None:
    keys = [e["key"] for e in entries]
    assert len(keys) == len(set(keys)), "duplicate career keys"
    for e in entries:
        assert e["profile"], f"{e['key']}: no profile"
        for related in e.get("related", []):
            assert related in keys, f"{e['key']}: related career '{related}' doesn't exist"
        if dimensions is not None:
            unknown = (set(e["profile"]) | set(e.get("must", []))) - dimensions
            assert not unknown, f"{e['key']}: unknown dimensions {unknown}"
        for section in ("overview", "how_to_prepare", "start_now", "resources", "roles", "earnings"):
            assert e["details"].get(section), f"{e['key']}: details.{section} is empty"


def seed_careers(db: Session) -> int:
    from app.services.assessment_engine import load_bank

    entries = load_library()
    _validate(entries, set(load_bank()["dimensions"]))

    db.query(CareerOption).filter(CareerOption.key.is_(None)).delete()
    by_key = {c.key: c for c in db.query(CareerOption).all()}
    for entry in entries:
        career = by_key.get(entry["key"]) or CareerOption(key=entry["key"])
        for field in FIELDS:
            setattr(career, field, entry.get(field, DEFAULTS.get(field, "")))
        db.add(career)
        by_key[entry["key"]] = career
    db.flush()
    for entry in entries:
        by_key[entry["key"]].related_career_ids = [by_key[k].id for k in entry.get("related", [])]
    db.commit()
    return len(entries)


def run() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        print(f"Loaded {seed_careers(db)} careers into the library.")
    finally:
        db.close()


if __name__ == "__main__":
    run()
