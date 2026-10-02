"""A college's facts by topic, for the API and for MAYA (docs/design/15-phase6-plan.md)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.facts import describe, store

TOPICS = {
    "fees": ("fee.",),
    "campus": ("facility.",),
    "location": ("location.", "near."),
    "admissions": ("admission.",),
    "rankings": ("ranking.",),
    "placements": ("placement.",),
}


def facts(db: Session, college_id: int, topic: str | None = None) -> dict[str, dict]:
    """FactViews for one college — one topic, or all of them."""
    out: dict[str, dict] = {}
    for prefix in (TOPICS[topic] if topic else tuple(p for ps in TOPICS.values() for p in ps)):
        out.update(store.current(db, "college", college_id, prefix=prefix))
    return out


def for_model(views: dict[str, dict]) -> list[dict]:
    """Short, plain lines for the LLM: what, the value in words, the year, how fresh, where from."""
    lines = []
    for attribute, v in sorted(views.items()):
        line = {"what": describe.name(attribute), "value": describe.value_text(attribute, v["value"]),
                "academic_year": v["academic_year"], "status": v["status"], "checked": v["label"]["en"],
                "source": v["source"]["name"], "official": v["source"]["official"], "document": v["source"]["document"],
                "url": v["source"]["url"]}
        if v["source"].get("locator"):
            line["where"] = v["source"]["locator"]
        if v["conflict"]:
            line["also_says"] = [{"value": describe.value_text(attribute, c["value"]), "source": c["source"]["name"]}
                                 for c in v["conflict"]]
        lines.append(line)
    return lines
